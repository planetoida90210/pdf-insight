"""Per-page text extraction: visible text layer, hidden-text filter, OCR for scanned pages."""

import logging
import re
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


@dataclass(slots=True)
class Extraction:
    file_name: str
    pages: list[str]  # PAGE_MARKER line + text, only pages that have text
    page_info: list[PageInfo]
    warnings: list[AnalysisWarning]

    @property
    def text(self) -> str:
        return PAGE_SEPARATOR.join(self.pages)


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
    result = Extraction(file_name=file_name, pages=[], page_info=[], warnings=[])
    chars = 0
    with open_pdf(data, settings.max_pages) as pdf, pdfplumber.open(BytesIO(data)) as plumber:
        if any(number > len(pdf) for number in browser_ocr):
            raise ApiError(ErrorCode.INVALID_REQUEST)
        for number, page in enumerate(plumber.pages, start=1):
            browser = browser_ocr.get(number)
            info, text, warnings = _read_page(pdf, page, number, settings, vision, browser)
            # pdfplumber keeps every parsed page otherwise; long documents would outgrow
            # the worker's memory cap.
            page.close()
            chars += len(text)
            if chars > settings.max_text_chars:
                raise ApiError(ErrorCode.TEXT_TOO_LONG)
            result.page_info.append(info)
            result.warnings.extend(warnings)
            if text:
                result.pages.append(f"{PAGE_MARKER.format(page=number)}\n{text}")
    return result


def _read_page(
    pdf: pdfium.PdfDocument,
    page: Any,
    number: int,
    settings: Settings,
    vision: OpenRouter | None,
    browser: OcrPage | None,
) -> tuple[PageInfo, str, list[AnalysisWarning]]:
    """The visible text layer, or the page's OCR text when it needs OCR: the browser's if sent,
    else Tesseract's; a vision model's when either is unsure."""
    pdf_page = pdf[number - 1]
    scale = render_scale(pdf_page, VISIBILITY_SCALE)
    visible, hidden = _visible_and_hidden_text(page, render_page(pdf_page, scale), scale)
    warnings = [warning(WarningCode.HIDDEN_TEXT, number, snippet=hidden)] if hidden else []
    text_info = PageInfo(page=number, method="text", chars=len(visible), confidence=None)
    if not needs_ocr(visible, _image_share(page), settings.ocr_min_chars):
        return text_info, visible, warnings

    if browser is None:
        text, confidence = tesseract(render_page(pdf_page, OCR_SCALE), settings.ocr_lang)
    else:
        text, confidence = browser.text.strip(), browser.confidence
    info = PageInfo(page=number, method="ocr", chars=len(text), confidence=confidence)
    if (
        vision is not None
        and confidence < settings.ocr_min_confidence
        and (transcript := transcribe(vision, render_page(pdf_page, OCR_SCALE)))
    ):
        text = transcript
        info = PageInfo(page=number, method="vision", chars=len(text), confidence=None)
    return info, text, warnings + _ocr_warnings(info, settings.ocr_min_confidence)


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


def _ocr_warnings(info: PageInfo, min_confidence: float) -> list[AnalysisWarning]:
    used = WarningCode.VISION_USED if info.method == "vision" else WarningCode.OCR_USED
    warnings = [warning(used, info.page)]
    if info.confidence is not None and info.confidence < min_confidence:
        confidence = info.confidence
        warnings.append(warning(WarningCode.OCR_LOW_CONFIDENCE, info.page, confidence=confidence))
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
