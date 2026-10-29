"""Page rendering and Tesseract OCR, with optional vision-LLM fallback."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import pypdfium2 as pdfium
import pytesseract
from PIL import Image

logger = logging.getLogger("pdf_insight")

# ~300 DPI relative to a 72 pt PDF page.
OCR_RENDER_SCALE = 300 / 72


@dataclass(frozen=True, slots=True)
class OcrResult:
    text: str
    confidence: float
    method: str = "ocr"  # "ocr" | "vision" once B3 wires the fallback


def render_page(pdf: pdfium.PdfDocument, page_index: int, scale: float) -> Image.Image:
    bitmap = pdf[page_index].render(scale=scale)
    image = bitmap.to_pil().convert("RGB")
    assert isinstance(image, Image.Image)
    return image


def ocr_image(image: Image.Image, lang: str) -> OcrResult:
    """Runs Tesseract `image_to_data` and returns text + mean word confidence."""
    try:
        data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractNotFoundError as error:
        raise RuntimeError("tesseract binary is not installed") from error
    words: list[str] = []
    confidences: list[float] = []
    for text, conf in zip(data["text"], data["conf"], strict=True):
        try:
            score = float(conf)
        except (TypeError, ValueError):
            continue
        if score < 0:
            continue
        token = (text or "").strip()
        if not token:
            continue
        words.append(token)
        confidences.append(score)
    mean = sum(confidences) / len(confidences) if confidences else 0.0
    return OcrResult(text=" ".join(words), confidence=mean)


VisionFallback = Callable[[Image.Image], OcrResult | None]


def vision_fallback(_image: Image.Image) -> OcrResult | None:
    """No-op default; extract passes make_vision_fallback(transport) when enabled."""
    return None


def ocr_page(
    pdf: pdfium.PdfDocument,
    page_index: int,
    *,
    lang: str,
    min_confidence: float,
    vision_enabled: bool,
    vision: VisionFallback = vision_fallback,
) -> OcrResult:
    image = render_page(pdf, page_index, OCR_RENDER_SCALE)
    result = ocr_image(image, lang)
    if vision_enabled and (result.confidence < min_confidence or len(result.text.strip()) < 10):
        fallback = vision(image)
        if fallback is not None:
            logger.info("vision fallback used for page %s", page_index + 1)
            return fallback
    return result
