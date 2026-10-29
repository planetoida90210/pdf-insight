"""Wall-clock budgets for extract and analyze map to TIMEOUT 504."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.cache import TtlCache
from app.config import Settings
from app.llm import MockTransport
from app.main import CachedExtraction, create_app
from app.schema import PageInfo

ORIGIN = "https://planetoida90210.github.io"


def test_extract_timeout_returns_504() -> None:
    from tests.pdfs import text_pdf

    pdf = text_pdf("Hello")

    def slow_extract(*_args: object, **_kwargs: object) -> object:
        time.sleep(0.3)
        raise AssertionError("should have been cancelled by wait_for")

    app = create_app(
        Settings(
            allowed_origins=ORIGIN,
            extract_timeout_seconds=0.05,
            rate_limit_per_minute=60,
            vision_fallback=False,
        )
    )
    client = TestClient(app)
    with patch("app.main.extract_pdf", side_effect=slow_extract):
        response = client.post(
            "/api/extract",
            files={"file": ("a.pdf", pdf, "application/pdf")},
        )
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "TIMEOUT"


def test_analyze_timeout_returns_504() -> None:
    def slow(_system: str, _user: str) -> dict[str, Any]:
        time.sleep(0.3)
        return {}

    app = create_app(
        Settings(
            allowed_origins=ORIGIN,
            analyze_timeout_seconds=0.05,
            rate_limit_per_minute=60,
            vision_fallback=False,
        ),
        llm_transport=MockTransport(slow),
    )
    cache = cast(TtlCache[CachedExtraction], app.state.cache)
    cache.set(
        "t1",
        CachedExtraction(
            file_name="a.pdf",
            pages=1,
            text="tekst",
            chars=5,
            page_info=[PageInfo(page=1, method="text", chars=5, confidence=None)],
            warnings=[],
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        ),
    )
    client = TestClient(app)
    response = client.post("/api/analyze", json={"extractionId": "t1"})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "TIMEOUT"
