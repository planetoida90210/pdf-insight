"""Per-page text extraction: visible text layer, hidden-text filter, OCR for scanned pages."""

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO
from typing import Any, cast

import pdfplumber
import pypdfium2 as pdfium
from pdfplumber.utils.exceptions import PdfminerException
from PIL import Image

from app.config import Settings
from app.errors import ApiError, ErrorCode, WarningCode, warning
from app.injection import find_injection
from app.llm import OpenRouter, create_llm
from app.ocr import OCR_SCALE, render_page, render_scale, tesseract, transcribe
from app.prompts import PAGE_MARKER, PAGE_SEPARATOR
from app.ratelimit import DailyCounter
from app.schema import AnalysisWarning, OcrPage, PageInfo
from app.upload import open_pdf

logger = logging.getLogger(__name__)

# ~108 DPI: enough to tell a glyph from a flat background, cheap on a shared CPU.
VISIBILITY_SCALE = 1.5
# A glyph whose box has a smaller luminance spread is drawn in the background colour.
MIN_LUMINANCE_SPREAD = 15
# A page this much covered by images, with less text than SCAN_TEXT_CHARS, is a scan with a
# stamped header or page number on top: its content is in the image.
SCAN_IMAGE_SHARE = 0.5
SCAN_TEXT_CHARS = 200
# Glyphs whose font has no Unicode mapping: pdfminer's "(cid:N)", the replacement character and
# control codes. A text layer made mostly of them is unreadable.
UNMAPPED = re.compile(r"\(cid:\d+\)|[\x00-\x1f\x7f-\x9f\ufffd]")
# Vision calls in flight at once; each holds a rendered page and its PNG in the worker's memory.
VISION_CONCURRENCY = 4
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
    budget: DailyCounter,
    browser_ocr: dict[int, OcrPage],
) -> Extraction:
    """extract_pdf for the worker process, which builds its own vision client: an open HTTP
    client cannot cross the process boundary."""
    enabled = settings.vision_fallback and settings.openrouter_api_key
    vision = create_llm(settings, budget) if enabled else None
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
    except (PdfminerException, pdfium.PdfiumError) as error:
        # The two parsers disagree on damaged files: pdfium repairs some that pdfminer cannot
        # parse, pdfminer finds pages that pdfium cannot load.
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
    with open_pdf(data, settings.max_pages) as pdf, pdfplumber.open(BytesIO(data)) as plumber:
        if any(number > len(pdf) for number in browser_ocr):
            raise ApiError(ErrorCode.INVALID_REQUEST)
        for number, page in enumerate(plumber.pages, start=1):
            read = _read_page(pdf, page, number, settings, browser_ocr.get(number))
            # pdfplumber keeps every parsed page otherwise; long documents would outgrow
            # the worker's memory cap.
            page.close()
            chars += len(read.text)
            if chars > settings.max_text_chars:
                raise ApiError(ErrorCode.TEXT_TOO_LONG)
            pages.append(read)
        if vision is not None:
            _transcribe_unsure(pdf, pages, vision, settings, deadline)
    return Extraction(
        file_name=file_name,
        pages=[f"{PAGE_MARKER.format(page=p.info.page)}\n{p.text}" for p in pages if p.text],
        page_info=[p.info for p in pages],
        warnings=[w for p in pages for w in _page_warnings(p, settings.ocr_min_confidence)],
    )


def _read_page(
    pdf: pdfium.PdfDocument, page: Any, number: int, settings: Settings, browser: OcrPage | None
) -> _PageText:
    """The visible text layer, or the page's OCR text when it needs OCR: the browser's if it
    sent one, else Tesseract's."""
    pdf_page = pdf[number - 1]
    scale = render_scale(pdf_page, VISIBILITY_SCALE)
    visible, hidden = _visible_and_hidden_text(page, render_page(pdf_page, scale), scale)
    if not needs_ocr(visible, _image_share(page), settings.ocr_min_chars):
        info = PageInfo(page=number, method="text", chars=len(visible), confidence=None)
        return _PageText(info, visible, hidden)
    if browser is None:
        text, confidence = tesseract(render_page(pdf_page, OCR_SCALE), settings.ocr_lang)
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
    """Gives pages that OCR read with low confidence a vision model's text, in parallel."""
    unsure = [
        page
        for page in pages
        if page.info.confidence is not None and page.info.confidence < settings.ocr_min_confidence
    ]
    # pdfium must not be called from two threads at once.
    render_lock = threading.Lock()

    def read(page: _PageText) -> str:
        with render_lock:
            image = render_page(pdf[page.info.page - 1], OCR_SCALE)
        timeout = min(settings.llm_timeout_seconds, deadline - time.monotonic())
        return transcribe(vision, image, timeout)

    with ThreadPoolExecutor(VISION_CONCURRENCY) as pool:
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


def _image_share(page: Any) -> float:
    """The part of the page covered by images, overlaps counted twice."""
    x0, top, x1, bottom = page.bbox
    covered = sum(
        max(min(image["x1"], x1) - max(image["x0"], x0), 0)
        * max(min(image["bottom"], bottom) - max(image["top"], top), 0)
        for image in page.images
    )
    area = (x1 - x0) * (bottom - top)
    return float(covered / area) if area else 0.0


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


def _visible_and_hidden_text(page: Any, rendered: Image.Image, scale: float) -> tuple[str, str]:
    """Splits the text layer by what the rendered page actually shows.

    Whitespace glyphs are kept on both sides so pdfplumber can lay out words and lines.
    """
    gray = rendered.convert("L")
    hidden = {
        id(char)
        for char in page.chars
        if not char["text"].isspace() and not _glyph_visible(char, gray, scale)
    }
    if not hidden:
        return page.extract_text().strip(), ""
    visible = page.filter(lambda obj: id(obj) not in hidden).extract_text()
    hidden_text = page.filter(
        lambda obj: id(obj) in hidden or (obj["object_type"] == "char" and obj["text"].isspace())
    ).extract_text()
    return visible.strip(), " ".join(hidden_text.split())


def _glyph_visible(char: dict[str, Any], gray: Image.Image, scale: float) -> bool:
    """Tiny, off-page or flat-coloured glyphs (e.g. white on white) are not visible."""
    x0, top, x1, bottom = (int(char[key] * scale) for key in ("x0", "top", "x1", "bottom"))
    box = (
        max(x0, 0),
        max(top, 0),
        min(max(x1, x0 + 1), gray.width),
        min(max(bottom, top + 1), gray.height),
    )
    if char["size"] < 1 or box[0] >= box[2] or box[1] >= box[3]:
        return False
    low, high = cast(tuple[int, int], gray.crop(box).getextrema())  # one band in mode "L"
    return bool(high - low >= MIN_LUMINANCE_SPREAD)
