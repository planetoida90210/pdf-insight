import json

from app.validation import parse_analysis
from tests.fakes import llm_answer


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


def test_counts_summary_sentences_and_key_points() -> None:
    sentences = [f"Zdanie {n} o firmie Acme sp. z o.o. (Wykonawca)." for n in range(5)]
    assert parse_analysis(llm_answer(summarySentences=sentences))[1] == []
    _, errors = parse_analysis(llm_answer(summarySentences=["Jedno zdanie."], keyPoints=["a", "b"]))
    assert errors == [
        "summarySentences: List should have at least 3 items after validation, not 1",
        "keyPoints: List should have at least 3 items after validation, not 2",
    ]


def test_rejects_non_json_and_non_object_answers() -> None:
    assert parse_analysis("Oto analiza:")[1][0].startswith("response is not valid JSON")
    assert parse_analysis(json.dumps(["lista"]))[1] == ["response must be a JSON object"]
    assert parse_analysis('{"amounts": [{"value": ' + "9" * 5000 + "}]}")[0] is None
