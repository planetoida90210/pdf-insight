"""A page's text layer, split by what the rendered page shows."""

from collections.abc import Callable
from contextlib import closing
from typing import cast

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from PIL import Image

from app.ocr import UNMAPPED, render_scale

# ~108 DPI: enough to tell a glyph from a flat background, cheap on a shared CPU.
VISIBILITY_SCALE = 1.5
# A glyph whose box has a smaller luminance spread is drawn in the background colour.
MIN_LUMINANCE_SPREAD = 15
# Glyphs smaller than this, in points, are not meant to be read.
MIN_GLYPH_SIZE = 1
# A glyph box is checked over at least this many pixels in each direction.
MIN_GLYPH_PIXELS = 4
HYPHEN_AT_LINE_END = 0x2


def visible_and_hidden_text(page: pdfium.PdfPage) -> tuple[str, str]:
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
    left, right = _pixel_span(x0, x1, gray.width)
    top, bottom = _pixel_span(y0, y1, gray.height)
    if left >= right or top >= bottom:
        return False
    crop = gray.crop((left, top, right, bottom))
    low, high = cast(tuple[int, int], crop.getextrema())  # one band in mode "L"
    return bool(high - low >= MIN_LUMINANCE_SPREAD)


def _pixel_span(start: float, end: float, limit: int) -> tuple[int, int]:
    """The pixels from `start` to `end`, widened around the centre to MIN_GLYPH_PIXELS: the box of
    a thin glyph (a minus sign, a period) can lie inside its own stroke, with no contrast in it."""
    low, high = sorted((start, end))
    grow = max(MIN_GLYPH_PIXELS - (high - low), 0) / 2
    return max(int(low - grow), 0), min(int(high + grow), limit)
