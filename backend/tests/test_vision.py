from typing import Any, cast

import pytest
from PIL import Image

from app import ocr
from app.errors import ApiError, ErrorCode
from tests.fakes import FakeLlm


@pytest.fixture(autouse=True)
def unsure_tesseract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr, "render_page", lambda *_: Image.new("RGB", (10, 10), "white"))
    monkeypatch.setattr(ocr, "tesseract", lambda *_: ("13 1OO", 40.0))


def read(vision: FakeLlm | None) -> ocr.OcrResult:
    return ocr.ocr_page(cast(Any, None), lang="pol", min_confidence=60, vision=vision)


def test_low_confidence_page_is_transcribed_by_vision() -> None:
    assert read(FakeLlm(lambda _: "Aneks: 13 100 PLN")) == ocr.OcrResult(
        "Aneks: 13 100 PLN", None, "vision"
    )


def test_vision_failure_keeps_tesseract_text() -> None:
    def fail(_: str) -> str:
        raise ApiError(ErrorCode.AI_UNAVAILABLE)

    assert read(FakeLlm(fail)) == ocr.OcrResult("13 1OO", 40.0, "ocr")
    assert read(None) == ocr.OcrResult("13 1OO", 40.0, "ocr")
