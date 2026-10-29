from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.cache import TtlCache
from app.config import Settings
from app.main import CachedExtraction, create_app
from tests.pdfs import hidden_text_pdf, text_pdf

ORIGIN = "https://planetoida90210.github.io"


def make_client(
    *,
    rate_limit_per_minute: int = 6,
    llm_provider: str = "gemini",
) -> tuple[TestClient, FastAPI]:
    app = create_app(
        Settings(
            allowed_origins=f"{ORIGIN},http://localhost:5173",
            max_file_mb=1,
            rate_limit_per_minute=rate_limit_per_minute,
            vision_fallback=False,
            llm_provider=cast(Any, llm_provider),
        )
    )
    return TestClient(app), app


def test_extract_returns_page_info_and_caches() -> None:
    client, app = make_client()
    pdf = text_pdf("Strona testowa umowy z wystarczajaca iloscia tekstu widocznego.")
    response = client.post(
        "/api/extract",
        files={"file": ("umowa.pdf", pdf, "application/pdf")},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    body = response.json()
    assert "extractionId" in body
    assert body["fileName"] == "umowa.pdf"
    assert body["pages"] == 1
    assert body["chars"] > 0
    assert body["pageInfo"][0]["method"] == "text"
    assert body["pageInfo"][0]["confidence"] is None
    assert "expiresAt" in body
    cache = cast(TtlCache[CachedExtraction], app.state.cache)
    cached = cache.get(body["extractionId"])
    assert cached is not None
    assert "Strona testowa" in cached.text
    assert "[Strona 1]" in cached.text


def test_extract_reports_hidden_text() -> None:
    client, _ = make_client()
    response = client.post(
        "/api/extract",
        files={"file": ("hid.pdf", hidden_text_pdf(), "application/pdf")},
    )
    assert response.status_code == 200
    warnings = response.json()["warnings"]
    assert any(w["code"] == "HIDDEN_TEXT" for w in warnings)


def test_extract_rate_limited() -> None:
    client, _ = make_client(rate_limit_per_minute=1)
    pdf = text_pdf("Strona testowa umowy z wystarczajaca iloscia tekstu widocznego.")
    files = {"file": ("a.pdf", pdf, "application/pdf")}
    assert client.post("/api/extract", files=files).status_code == 200
    second = client.post("/api/extract", files=files)
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMITED"
    assert "retry-after" in second.headers


def test_extract_rejects_non_pdf() -> None:
    client, _ = make_client()
    response = client.post(
        "/api/extract",
        files={"file": ("x.txt", b"not a pdf", "text/plain")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_TYPE"


def test_health_includes_provider() -> None:
    _, app = make_client(llm_provider="anthropic")
    response = TestClient(app).get("/api/health")
    assert response.json() == {"status": "ok", "provider": "anthropic"}
