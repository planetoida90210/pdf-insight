"""Page rendering and reading text from a page image: Tesseract, or a vision model."""

import io
import logging
import math

import pypdfium2 as pdfium
import pytesseract
from PIL import Image

from app.errors import ApiError
from app.llm import OpenRouter
from app.prompts import VISION_PROMPT, VISION_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# 200 DPI (PDF user space is 72 units per inch): on the test scan it reads the same words with the
# same confidence as 300 DPI in about 60% of the time.
OCR_SCALE = 200 / 72
# About A4 at 300 DPI. Larger pages render at a lower scale, so a huge page box cannot
# allocate gigabytes for one bitmap.
MAX_RENDER_PIXELS = 9_000_000


def render_scale(page: pdfium.PdfPage, scale: float) -> float:
    """`scale`, lowered when the bitmap would exceed MAX_RENDER_PIXELS."""
    width, height = page.get_size()
    return min(scale, math.sqrt(MAX_RENDER_PIXELS / max(width * height, 1)))


def render_page(page: pdfium.PdfPage, scale: float) -> Image.Image:
    image: Image.Image = page.render(scale=render_scale(page, scale)).to_pil()
    return image.convert("RGB")


def tesseract(image: Image.Image, lang: str) -> tuple[str, float]:
    """Text with Tesseract's line breaks, plus the mean word confidence (0 when nothing is read)."""
    data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
    lines: dict[tuple[int, int, int], list[str]] = {}
    confidences: list[float] = []
    for i, word in enumerate(data["text"]):
        confidence = float(data["conf"][i])
        if confidence < 0 or not word.strip():
            continue
        line = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(line, []).append(word.strip())
        confidences.append(confidence)
    text = "\n".join(" ".join(words) for words in lines.values())
    return text, sum(confidences) / len(confidences) if confidences else 0.0


def transcribe(vision: OpenRouter, image: Image.Image, timeout: float) -> str:
    """Vision is a best-effort fallback: a provider error or no time left keeps the OCR text."""
    if timeout <= 0:
        return ""
    png = io.BytesIO()
    image.save(png, format="PNG")
    try:
        text = vision.generate(
            system=VISION_SYSTEM_PROMPT,
            prompt=VISION_PROMPT,
            image_png=png.getvalue(),
            timeout=timeout,
        )
        return text.strip()
    except ApiError as error:
        logger.warning("vision fallback failed code=%s", error.code)
        return ""
