"""Which pages need OCR, page rendering, and reading a page image: Tesseract or a vision model."""

import io
import logging
import math
import re

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
# Words read under NOISE_CONFIDENCE are mostly stamps, signatures and specks that Tesseract took
# for text; clean scans have them too. A word read at SURE_CONFIDENCE or more is almost always
# right.
NOISE_CONFIDENCE = 50
SURE_CONFIDENCE = 90
# A page this much covered by images, with less text than SCAN_TEXT_CHARS, is a scan with a
# stamped header or page number on top: its content is in the image.
SCAN_IMAGE_SHARE = 0.5
SCAN_TEXT_CHARS = 200
# Glyphs whose font has no Unicode mapping: pdfium and pdf.js give their raw character codes,
# mostly control codes, and the visible text has U+FFFD for them. A text layer made mostly of
# them is unreadable.
UNMAPPED = re.compile(r"[\x00-\x1f\x7f-\x9f\ufffd]")


def render_scale(page: pdfium.PdfPage, scale: float) -> float:
    """`scale`, lowered when the bitmap would exceed MAX_RENDER_PIXELS."""
    width, height = page.get_size()
    return min(scale, math.sqrt(MAX_RENDER_PIXELS / max(width * height, 1)))


def render_page(page: pdfium.PdfPage, scale: float) -> Image.Image:
    image: Image.Image = page.render(scale=render_scale(page, scale)).to_pil()
    return image.convert("RGB")


def needs_ocr(text: str, image_share: float, min_chars: int) -> bool:
    """Too little text, an unreadable text layer, or a scan under a short text overlay. Same rule
    as needsOcr in src/lib/ocr.ts."""
    chars = "".join(text.split())
    unmapped = sum(len(match) for match in UNMAPPED.findall(chars))
    return (
        len(chars) < min_chars
        or unmapped * 2 > len(chars)
        or (image_share >= SCAN_IMAGE_SHARE and len(chars) < SCAN_TEXT_CHARS)
    )


def page_confidence(confidences: list[float]) -> float:
    """The percentage of a page's words read at SURE_CONFIDENCE, among the words that are not
    noise; 0 when there are none. Same measure as pageConfidence in src/lib/ocr.ts.

    The mean word confidence cannot tell a blurred photo, read with a few confident mistakes,
    from a clean scan whose stamp adds noise words."""
    words = [confidence for confidence in confidences if confidence >= NOISE_CONFIDENCE]
    if not words:
        return 0.0
    return 100 * sum(confidence >= SURE_CONFIDENCE for confidence in words) / len(words)


def tesseract(image: Image.Image, lang: str) -> tuple[str, float]:
    """Text with Tesseract's line breaks, plus its page_confidence."""
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
    return text, page_confidence(confidences)


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
