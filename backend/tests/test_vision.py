import threading
from typing import Any

import pytest
from PIL import Image

from app import extraction
from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.extraction import DEADLINE_MARGIN_SECONDS, Extraction, extract_pdf
from app.llm import OpenRouter
from app.ocr import OCR_SCALE, render_page
from app.schema import OcrPage
from tests.fakes import FakeLlm, budget
from tests.pdfs import image_pages_pdf


def extract(vision: OpenRouter | None, *confidences: float, **settings: object) -> Extraction:
    """A scan with one page per OCR confidence (one page at 40 by default)."""
    confidences = confidences or (40.0,)
    browser_ocr = {
        n: OcrPage(page=n, text="Aneks: 13 1OO PLN", confidence=confidence)
        for n, confidence in enumerate(confidences, start=1)
    }
    return extract_pdf(
        image_pages_pdf(*["Aneks: 13 100 PLN"] * len(confidences)),
        "scan.pdf",
        Settings(ocr_min_confidence=60, **settings),  # type: ignore[arg-type]
        vision=vision,
        browser_ocr=browser_ocr,
    )


def test_low_confidence_page_is_transcribed_by_vision() -> None:
    result = extract(FakeLlm(lambda _: "Aneks: 13 100 PLN"))
    assert result.pages == ["=== 1 ===\nAneks: 13 100 PLN"]
    assert [(info.method, info.confidence) for info in result.page_info] == [("vision", None)]
    assert [w.code for w in result.warnings] == ["VISION_USED"]


def test_only_the_least_confident_pages_under_the_minimum_go_to_vision_in_one_round() -> None:
    all_started = threading.Barrier(2, timeout=5)

    def respond(_: str) -> str:
        all_started.wait()
        return "Aneks: 13 100 PLN"

    llm = FakeLlm(respond)
    result = extract(llm, 95.0, 20.0, 50.0, 40.0, 90.0, vision_max_pages=2)
    methods = [info.method for info in result.page_info]
    assert methods == ["ocr", "vision", "ocr", "vision", "ocr"]
    assert len(llm.prompts) == 2


def test_confident_pages_stay_with_ocr() -> None:
    llm = FakeLlm(lambda _: "Aneks: 13 100 PLN")
    result = extract(llm, 95.0, 60.0)
    assert [info.method for info in result.page_info] == ["ocr", "ocr"]
    assert llm.prompts == []
    assert [w.code for w in result.warnings] == ["OCR_USED", "OCR_USED"]


def test_vision_calls_stop_when_the_client_budget_is_used_up() -> None:
    llm = FakeLlm(lambda _: "Aneks: 13 100 PLN")
    result = extract(llm.billed_to(budget(1)), 40.0, 30.0, 50.0)
    assert sorted(info.method for info in result.page_info) == ["ocr", "ocr", "vision"]
    assert len(llm.prompts) == 1


def test_vision_failure_keeps_the_ocr_text() -> None:
    def fail(_: str) -> str:
        raise ApiError(ErrorCode.AI_UNAVAILABLE)

    for vision in (FakeLlm(fail), None):
        result = extract(vision)
        assert result.pages == ["=== 1 ===\nAneks: 13 1OO PLN"]
        assert [w.code for w in result.warnings] == ["OCR_USED", "OCR_LOW_CONFIDENCE"]


def test_no_vision_render_or_call_after_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    scales: list[float] = []

    def counted(page: Any, scale: float) -> Image.Image:
        scales.append(scale)
        return render_page(page, scale)

    monkeypatch.setattr(extraction, "render_page", counted)
    llm = FakeLlm(lambda _: "za późno")
    result = extract(llm, 40.0, 40.0, 40.0, extract_timeout_seconds=DEADLINE_MARGIN_SECONDS)
    assert [info.method for info in result.page_info] == ["ocr"] * 3
    assert llm.prompts == []
    assert OCR_SCALE not in scales


def test_transcript_past_the_text_limit_is_refused() -> None:
    with pytest.raises(ApiError) as raised:
        extract(FakeLlm(lambda _: "Aneks " * 40), max_text_chars=100)
    assert raised.value.code == ErrorCode.TEXT_TOO_LONG
