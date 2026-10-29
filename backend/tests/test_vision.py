from typing import Any, cast

import pytest
from PIL import Image

from app.llm import MockTransport, make_vision_fallback
from app.ocr import OcrResult, ocr_page


def test_vision_fallback_returns_vision_method() -> None:
    transport = MockTransport(
        complete_fn=lambda _s, _u: {},
        transcribe_fn=lambda _image: "Aneks 13 100 PLN 135 użytkowników",
    )
    vision = make_vision_fallback(transport)
    image = Image.new("RGB", (40, 20), "white")
    result = vision(image)
    assert result is not None
    assert result.method == "vision"
    assert "13 100" in result.text


def test_ocr_page_uses_vision_when_confidence_low(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import ocr as ocr_mod

    def fake_ocr_image(_image: Image.Image, _lang: str) -> OcrResult:
        return OcrResult(text="x", confidence=10.0, method="ocr")

    def fake_render(_pdf: Any, _index: int, _scale: float) -> Image.Image:
        return Image.new("RGB", (10, 10), "white")

    monkeypatch.setattr(ocr_mod, "ocr_image", fake_ocr_image)
    monkeypatch.setattr(ocr_mod, "render_page", fake_render)

    def vision(_image: Image.Image) -> OcrResult:
        return OcrResult(text="vision text", confidence=100.0, method="vision")

    result = ocr_page(
        cast(Any, object()),
        0,
        lang="eng",
        min_confidence=60,
        vision_enabled=True,
        vision=vision,
    )
    assert result.method == "vision"
    assert result.text == "vision text"
