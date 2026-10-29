"""Per-page PDF text extraction with render-based hidden-text filtering."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from io import BytesIO
from typing import Literal

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image

from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.injection import scan_injection
from app.ocr import VisionFallback, ocr_page, render_page, vision_fallback
from app.schema import AnalysisWarning, PageInfo

logger = logging.getLogger("pdf_insight")

# Render scale for visibility checks (~144 DPI). Kept low so filtering stays cheap.
VISIBILITY_SCALE = 2.0
# max-min luminance below this => glyph region is flat (same colour as background).
LUMINANCE_THRESHOLD = 15.0
HIDDEN_SNIPPET_MAX = 160


@dataclass(slots=True)
class PageResult:
    page: int
    method: Literal["text", "ocr", "vision"]
    text: str
    chars: int
    confidence: float | None
    hidden_snippet: str | None = None


@dataclass(slots=True)
class ExtractionResult:
    pages: int
    page_results: list[PageResult]
    text: str
    chars: int
    page_info: list[PageInfo]
    warnings: list[AnalysisWarning] = field(default_factory=list)


def _luminance_spread(region: Image.Image) -> float:
    if region.width == 0 or region.height == 0:
        return 0.0
    extrema = region.convert("L").getextrema()
    # Mode "L" returns (min, max); multi-band modes return a nested tuple.
    if isinstance(extrema[0], tuple):
        return 0.0
    low, high = extrema
    return float(high - low)


def _char_visible(
    char: dict[str, object],
    page_width: float,
    page_height: float,
    rendered: Image.Image,
    scale: float,
) -> bool:
    size = float(char.get("size") or 0)  # type: ignore[arg-type]
    x0 = float(char["x0"])  # type: ignore[arg-type]
    x1 = float(char["x1"])  # type: ignore[arg-type]
    top = float(char["top"])  # type: ignore[arg-type]
    bottom = float(char["bottom"])  # type: ignore[arg-type]
    if size < 1.0 or x1 <= 0 or bottom <= 0 or x0 >= page_width or top >= page_height:
        return False
    px0 = int(max(0, x0 * scale))
    px1 = int(min(rendered.width, max(px0 + 1, x1 * scale)))
    py0 = int(max(0, top * scale))
    py1 = int(min(rendered.height, max(py0 + 1, bottom * scale)))
    region = rendered.crop((px0, py0, px1, py1))
    return _luminance_spread(region) >= LUMINANCE_THRESHOLD


def _split_visible_hidden(
    chars: list[dict[str, object]],
    page_width: float,
    page_height: float,
    rendered: Image.Image,
    scale: float,
) -> tuple[str, str]:
    """Classify non-whitespace glyphs; whitespace follows the previous glyph's class."""
    visible: list[str] = []
    hidden: list[str] = []
    prev_hidden = False
    for char in chars:
        text = str(char.get("text") or "")
        if not text:
            continue
        if text.isspace():
            (hidden if prev_hidden else visible).append(text)
            continue
        is_hidden = not _char_visible(char, page_width, page_height, rendered, scale)
        prev_hidden = is_hidden
        (hidden if is_hidden else visible).append(text)
    return "".join(visible), "".join(hidden)


def _snippet(text: str, limit: int = HIDDEN_SNIPPET_MAX) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _page_marker(page: int) -> str:
    return f"[Strona {page}]"


def extract_pdf(
    data: bytes,
    settings: Settings,
    *,
    vision: VisionFallback | None = None,
) -> ExtractionResult:
    """Extract visible text, OCR sparse pages, assemble warnings and markers."""
    warnings: list[AnalysisWarning] = []
    page_results: list[PageResult] = []
    ocr_used = 0
    vision_fn: VisionFallback = vision or vision_fallback

    # pdfplumber for char boxes; pdfium for rendering (and later OCR).
    with pdfplumber.open(BytesIO(data)) as plumber, pdfium.PdfDocument(data) as pdf:
        page_count = len(plumber.pages)
        if page_count == 0:
            raise ApiError(ErrorCode.INVALID_PDF)

        for index, plumber_page in enumerate(plumber.pages):
            page_no = index + 1
            rendered = render_page(pdf, index, VISIBILITY_SCALE)
            chars = [dict(char) for char in plumber_page.chars]
            visible, hidden = _split_visible_hidden(
                chars,
                float(plumber_page.width),
                float(plumber_page.height),
                rendered,
                VISIBILITY_SCALE,
            )
            if hidden.strip():
                snippet = _snippet(hidden)
                warnings.append(
                    AnalysisWarning(
                        code="HIDDEN_TEXT",
                        page=page_no,
                        message=(
                            f"Na stronie {page_no} wykryto niewidoczny tekst "
                            f"(„{snippet}”). Pominięto go w analizie."
                        ),
                    )
                )

            method: Literal["text", "ocr", "vision"] = "text"
            confidence: float | None = None
            text = visible
            hidden_snippet = _snippet(hidden) if hidden.strip() else None

            if len(visible.strip()) < settings.ocr_min_chars:
                if ocr_used >= settings.max_ocr_pages:
                    warnings.append(
                        AnalysisWarning(
                            code="PAGES_SKIPPED",
                            page=page_no,
                            message=(
                                f"Strona {page_no} wymaga OCR, ale przekroczono limit "
                                f"{settings.max_ocr_pages} stron OCR — pominięto."
                            ),
                        )
                    )
                    text = visible
                else:
                    ocr = ocr_page(
                        pdf,
                        index,
                        lang=settings.ocr_lang,
                        min_confidence=settings.ocr_min_confidence,
                        vision_enabled=settings.vision_fallback,
                        vision=vision_fn,
                    )
                    ocr_used += 1
                    text = ocr.text
                    confidence = ocr.confidence
                    method = "vision" if ocr.method == "vision" else "ocr"
                    warning_code = "VISION_USED" if method == "vision" else "OCR_USED"
                    warnings.append(
                        AnalysisWarning(
                            code=warning_code,
                            page=page_no,
                            message=(
                                f"Strona {page_no} nie ma warstwy tekstowej — "
                                f"odczytano ją przez {'vision' if method == 'vision' else 'OCR'}."
                            ),
                        )
                    )
                    if (
                        method == "ocr"
                        and confidence is not None
                        and confidence < settings.ocr_min_confidence
                    ):
                        warnings.append(
                            AnalysisWarning(
                                code="OCR_LOW_CONFIDENCE",
                                page=page_no,
                                message=(
                                    f"Strona {page_no}: niska pewność OCR ({confidence:.0f}%)."
                                ),
                            )
                        )

            page_results.append(
                PageResult(
                    page=page_no,
                    method=method,
                    text=text,
                    chars=len(text),
                    confidence=confidence,
                    hidden_snippet=hidden_snippet,
                )
            )

    parts = [f"{_page_marker(p.page)}\n{p.text}".rstrip() for p in page_results if p.text.strip()]
    full_text = "\n\n".join(parts)
    if not full_text.strip():
        raise ApiError(ErrorCode.NO_TEXT)

    if scan_injection(full_text):
        warnings.append(
            AnalysisWarning(
                code="INJECTION_SUSPECTED",
                page=None,
                message=(
                    "W tekście dokumentu wykryto fragmenty wyglądające na instrukcje "
                    "dla modelu AI. Zostaną one potraktowane jako dane, nie jako polecenia."
                ),
            )
        )

    page_info = [
        PageInfo(page=p.page, method=p.method, chars=p.chars, confidence=p.confidence)
        for p in page_results
    ]
    total_chars = sum(p.chars for p in page_results)
    logger.info(
        "extracted pages=%s chars=%s ocr_pages=%s warnings=%s",
        page_count,
        total_chars,
        sum(1 for p in page_results if p.method in {"ocr", "vision"}),
        len(warnings),
    )
    return ExtractionResult(
        pages=page_count,
        page_results=page_results,
        text=full_text,
        chars=total_chars,
        page_info=page_info,
        warnings=warnings,
    )
