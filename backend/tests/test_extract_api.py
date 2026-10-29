from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.cache import TtlCache
from app.config import Settings
from app.extraction import Extraction
from app.main import create_app
from tests.pdfs import hidden_text_pdf, text_pdf

PAGE = "Strona testowa umowy z wystarczajaca iloscia widocznego tekstu."


def make_client(**settings: object) -> tuple[TestClient, FastAPI]:
    app = create_app(Settings(vision_fallback=False, max_file_mb=1, **settings))  # type: ignore[arg-type]
    return TestClient(app), app


def upload(client: TestClient, data: bytes, content_type: str = "application/pdf") -> object:
    return client.post("/api/extract", files={"file": ("umowa.pdf", data, content_type)})


def test_returns_page_info_and_caches_the_text() -> None:
    client, app = make_client()
    response = client.post("/api/extract", files={"file": ("umowa.pdf", text_pdf(PAGE))})
    body = response.json()
    assert response.status_code == 200
    assert (body["fileName"], body["pages"], body["chars"]) == ("umowa.pdf", 1, len(PAGE))
    assert body["pageInfo"] == [
        {"page": 1, "method": "text", "chars": len(PAGE), "confidence": None}
    ]
    assert body["warnings"] == []
    cached = cast(TtlCache[Extraction], app.state.cache).get(body["extractionId"])
    assert cached is not None
    assert cached.pages == [f"[Strona 1]\n{PAGE}"]


def test_type_is_decided_by_the_pdf_signature() -> None:
    client, _ = make_client()
    pdf_as_octet_stream = client.post(
        "/api/extract", files={"file": ("umowa.pdf", text_pdf(PAGE), "application/octet-stream")}
    )
    assert pdf_as_octet_stream.status_code == 200
    not_a_pdf = client.post(
        "/api/extract", files={"file": ("x.pdf", b"PK\x03\x04", "application/pdf")}
    )
    assert not_a_pdf.status_code == 415
    assert not_a_pdf.json()["error"]["code"] == "UNSUPPORTED_TYPE"


def test_reports_hidden_text() -> None:
    client, _ = make_client()
    response = client.post("/api/extract", files={"file": ("h.pdf", hidden_text_pdf())})
    assert [w["code"] for w in response.json()["warnings"]] == ["HIDDEN_TEXT"]


def test_long_file_name_is_cut_to_the_schema_limit() -> None:
    client, _ = make_client()
    response = client.post("/api/extract", files={"file": ("a" * 300 + ".pdf", text_pdf(PAGE))})
    assert response.json()["fileName"] == "a" * 255


def test_rate_limit_answers_before_the_upload_is_parsed() -> None:
    client, _ = make_client(rate_limit_per_minute=1)
    assert client.post("/api/extract", files={"file": ("a.pdf", text_pdf(PAGE))}).status_code == 200
    second = client.post("/api/extract", content=b"not a multipart body")
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMITED"
    assert int(second.headers["retry-after"]) > 0


def test_time_budget_returns_504() -> None:
    client, _ = make_client(extract_timeout_seconds=0)
    response = client.post("/api/extract", files={"file": ("a.pdf", text_pdf(PAGE))})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "TIMEOUT"
