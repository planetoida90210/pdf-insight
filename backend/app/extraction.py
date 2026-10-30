"""Per-page text extraction: visible text layer, hidden-text filter, OCR for scanned pages."""

import heapq
import logging
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from typing import cast

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from PIL import Image

from app.config import Settings
from app.errors import ApiError, ErrorCode, WarningCode, warning
from app.injection import find_injection
from app.llm import OpenRouter, create_llm
from app.ocr import OCR_SCALE, render_page, render_scale, tesseract, transcribe
from app.prompts import PAGE_MARKER, PAGE_SEPARATOR
from app.ratelimit import Charge
from app.schema import AnalysisWarning, OcrPage, PageInfo
from app.upload import open_pdf

logger = logging.getLogger(__name__)

# ~108 DPI: enough to tell a glyph from a flat background, cheap on a shared CPU.
VISIBILITY_SCALE = 1.5
# A glyph whose box has a smaller luminance spread is drawn in the background colour.
MIN_LUMINANCE_SPREAD = 15
# Glyphs smaller than this, in points, are not meant to be read.
MIN_GLYPH_SIZE = 1
# A page this much covered by images, with less text than SCAN_TEXT_CHARS, is a scan with a
# stamped header or page number on top: its content is in the image.
SCAN_IMAGE_SHARE = 0.5
SCAN_TEXT_CHARS = 200
# Glyphs whose font has no Unicode mapping: pdfium and pdf.js give their raw character codes,
# mostly control codes, and the visible text has U+FFFD for them. A text layer made mostly of
# them is unreadable.
UNMAPPED = re.compile(r"[\x00-\x1f\x7f-\x9f\ufffd]")
HYPHEN_AT_LINE_END = 0x2
# The web process kills the worker EXTRACT_TIMEOUT_SECONDS after starting it. Vision calls end
# this much earlier, so the worker still sends its result back in time.
DEADLINE_MARGIN_SECONDS = 5


@dataclass(slots=True)
class Extraction:
    file_name: str
    pages: list[str]  # PAGE_MARKER line + text, only pages that have text
    page_info: list[PageInfo]
    warnings: list[AnalysisWarning]

    @property
    def text(self) -> str:
        return PAGE_SEPARATOR.join(self.pages)


@dataclass(slots=True)
class _PageText:
    info: PageInfo
    text: str
    hidden: str  # the invisible part of the text layer, quoted in the HIDDEN_TEXT warning


def read_pdf(
    data: bytes,
    file_name: str,
    settings: Settings,
    charge: Charge,
    browser_ocr: dict[int, OcrPage],
) -> Extraction:
    """extract_pdf for the worker process, which builds its own vision client: an open HTTP
    client cannot cross the process boundary. Its calls are taken through `charge`."""
    enabled = settings.vision_fallback and settings.openrouter_api_key
    vision = create_llm(settings, charge) if enabled else None
    return extract_pdf(data, file_name, settings, vision=vision, browser_ocr=browser_ocr)


def extract_pdf(
    data: bytes,
    file_name: str,
    settings: Settings,
    *,
    vision: OpenRouter | None,
    browser_ocr: dict[int, OcrPage],
) -> Extraction:
    """The visible text of every page and its warnings; ApiError when the file cannot be read.

    `browser_ocr` is the text the browser read from pages it took for scans; it replaces
    Tesseract on the pages that need OCR.
    """
    try:
        result = _read_pages(data, file_name, settings, vision, browser_ocr)
    except pdfium.PdfiumError as error:
        raise ApiError(ErrorCode.INVALID_PDF) from error
    if not result.pages:
        raise ApiError(ErrorCode.NO_TEXT)
    if injection := find_injection(result.text):
        result.warnings.append(warning(WarningCode.INJECTION_SUSPECTED, snippet=injection))
    logger.info(
        "extracted pages=%s chars=%s warnings=%s",
        len(result.page_info),
        len(result.text),
        [w.code for w in result.warnings],
    )
    return result


def _read_pages(
    data: bytes,
    file_name: str,
    settings: Settings,
    vision: OpenRouter | None,
    browser_ocr: dict[int, OcrPage],
) -> Extraction:
    deadline = time.monotonic() + settings.extract_timeout_seconds - DEADLINE_MARGIN_SECONDS
    pages: list[_PageText] = []
    chars = 0
    with open_pdf(data, settings.max_pages) as pdf:
        if any(number > len(pdf) for number in browser_ocr):
            raise ApiError(ErrorCode.INVALID_REQUEST)
        if _text_layer_chars(pdf) > settings.max_text_chars:
            raise ApiError(ErrorCode.TEXT_TOO_LONG)
        for number in range(1, len(pdf) + 1):
            # Closed after reading: long documents would outgrow the worker's memory cap.
            with closing(pdf[number - 1]) as page:
                read = _read_page(page, number, settings, browser_ocr.get(number))
            chars += len(read.text)
            if chars > settings.max_text_chars:
                raise ApiError(ErrorCode.TEXT_TOO_LONG)
            pages.append(read)
        if vision is not None:
            _transcribe_unsure(pdf, pages, vision, settings, deadline)
            # A transcript can be longer than the OCR text it replaced.
            if sum(len(page.text) for page in pages) > settings.max_text_chars:
                raise ApiError(ErrorCode.TEXT_TOO_LONG)
    return Extraction(
        file_name=file_name,
        pages=[f"{PAGE_MARKER.format(page=p.info.page)}\n{p.text}" for p in pages if p.text],
        page_info=[p.info for p in pages],
        warnings=[w for p in pages for w in _page_warnings(p, settings.ocr_min_confidence)],
    )


def _text_layer_chars(pdf: pdfium.PdfDocument) -> int:
    """Every glyph of every text layer, hidden ones included: more than the visible text, and
    cheap to count, so a document with too much text is refused before any page is rendered."""
    total = 0
    for index in range(len(pdf)):
        with closing(pdf[index]) as page, closing(page.get_textpage()) as text:
            total += text.count_chars()
    return total


def _read_page(
    page: pdfium.PdfPage, number: int, settings: Settings, browser: OcrPage | None
) -> _PageText:
    """The visible text layer, or the page's OCR text when it needs OCR: the browser's if it
    sent one, else Tesseract's."""
    if 0 in page.get_size():
        # A crop box outside the media box leaves nothing to show, and nothing to render.
        return _PageText(PageInfo(page=number, method="text", chars=0, confidence=None), "", "")
    visible, hidden = _visible_and_hidden_text(page)
    if not needs_ocr(visible, _image_share(page), settings.ocr_min_chars):
        info = PageInfo(page=number, method="text", chars=len(visible), confidence=None)
        return _PageText(info, visible, hidden)
    if browser is None:
        text, confidence = tesseract(render_page(page, OCR_SCALE), settings.ocr_lang)
    else:
        text, confidence = browser.text.strip(), browser.confidence
    info = PageInfo(page=number, method="ocr", chars=len(text), confidence=confidence)
    return _PageText(info, text, hidden)


def _transcribe_unsure(
    pdf: pdfium.PdfDocument,
    pages: list[_PageText],
    vision: OpenRouter,
    settings: Settings,
    deadline: float,
) -> None:
    """Gives the OCR pages under OCR_MIN_CONFIDENCE a vision model's text, the
    VISION_MAX_PAGES least confident of them, in one parallel round."""
    scored = [
        (page.info.confidence, page)
        for page in pages
        if page.info.confidence is not None and page.info.confidence < settings.ocr_min_confidence
    ]
    lowest = heapq.nsmallest(settings.vision_max_pages, scored, key=lambda item: item[0])
    unsure = [page for _, page in lowest]
    if not unsure:
        return
    # pdfium must not be called from two threads at once.
    render_lock = threading.Lock()

    def read(page: _PageText) -> str:
        with render_lock:
            # Pages left when the time is up keep their OCR text without being rendered.
            if time.monotonic() >= deadline:
                return ""
            with closing(pdf[page.info.page - 1]) as pdf_page:
                image = render_page(pdf_page, OCR_SCALE)
        timeout = min(settings.llm_timeout_seconds, deadline - time.monotonic())
        return transcribe(vision, image, timeout)

    with ThreadPoolExecutor(len(unsure)) as pool:
        for page, transcript in zip(unsure, pool.map(read, unsure), strict=True):
            if transcript:
                number = page.info.page
                page.text = transcript
                page.info = PageInfo(
                    page=number, method="vision", chars=len(transcript), confidence=None
                )


def needs_ocr(text: str, image_share: float, min_chars: int) -> bool:
    """Too little text, an unreadable text layer, or a scan under a short text overlay."""
    chars = "".join(text.split())
    unmapped = sum(len(match) for match in UNMAPPED.findall(chars))
    return (
        len(chars) < min_chars
        or unmapped * 2 > len(chars)
        or (image_share >= SCAN_IMAGE_SHARE and len(chars) < SCAN_TEXT_CHARS)
    )


def _image_share(page: pdfium.PdfPage) -> float:
    """The part of the page covered by images, overlaps counted twice."""
    left, bottom, right, top = page.get_bbox()
    covered = 0.0
    for image in page.get_objects([pdfium_raw.FPDF_PAGEOBJ_IMAGE]):
        x0, y0, x1, y1 = _page_bounds(image)
        covered += max(min(x1, right) - max(x0, left), 0) * max(min(y1, top) - max(y0, bottom), 0)
    area = (right - left) * (top - bottom)
    return covered / area if area else 0.0


def _page_bounds(obj: pdfium.PdfObject) -> tuple[float, float, float, float]:
    """An object's bounds on the page; pdfium gives them in the space of the form XObject that
    holds the object."""
    bounds: tuple[float, float, float, float] = obj.get_bounds()
    form = obj.container
    while form is not None:
        bounds = form.get_matrix().on_rect(*bounds)
        form = form.container
    return bounds


def _page_warnings(page: _PageText, min_confidence: float) -> list[AnalysisWarning]:
    number, method, confidence = page.info.page, page.info.method, page.info.confidence
    warnings = (
        [warning(WarningCode.HIDDEN_TEXT, number, snippet=page.hidden)] if page.hidden else []
    )
    if method == "text":
        return warnings
    used = WarningCode.VISION_USED if method == "vision" else WarningCode.OCR_USED
    warnings.append(warning(used, number))
    if confidence is not None and confidence < min_confidence:
        warnings.append(warning(WarningCode.OCR_LOW_CONFIDENCE, number, confidence=confidence))
    return warnings


def _visible_and_hidden_text(page: pdfium.PdfPage) -> tuple[str, str]:
    """Splits the text layer by what the rendered page actually shows.

    Whitespace, including the spaces and line breaks pdfium generates between words and lines,
    goes to both sides. A glyph without a Unicode mapping becomes U+FFFD and is never hidden: a
    space among such glyphs draws nothing as well.
    """
    with closing(page.render(scale=render_scale(page, VISIBILITY_SCALE))) as bitmap:
        gray = bitmap.to_pil().convert("L")
        to_pixels = _pixel_transform(page, bitmap)
    visible: list[str] = []
    hidden: list[str] = []
    box = pdfium_raw.FS_RECTF()
    with closing(page.get_textpage()) as text:
        for index in range(text.count_chars()):
            char = _char(text, index)
            if UNMAPPED.fullmatch(char) and not pdfium_raw.FPDFText_IsGenerated(text, index):
                visible.append("\ufffd")
            elif char.isspace():
                visible.append(char)
                hidden.append(char)
            else:
                pdfium_raw.FPDFText_GetLooseCharBox(text, index, box)
                (visible if _glyph_visible(box, to_pixels, gray) else hidden).append(char)
    lines = (line.strip() for line in "".join(visible).splitlines())
    return "\n".join(line for line in lines if line), " ".join("".join(hidden).split())


def _char(text: pdfium.PdfTextPage, index: int) -> str:
    """The character of a glyph. pdfium gives a hyphen that splits a word at a line end as
    U+0002. A broken ToUnicode map can give a lone surrogate or a value past U+10FFFF, which
    UTF-8 cannot encode: those count as unmapped."""
    code = pdfium_raw.FPDFText_GetUnicode(text, index)
    if code == HYPHEN_AT_LINE_END and pdfium_raw.FPDFText_IsHyphen(text, index):
        return "-"
    return chr(code) if code < 0xD800 or 0xE000 <= code < 0x110000 else "\ufffd"


PixelTransform = Callable[[float, float], tuple[float, float]]


def _pixel_transform(page: pdfium.PdfPage, bitmap: pdfium.PdfBitmap) -> PixelTransform:
    """Maps page coordinates to the bitmap's pixels like the renderer does (crop box, /Rotate,
    scale). The mapping is affine, so three corners of the page fix it and a glyph costs no
    pdfium call."""
    to_bitmap = bitmap.get_posconv(page).to_bitmap
    left, bottom, right, top = page.get_bbox()
    x0, y0 = to_bitmap(left, bottom)
    x1, y1 = to_bitmap(right, bottom)
    x2, y2 = to_bitmap(left, top)

    def to_pixels(x: float, y: float) -> tuple[float, float]:
        u, v = (x - left) / (right - left), (y - bottom) / (top - bottom)
        return x0 + u * (x1 - x0) + v * (x2 - x0), y0 + u * (y1 - y0) + v * (y2 - y0)

    return to_pixels


def _glyph_visible(box: pdfium_raw.FS_RECTF, to_pixels: PixelTransform, gray: Image.Image) -> bool:
    """Tiny, off-page or flat-coloured glyphs (e.g. white on white) are not visible."""
    if max(box.right - box.left, box.top - box.bottom) < MIN_GLYPH_SIZE:
        return False
    (x0, y0), (x1, y1) = to_pixels(box.left, box.bottom), to_pixels(box.right, box.top)
    left, right = sorted((int(x0), int(x1)))
    top, bottom = sorted((int(y0), int(y1)))
    crop = (
        max(left, 0),
        max(top, 0),
        min(max(right, left + 1), gray.width),
        min(max(bottom, top + 1), gray.height),
    )
    if crop[0] >= crop[2] or crop[1] >= crop[3]:
        return False
    low, high = cast(tuple[int, int], gray.crop(crop).getextrema())  # one band in mode "L"
    return bool(high - low >= MIN_LUMINANCE_SPREAD)
