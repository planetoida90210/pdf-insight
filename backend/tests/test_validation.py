import json

import pytest

from app.validation import parse_analysis
from tests.fakes import llm_answer

DOCUMENT = "Umowa wdrożenia CRM z dnia 12.03.2026."


def test_normalizes_before_validation() -> None:
    analysis, errors = parse_analysis(
        llm_answer(
            document={"language": "PL", "type": "umowa", "title": "  ", "date": ""},
            entities={"organizations": ["Acme", " acme ", "Beta"], "people": []},
            amounts=[{"value": 10, "currency": "zł", "context": "opłata"}],
            keywords=["CRM", "crm"],
        ),
        DOCUMENT,
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
        llm_answer(amounts=[{"value": 1, "currency": "zloty", "context": "x"}]), DOCUMENT
    )
    assert errors == ["amounts.0.currency: String should match pattern '^[A-Z]{3}$'"]


def test_counts_summary_sentences_and_key_points() -> None:
    sentences = [f"Zdanie {n} o firmie Acme sp. z o.o. (Wykonawca)." for n in range(5)]
    assert parse_analysis(llm_answer(summarySentences=sentences), DOCUMENT)[1] == []
    _, errors = parse_analysis(
        llm_answer(summarySentences=["Jedno zdanie."], keyPoints=["a", "b"]), DOCUMENT
    )
    assert errors == [
        "summarySentences: List should have at least 3 items after validation, not 1",
        "keyPoints: List should have at least 3 items after validation, not 2",
    ]


def test_rejects_non_json_and_non_object_answers() -> None:
    assert parse_analysis("Oto analiza:", DOCUMENT)[1][0].startswith("response is not valid JSON")
    assert parse_analysis(json.dumps(["lista"]), DOCUMENT)[1] == ["response must be a JSON object"]
    assert parse_analysis('{"amounts": [{"value": ' + "9" * 5000 + "}]}", DOCUMENT)[0] is None


def answer_in(text: str) -> str:
    """An answer whose summary and key points are all `text`."""
    return llm_answer(summarySentences=[text] * 3, keyPoints=[f"{n}. {text}" for n in range(3)])


def test_summary_in_another_script_than_the_document_is_an_error() -> None:
    hebrew = "הסכם שירות בין חברת אורן מערכות לבין יעל כהן."
    polish = "Umowa o świadczenie usług między חברת אורן מערכות a יעל כהן."
    analysis, errors = parse_analysis(answer_in(polish), hebrew)
    assert analysis is None
    assert errors == [
        "summarySentences and keyPoints are mostly in LATIN script, but the document is mostly "
        "in HEBREW script: set document.language to the document's main language and write "
        "them in it"
    ]
    assert parse_analysis(answer_in(hebrew), hebrew)[1] == []


@pytest.mark.parametrize(
    ("document", "summary"),
    [
        # Chinese, Japanese and Korean scripts count as one, full-width letters as plain ones.
        ("株式会社さくらデザイン 御中 請求書", "这是一张发票。"),
        ("청구서 (주)한빛소프트", "ＡＢＣ株式会社の請求書です。"),
        # An East Asian character weighs three letters: Latin product names do not outweigh it.
        ("Amazon Web Services請求書のお知らせ", "月額料金のお知らせです。"),
        # Languages that share a script cannot be told apart, and digits are no script.
        ("Invoice INV-2026-0042", "Faktura dla Harbor & Pine Inc."),
        ("12 300,00 / 13 100,00", "Kwoty bez opisu."),
    ],
)
def test_summary_in_the_documents_script_passes(document: str, summary: str) -> None:
    assert parse_analysis(answer_in(summary), document)[1] == []
