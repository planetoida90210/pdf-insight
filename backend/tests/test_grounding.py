import json

import pytest

from app.grounding import date_in, ground_analysis, integers_in, numbers_in
from app.schema import LlmAnalysis
from tests.fakes import llm_answer


def test_reads_polish_and_english_number_formats() -> None:
    text = "184 500,00 zł; 12\u00a0300 PLN; 2 150 EUR; 1.234,56; 1,234.56; 1'234.50; 99,5%"
    assert {184500.0, 12300.0, 2150.0, 1234.56, 1234.5, 99.5} <= numbers_in(text)


def test_line_break_can_split_one_number_or_separate_two() -> None:
    text = "abonament w wysokości 13\n100,00 PLN, użytkownicy: 120\n135"
    assert {13100.0, 120.0, 135.0} <= numbers_in(text)


@pytest.mark.parametrize(
    "text",
    [
        "12.03.2026",
        "2026-03-12",
        "03/12/2026",
        "12/03/26",
        "12 marca 2026 r.",
        "March 12, 2026",
        "Mar 12, 2026",
        "12. März 2026",
        "12 mars 2026",
        "12 de marzo de 2026",
    ],
)
def test_finds_a_date_written_in_any_format(text: str) -> None:
    assert date_in("2026-03-12", integers_in(text))


def test_rejects_a_date_whose_year_or_day_is_not_in_the_text() -> None:
    integers = integers_in("Umowa z 12.03.2026")
    assert not date_in("2027-03-12", integers)
    assert not date_in("2026-03-15", integers)


def test_drops_ungrounded_values_and_counts_them() -> None:
    analysis = LlmAnalysis.model_validate(
        json.loads(
            llm_answer(
                document={"language": "pl", "type": "umowa", "title": None, "date": "2099-12-31"},
                amounts=[
                    {"value": 184500, "currency": "PLN", "context": "wdrożenie"},
                    {"value": 1, "currency": "PLN", "context": "wstrzyknięta kwota"},
                ],
                dates=[
                    {"date": "2026-04-01", "context": "start"},
                    {"date": "2099-01-01", "context": "fikcja"},
                ],
            )
        )
    )
    grounded, removed = ground_analysis(analysis, "Wynagrodzenie 184 500,00 zł od 01.04.2026.")
    assert [a.value for a in grounded.amounts] == [184500]
    assert [d.date for d in grounded.dates] == ["2026-04-01"]
    assert grounded.document.date is None
    assert removed == 3
