"""Per-page text extraction: visible text layer, hidden-text filter, OCR for scanned pages."""

import logging
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
from app.ocr import OcrResult, ocr_page, render_page, render_scale
from app.prompts import PAGE_MARKER, PAGE_SEPARATOR
from app.ratelimit import DailyCounter
from app.schema import AnalysisWarning, PageInfo
from app.upload import open_pdf

logger = logging.getLogger(__name__)

# ~108 DPI: enough to tell a glyph from a flat background, cheap on a shared CPU.
VISIBILITY_SCALE = 1.5
# A glyph whose box has a smaller luminance spread is drawn in the background colour.
MIN_LUMINANCE_SPREAD = 15


@dataclass(slots=True)
class Extraction:
    file_name: str
    pages: list[str]  # PAGE_MARKER line + text, only pages that have text
    page_info: list[PageInfo]
    warnings: list[AnalysisWarning]

    @property
    def text(self) -> str:
        return PAGE_SEPARATOR.join(self.pages)


def read_pdf(data: bytes, file_name: str, settings: Settings, budget: DailyCounter) -> Extraction:
    """extract_pdf for the worker process, which builds its own vision client: an open HTTP
    client cannot cross the process boundary."""
    enabled = settings.vision_fallback and settings.openrouter_api_key
    vision = create_llm(settings, budget) if enabled else None
    return extract_pdf(data, file_name, settings, vision=vision)


def extract_pdf(
    data: bytes, file_name: str, settings: Settings, *, vision: OpenRouter | None
) -> Extraction:
    """The visible text of every page and its warnings; ApiError when the file cannot be read."""
    try:
        result = _read_pages(data, file_name, settings, vision)
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
    data: bytes, file_name: str, settings: Settings, vision: OpenRouter | None
) -> Extraction:
    result = Extraction(file_name=file_name, pages=[], page_info=[], warnings=[])
    with open_pdf(data, settings.max_pages) as pdf, pdfplumber.open(BytesIO(data)) as plumber:
        for number, page in enumerate(plumber.pages, start=1):
            room = settings.max_text_chars - sum(len(text) for text in result.pages)
            if room <= 0:
                result.page_info.append(
                    PageInfo(page=number, method="text", chars=0, confidence=None)
                )
                continue
            ocr_pages = sum(info.method != "text" for info in result.page_info)
            ocr_allowed = ocr_pages < settings.max_ocr_pages
            info, text, warnings = _read_page(pdf, page, number, settings, vision, ocr_allowed)
            # pdfplumber keeps every parsed page otherwise; long documents would outgrow
            # the worker's memory cap.
            page.close()
            result.page_info.append(info)
            result.warnings.extend(warnings)
            if len(text) >= room:
                text = text[:room]
                limit = settings.max_text_chars
                result.warnings.append(warning(WarningCode.TEXT_LIMIT, number, limit=limit))
            if text:
                result.pages.append(f"{PAGE_MARKER.format(page=number)}\n{text}")
    return result


def _read_page(
    pdf: pdfium.PdfDocument,
    page: Any,
    number: int,
    settings: Settings,
    vision: OpenRouter | None,
    ocr_allowed: bool,
) -> tuple[PageInfo, str, list[AnalysisWarning]]:
    """The text layer when it has enough visible text, else the OCR text of the rendered page."""
    pdf_page = pdf[number - 1]
    scale = render_scale(pdf_page, VISIBILITY_SCALE)
    visible, hidden = _visible_and_hidden_text(page, render_page(pdf_page, scale), scale)
    warnings = [warning(WarningCode.HIDDEN_TEXT, number, snippet=hidden)] if hidden else []
    text_info = PageInfo(page=number, method="text", chars=len(visible), confidence=None)
    if len(visible) >= settings.ocr_min_chars:
        return text_info, visible, warnings
    if not ocr_allowed:
        warnings.append(warning(WarningCode.PAGES_SKIPPED, number, limit=settings.max_ocr_pages))
        return text_info, visible, warnings

    ocr = ocr_page(
        pdf_page,
        lang=settings.ocr_lang,
        min_confidence=settings.ocr_min_confidence,
        vision=vision,
    )
    warnings += _ocr_warnings(ocr, number, settings.ocr_min_confidence)
    info = PageInfo(page=number, method=ocr.method, chars=len(ocr.text), confidence=ocr.confidence)
    return info, ocr.text, warnings


def _ocr_warnings(ocr: OcrResult, number: int, min_confidence: float) -> list[AnalysisWarning]:
    used = WarningCode.VISION_USED if ocr.method == "vision" else WarningCode.OCR_USED
    warnings = [warning(used, number)]
    if ocr.confidence is not None and ocr.confidence < min_confidence:
        warnings.append(warning(WarningCode.OCR_LOW_CONFIDENCE, number, confidence=ocr.confidence))
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
