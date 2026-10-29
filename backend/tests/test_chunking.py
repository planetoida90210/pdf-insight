"""Chunk split, merge, reduce, and failure propagation (F-08)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.analysis import analyze_extraction
from app.cache import TtlCache
from app.chunking import merge_chunk_analyses, run_bounded, split_into_chunks
from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.llm import MockTransport
from app.main import CachedExtraction, create_app
from app.schema import (
    Amount,
    DateEntry,
    Entities,
    LlmAnalysis,
    LlmDocument,
    PageInfo,
)

ORIGIN = "https://planetoida90210.github.io"


def _page(n: int, body: str) -> str:
    return f"[Strona {n}]\n{body}"


def _analysis(
    *,
    summary: str = "Zdanie jedno. Zdanie dwa. Zdanie trzy.",
    key_points: list[str] | None = None,
    orgs: list[str] | None = None,
    people: list[str] | None = None,
    amounts: list[Amount] | None = None,
    dates: list[DateEntry] | None = None,
    keywords: list[str] | None = None,
    language: str = "pl",
    doc_type: str = "umowa",
    title: str | None = "Tytuł",
    date: str | None = "2026-03-12",
) -> LlmAnalysis:
    from typing import Literal, cast

    return LlmAnalysis(
        document=LlmDocument(
            language=language,
            type=cast(Literal["faktura", "umowa", "oferta", "raport", "inne"], doc_type),
            title=title,
            date=date,
        ),
        summary=summary,
        key_points=key_points or ["A", "B", "C"],
        entities=Entities(organizations=orgs or [], people=people or []),
        amounts=amounts or [],
        dates=dates or [],
        keywords=keywords or [],
        suspicious_instructions=[],
    )


def test_split_returns_single_chunk_when_under_limit() -> None:
    text = _page(1, "krótki")
    assert split_into_chunks(text, 1000) == [text]


def test_split_on_page_boundaries() -> None:
    pages = [_page(i, "x" * 40) for i in range(1, 5)]
    text = "\n\n".join(pages)
    # Each page block is ~50 chars; limit packs two pages per chunk.
    chunks = split_into_chunks(text, 110)
    assert len(chunks) >= 2
    assert all("[Strona" in chunk for chunk in chunks)
    # Page markers stay intact — never mid-page split when pages fit.
    joined_pages = sum(chunk.count("[Strona") for chunk in chunks)
    assert joined_pages == 4


def test_oversized_single_page_becomes_own_chunk() -> None:
    huge = _page(1, "y" * 500)
    chunks = split_into_chunks(huge, 100)
    assert len(chunks) == 1
    assert chunks[0] == huge


def test_merge_dedupes_case_insensitive() -> None:
    a = _analysis(
        orgs=["Acme", "Beta"],
        people=["Anna"],
        keywords=["CRM", "Umowa"],
        amounts=[Amount(value=100.0, currency="PLN", context="a")],
        dates=[DateEntry(date="2026-03-12", context="podpis")],
        title="Pierwszy",
        date="2026-03-12",
    )
    b = _analysis(
        orgs=["acme", "Gamma"],
        people=["ANNA", "Paweł"],
        keywords=["crm", "Aneks"],
        amounts=[
            Amount(value=100.0, currency="PLN", context="dup"),
            Amount(value=200.0, currency="EUR", context="b"),
        ],
        dates=[
            DateEntry(date="2026-03-12", context="again"),
            DateEntry(date="2026-04-01", context="start"),
        ],
        title=None,
        date=None,
        language="pl",
        doc_type="raport",
    )
    merged = merge_chunk_analyses([a, b])
    assert merged.entities.organizations == ["Acme", "Beta", "Gamma"]
    assert merged.entities.people == ["Anna", "Paweł"]
    assert merged.keywords == ["CRM", "Umowa", "Aneks"]
    assert len(merged.amounts) == 2
    assert [d.date for d in merged.dates] == ["2026-03-12", "2026-04-01"]
    assert merged.document.title == "Pierwszy"
    assert merged.document.date == "2026-03-12"
    assert merged.document.type == "umowa"  # majority / first wins via Counter


def test_run_bounded_propagates_chunk_failure() -> None:
    def worker(item: int) -> LlmAnalysis:
        if item == 2:
            raise ApiError(ErrorCode.AI_UNAVAILABLE)
        return _analysis()

    with pytest.raises(ApiError) as raised:
        run_bounded([1, 2, 3], worker, concurrency=3)
    assert raised.value.code == ErrorCode.AI_UNAVAILABLE


def test_analyze_chunked_path_merges_and_reduces() -> None:
    calls: list[str] = []

    def complete(_system: str, user: str) -> dict[str, Any]:
        calls.append(user)
        if "Combine the following chunk" in user:
            return {
                "document": {
                    "language": "pl",
                    "type": "umowa",
                    "title": "Scalony",
                    "date": "2026-03-12",
                },
                "summary": (
                    "Dokument opisuje umowę wdrożeniową. "
                    "Strony ustaliły wynagrodzenie. "
                    "Termin realizacji przypada na wiosnę."
                ),
                "keyPoints": ["Scalony punkt 1", "Scalony punkt 2", "Scalony punkt 3"],
                "entities": {"organizations": [], "people": []},
                "amounts": [],
                "dates": [],
                "keywords": [],
                "suspiciousInstructions": [],
            }
        # Per-chunk responses: detect which page marker is present.
        org = "NordA" if "[Strona 1]" in user else "NordB"
        return {
            "document": {
                "language": "pl",
                "type": "umowa",
                "title": "Umowa",
                "date": "2026-03-12",
            },
            "summary": (
                "Fragment umowy o wdrożeniu. Opisuje strony i zakres. Wskazuje termin rozpoczęcia."
            ),
            "keyPoints": [f"KP {org} 1", f"KP {org} 2", f"KP {org} 3"],
            "entities": {"organizations": [org], "people": ["Anna"]},
            "amounts": [{"value": 1000.0, "currency": "PLN", "context": "opłata"}],
            "dates": [{"date": "2026-03-12", "context": "podpis"}],
            "keywords": ["umowa"],
            "suspiciousInstructions": [],
        }

    # Force two chunks: two large pages under a tiny budget.
    page1 = _page(1, ("Tekst strony pierwszej. " * 20) + "1000 PLN 12.03.2026")
    page2 = _page(2, ("Tekst strony drugiej. " * 20) + "1000 PLN")
    text = f"{page1}\n\n{page2}"
    assert len(split_into_chunks(text, 200)) >= 2

    result = analyze_extraction(
        transport=MockTransport(complete),
        provider="gemini",
        model="gemini-3.8-flash",
        file_name="long.pdf",
        pages=2,
        text=text,
        page_info=[
            PageInfo(page=1, method="text", chars=10, confidence=None),
            PageInfo(page=2, method="text", chars=10, confidence=None),
        ],
        extract_warnings=[],
        chunk_chars=200,
        chunk_concurrency=2,
    )
    assert result.meta.chunks >= 2
    assert any(w.code == "CHUNKED" for w in result.warnings)
    assert "Scalony punkt 1" in result.key_points
    orgs = {name.casefold() for name in result.entities.organizations}
    assert "norda" in orgs
    assert "nordb" in orgs
    assert any("Combine the following chunk" in call for call in calls)
    assert len(calls) >= 3  # 2 chunks + 1 reduce


def test_analyze_chunk_failure_fails_request() -> None:
    def complete(_system: str, user: str) -> dict[str, Any]:
        if "[Strona 2]" in user:
            raise ApiError(ErrorCode.AI_UNAVAILABLE)
        return {
            "document": {
                "language": "pl",
                "type": "umowa",
                "title": "Umowa",
                "date": "2026-03-12",
            },
            "summary": "A. B. C.",
            "keyPoints": ["1", "2", "3"],
            "entities": {"organizations": [], "people": []},
            "amounts": [],
            "dates": [],
            "keywords": [],
            "suspiciousInstructions": [],
        }

    page1 = _page(1, "alpha " * 80)
    page2 = _page(2, "beta " * 80)
    text = f"{page1}\n\n{page2}"
    with pytest.raises(ApiError) as raised:
        analyze_extraction(
            transport=MockTransport(complete),
            provider="gemini",
            model="m",
            file_name="x.pdf",
            pages=2,
            text=text,
            page_info=[],
            extract_warnings=[],
            chunk_chars=200,
            chunk_concurrency=2,
        )
    assert raised.value.code == ErrorCode.AI_UNAVAILABLE


def test_analyze_api_chunked_meta() -> None:
    page1 = _page(1, ("słowo " * 60) + "1000 PLN 12.03.2026")
    page2 = _page(2, "inne " * 60)
    text = f"{page1}\n\n{page2}"

    def complete(_system: str, user: str) -> dict[str, Any]:
        summary = (
            "Umowa dotyczy wdrożenia systemu. Obowiązuje od marca. Wynagrodzenie jest ustalone."
        )
        if "Combine the following chunk" in user:
            return {
                "document": {
                    "language": "pl",
                    "type": "umowa",
                    "title": "T",
                    "date": "2026-03-12",
                },
                "summary": summary,
                "keyPoints": ["P1", "P2", "P3"],
                "entities": {"organizations": [], "people": []},
                "amounts": [],
                "dates": [],
                "keywords": [],
                "suspiciousInstructions": [],
            }
        return {
            "document": {
                "language": "pl",
                "type": "umowa",
                "title": "T",
                "date": "2026-03-12",
            },
            "summary": summary,
            "keyPoints": ["P1", "P2", "P3"],
            "entities": {"organizations": ["Acme"], "people": []},
            "amounts": [{"value": 1000.0, "currency": "PLN", "context": "opłata"}],
            "dates": [{"date": "2026-03-12", "context": "d"}],
            "keywords": ["k"],
            "suspiciousInstructions": [],
        }

    app = create_app(
        Settings(
            allowed_origins=ORIGIN,
            chunk_chars=200,
            chunk_concurrency=2,
            rate_limit_per_minute=60,
            gemini_api_key=None,
            vision_fallback=False,
        ),
        llm_transport=MockTransport(complete),
    )
    cache = cast(TtlCache[CachedExtraction], app.state.cache)
    cache.set(
        "c1",
        CachedExtraction(
            file_name="long.pdf",
            pages=2,
            text=text,
            chars=len(text),
            page_info=[
                PageInfo(page=1, method="text", chars=1, confidence=None),
                PageInfo(page=2, method="text", chars=1, confidence=None),
            ],
            warnings=[],
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        ),
    )
    client = TestClient(app)
    response = client.post("/api/analyze", json={"extractionId": "c1"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"]["chunks"] >= 2
    assert any(w["code"] == "CHUNKED" for w in body["warnings"])
