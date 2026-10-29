import json

import pytest

from app.analysis import analyze_extraction
from app.chunking import merge_analyses, split_into_chunks
from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.extraction import Extraction
from app.schema import LlmAnalysis, PageInfo
from tests.fakes import FakeLlm, llm_answer


def analysis(**overrides: object) -> LlmAnalysis:
    return LlmAnalysis.model_validate(json.loads(llm_answer(**overrides)))


def long_extraction(*bodies: str) -> Extraction:
    return Extraction(
        file_name="long.pdf",
        pages=[f"[Strona {n}]\n{body}" for n, body in enumerate(bodies, start=1)],
        page_info=[
            PageInfo(page=n, method="text", chars=len(body), confidence=None)
            for n, body in enumerate(bodies, start=1)
        ],
        warnings=[],
    )


def test_split_packs_whole_pages() -> None:
    pages = ["a" * 40, "b" * 40, "c" * 40, "d" * 200]
    assert split_into_chunks(pages, 90) == ["a" * 40 + "\n\n" + "b" * 40, "c" * 40, "d" * 200]
    assert split_into_chunks(pages[:2], 1000) == ["a" * 40 + "\n\n" + "b" * 40]


def test_merge_unions_lists_and_picks_document_fields() -> None:
    first = analysis(
        document={"language": "pl", "type": "umowa", "title": None, "date": None},
        entities={"organizations": ["Acme"], "people": ["Anna"]},
        amounts=[{"value": 100, "currency": "PLN", "context": "a"}],
        dates=[{"date": "2026-03-12", "context": "podpis"}],
        keywords=["CRM"],
    )
    second = analysis(
        document={"language": "pl", "type": "raport", "title": "Tytuł", "date": "2026-04-01"},
        entities={"organizations": ["ACME", "Beta"], "people": ["anna", "Paweł"]},
        amounts=[
            {"value": 100, "currency": "PLN", "context": "duplikat"},
            {"value": 100, "currency": "EUR", "context": "b"},
        ],
        dates=[{"date": "2026-03-12", "context": "duplikat"}],
        keywords=["crm", "SLA"],
    )
    third = analysis(document={"language": "pl", "type": "umowa", "title": "Inny", "date": None})

    merged = merge_analyses([first, second, third])

    assert merged.document.model_dump() == {
        "language": "pl",
        "type": "umowa",
        "title": "Tytuł",
        "date": "2026-04-01",
    }
    assert merged.entities.organizations == ["Acme", "Beta"]
    assert merged.entities.people == ["Anna", "Paweł", "Anna Kowalczyk"]
    assert [(a.value, a.currency, a.context) for a in merged.amounts] == [
        (100, "PLN", "a"),
        (100, "EUR", "b"),
        (100000, "PLN", "wynagrodzenie"),
    ]
    assert [d.context for d in merged.dates] == ["podpis"]
    assert merged.keywords == ["CRM", "SLA"]


def test_long_document_is_analysed_per_chunk_then_summarised() -> None:
    def respond(prompt: str) -> str:
        if "too long for one request" in prompt:
            assert "Part 1:\nStreszczenie strony 1." in prompt
            return llm_answer(keyPoints=["Całość 1", "Całość 2", "Całość 3"])
        page = "1" if "[Strona 1]" in prompt else "2"
        return llm_answer(
            summary=f"Streszczenie strony {page}. Drugie zdanie. Trzecie zdanie.",
            entities={"organizations": [f"Firma {page}"], "people": []},
        )

    llm = FakeLlm(respond)
    text = "Umowa z dnia 12.03.2026 na 100 000 PLN. " * 5
    result = analyze_extraction(
        llm, long_extraction(text, text), Settings(chunk_chars=len(text) + 20)
    )

    assert len(llm.prompts) == 3
    assert result.meta.chunks == 2
    assert result.key_points == ["Całość 1", "Całość 2", "Całość 3"]
    assert result.entities.organizations == ["Firma 1", "Firma 2"]
    assert [w.code for w in result.warnings] == ["CHUNKED"]
    assert "2 częściach" in result.warnings[0].message


def test_one_failing_chunk_fails_the_request() -> None:
    def respond(prompt: str) -> str:
        if "[Strona 2]" in prompt:
            raise ApiError(ErrorCode.AI_UNAVAILABLE)
        return llm_answer()

    text = "x" * 100
    with pytest.raises(ApiError) as raised:
        analyze_extraction(FakeLlm(respond), long_extraction(text, text), Settings(chunk_chars=150))
    assert raised.value.code == ErrorCode.AI_UNAVAILABLE
