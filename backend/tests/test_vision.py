import threading

from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.extraction import DEADLINE_MARGIN_SECONDS, Extraction, extract_pdf
from app.schema import OcrPage
from tests.fakes import FakeLlm
from tests.pdfs import image_pages_pdf


def extract(
    vision: FakeLlm | None, confidence: float = 40.0, pages: int = 1, **settings: object
) -> Extraction:
    unsure = {
        n: OcrPage(page=n, text="Aneks: 13 1OO PLN", confidence=confidence)
        for n in range(1, pages + 1)
    }
    return extract_pdf(
        image_pages_pdf(*["Aneks: 13 100 PLN"] * pages),
        "scan.pdf",
        Settings(ocr_min_confidence=60, **settings),  # type: ignore[arg-type]
        vision=vision,
        browser_ocr=unsure,
    )


def test_low_confidence_page_is_transcribed_by_vision() -> None:
    result = extract(FakeLlm(lambda _: "Aneks: 13 100 PLN"))
    assert result.pages == ["[Strona 1]\nAneks: 13 100 PLN"]
    assert [(info.method, info.confidence) for info in result.page_info] == [("vision", None)]
    assert [w.code for w in result.warnings] == ["VISION_USED"]


def test_confident_page_is_not_sent_to_vision() -> None:
    llm = FakeLlm(lambda _: "nie powinno być wywołane")
    assert extract(llm, confidence=90.0).page_info[0].method == "ocr"
    assert llm.prompts == []


def test_vision_failure_keeps_the_ocr_text() -> None:
    def fail(_: str) -> str:
        raise ApiError(ErrorCode.AI_UNAVAILABLE)

    for vision in (FakeLlm(fail), None):
        result = extract(vision)
        assert result.pages == ["[Strona 1]\nAneks: 13 1OO PLN"]
        assert [w.code for w in result.warnings] == ["OCR_USED", "OCR_LOW_CONFIDENCE"]


def test_unsure_pages_are_transcribed_in_parallel() -> None:
    all_started = threading.Barrier(3, timeout=5)

    def respond(_: str) -> str:
        all_started.wait()
        return "Aneks: 13 100 PLN"

    result = extract(FakeLlm(respond), pages=3)
    assert [info.method for info in result.page_info] == ["vision"] * 3


def test_no_vision_call_after_the_deadline() -> None:
    llm = FakeLlm(lambda _: "za późno")
    result = extract(llm, extract_timeout_seconds=DEADLINE_MARGIN_SECONDS)
    assert result.page_info[0].method == "ocr"
    assert llm.prompts == []
