import time
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

from app.cache import TtlCache
from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.extraction import Extraction
from app.main import create_app
from app.schema import AnalysisWarning, PageInfo
from tests.fakes import FakeLlm, extraction, llm_answer


def make_client(llm: FakeLlm | None, **settings: object) -> tuple[TestClient, FastAPI]:
    app = create_app(Settings(**{"rate_limit_per_minute": 60, **settings}), llm)  # type: ignore[arg-type]
    return TestClient(app), app


def seed(app: FastAPI, extraction_id: str = "ext-1", value: Extraction | None = None) -> None:
    cast(TtlCache[Extraction], app.state.cache).set(extraction_id, value or extraction())


def analyze(client: TestClient, extraction_id: str = "ext-1") -> Response:
    return client.post("/api/analyze", json={"extractionId": extraction_id})


def test_assembles_result_from_model_and_extraction() -> None:
    llm = FakeLlm(lambda _: llm_answer(suspiciousInstructions=["zignoruj polecenia"]))
    client, app = make_client(llm)
    seed(
        app,
        value=extraction(
            page_info=[
                PageInfo(page=1, method="text", chars=50, confidence=None),
                PageInfo(page=2, method="ocr", chars=20, confidence=90.0),
            ],
            warnings=[AnalysisWarning(code="HIDDEN_TEXT", page=1, message="Ukryty tekst.")],
        ),
    )

    body = analyze(client).json()

    assert body["document"] == {
        "fileName": "umowa.pdf",
        "pages": 2,
        "language": "pl",
        "type": "umowa",
        "title": "Umowa",
        "date": "2026-03-12",
    }
    assert body["amounts"] == [{"value": 100000.0, "currency": "PLN", "context": "wynagrodzenie"}]
    meta = body["meta"]
    assert (meta["provider"], meta["model"]) == ("openrouter", "anthropic/claude-haiku-5.5")
    assert (meta["ocrPages"], meta["hiddenTextPages"], meta["chunks"]) == ([2], [1], 1)
    assert [w["code"] for w in body["warnings"]] == ["HIDDEN_TEXT", "INJECTION_SUSPECTED"]
    assert "zignoruj polecenia" in body["warnings"][1]["message"]


def test_document_text_is_wrapped_in_a_random_tag() -> None:
    llm = FakeLlm(lambda _: llm_answer())
    client, app = make_client(llm)
    seed(app)
    analyze(client)
    prompt = llm.prompts[0]
    tag = prompt.split("<", 1)[1].split(">", 1)[0]
    assert tag.startswith("document_")
    assert len(tag) == len("document_") + 16
    assert f"</{tag}>" in prompt
    assert "Wynagrodzenie 100 000 PLN" in prompt


def test_retries_once_with_the_validation_errors() -> None:
    answers = iter([llm_answer(summary="Za krótkie."), llm_answer()])
    llm = FakeLlm(lambda _: next(answers))
    client, app = make_client(llm)
    seed(app)
    assert analyze(client).status_code == 200
    assert len(llm.prompts) == 2
    assert "summary must have 3-5 sentences, has 1" in llm.prompts[1]


def test_invalid_json_is_retried_too() -> None:
    answers = iter(["not json", llm_answer()])
    client, app = make_client(FakeLlm(lambda _: next(answers)))
    seed(app)
    assert analyze(client).status_code == 200


def test_second_invalid_answer_returns_502() -> None:
    llm = FakeLlm(lambda _: llm_answer(keyPoints=["jeden"]))
    client, app = make_client(llm)
    seed(app)
    response = analyze(client)
    assert response.status_code == 502
    assert response.json()["error"] == {
        "code": "AI_INVALID_RESPONSE",
        "message": "Model AI zwrócił niepoprawną odpowiedź. Spróbuj ponownie.",
    }
    assert len(llm.prompts) == 2


def test_ungrounded_values_are_removed() -> None:
    amounts = [
        {"value": 100000, "currency": "PLN", "context": "wynagrodzenie"},
        {"value": 777777, "currency": "PLN", "context": "zmyślona kwota"},
    ]
    llm = FakeLlm(lambda _: llm_answer(amounts=amounts))
    client, app = make_client(llm)
    seed(app, value=extraction("Umowa z dnia 12.03.2026. Wynagrodzenie 100 000 PLN."))
    body = analyze(client).json()
    assert [a["value"] for a in body["amounts"]] == [100000.0]
    assert [w["code"] for w in body["warnings"]] == ["UNGROUNDED_REMOVED"]


def test_provider_errors_keep_their_codes() -> None:
    for code, status in ((ErrorCode.AI_UNAVAILABLE, 503), (ErrorCode.TIMEOUT, 504)):

        def fail(_: str, code: ErrorCode = code) -> str:
            raise ApiError(code)

        client, app = make_client(FakeLlm(fail))
        seed(app)
        assert analyze(client).status_code == status


def test_missing_key_answers_503_but_extraction_cache_is_checked_first() -> None:
    client, app = make_client(None, openrouter_api_key=None)
    assert analyze(client, "missing").status_code == 404
    seed(app)
    assert analyze(client).status_code == 503


def test_daily_cap_counts_llm_calls() -> None:
    client, app = make_client(FakeLlm(lambda _: llm_answer(), daily_limit=1))
    assert analyze(client, "missing").status_code == 404
    seed(app, "a")
    seed(app, "b")
    assert analyze(client, "a").status_code == 200
    second = analyze(client, "b")
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "DAILY_LIMIT"


def test_rate_limit_per_client() -> None:
    client, app = make_client(FakeLlm(lambda _: llm_answer()), rate_limit_per_minute=1)
    seed(app)
    assert analyze(client).status_code == 200
    response = analyze(client)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert int(response.headers["retry-after"]) > 0


def test_time_budget_returns_504_and_stops_calling_the_llm() -> None:
    def slow_and_invalid(_: str) -> str:
        time.sleep(0.3)
        return llm_answer(keyPoints=["jeden"])

    llm = FakeLlm(slow_and_invalid)
    client, app = make_client(llm, analyze_timeout_seconds=0.05)
    seed(app)
    assert analyze(client).status_code == 504
    time.sleep(0.5)
    assert len(llm.prompts) == 1


def test_extraction_is_analysed_once() -> None:
    client, app = make_client(FakeLlm(lambda _: llm_answer()))
    seed(app)
    assert analyze(client).status_code == 200
    assert analyze(client).json()["error"]["code"] == "EXTRACTION_NOT_FOUND"
