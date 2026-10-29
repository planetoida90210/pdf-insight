import json

import pytest

from app.validation import count_sentences, parse_analysis
from tests.fakes import llm_answer


@pytest.mark.parametrize(
    ("text", "sentences"),
    [
        ("Pierwsze zdanie. Drugie zdanie! Trzecie?", 3),
        (
            "Umowa nr 14/2026 obowiązuje od 1 kwietnia 2026 r. do 31 marca 2028 r. "
            "Strony to Nordwave Logistics sp. z o.o. oraz Kwadrat Software S.A. "
            "Wynagrodzenie wynosi ok. 184,5 tys. zł, m.in. za wdrożenie.",
            3,
        ),
        ("Umowę podpisała A. Kowalczyk w dniu 12.03.2026 r. Obowiązuje dwa lata.", 2),
        ("Termin upływa 31 marca 2028 r.", 1),
        ("", 0),
    ],
)
def test_count_sentences_skips_polish_abbreviations(text: str, sentences: int) -> None:
    assert count_sentences(text) == sentences


def test_normalizes_before_validation() -> None:
    analysis, errors = parse_analysis(
        llm_answer(
            document={"language": "PL", "type": "umowa", "title": "  ", "date": ""},
            entities={"organizations": ["Acme", " acme ", "Beta"], "people": []},
            amounts=[{"value": 10, "currency": "zł", "context": "opłata"}],
            keywords=["CRM", "crm"],
        )
    )
    assert errors == []
    assert analysis is not None
    assert (analysis.document.language, analysis.document.title, analysis.document.date) == (
        "pl",
        None,
        None,
    )
    assert analysis.entities.organizations == ["Acme", "Beta"]
    assert analysis.amounts[0].currency == "PLN"
    assert analysis.keywords == ["CRM"]


def test_errors_name_the_field_for_the_retry_prompt() -> None:
    _, errors = parse_analysis(
        llm_answer(amounts=[{"value": 1, "currency": "zloty", "context": "x"}])
    )
    assert errors == ["amounts.0.currency: String should match pattern '^[A-Z]{3}$'"]


def test_rule_errors_for_summary_and_key_points() -> None:
    _, errors = parse_analysis(llm_answer(summary="Jedno zdanie.", keyPoints=["a", "b"]))
    assert errors == [
        "summary must have 3-5 sentences, has 1",
        "keyPoints must have 3-7 items, has 2",
    ]


def test_rejects_non_json_and_non_object_answers() -> None:
    assert parse_analysis("Oto analiza:")[1][0].startswith("response is not valid JSON")
    assert parse_analysis(json.dumps(["lista"]))[1] == ["response must be a JSON object"]
