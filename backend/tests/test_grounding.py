import json

import pytest

from app.grounding import amount_in, ascii_digits, date_in, ground_analysis, integers_in
from app.schema import LlmAnalysis
from tests.fakes import llm_answer


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (184500, "184 500,00 zł"),
        (12300, "12\u00a0300 PLN"),
        (2150, "2 150 EUR"),
        (1234.56, "1.234,56"),
        (1234.56, "1,234.56"),
        (1234.5, "1'234.50"),
        (99.5, "99,5%"),
        (0.05, "0,05 zł/kWh"),
        # Large totals with cents and rates with more than six decimals keep all their digits.
        (12345678901.12, "12,345,678,901.12 USD"),
        (0.1234567, "kurs 0,1234567"),
        (1e16, "10 000 000 000 000 000"),
        # Lakh grouping, a thin space, a typographic apostrophe, Arabic and Devanagari digits.
        (123600, "₹1,23,600.00"),
        (12300, "12\u2009300"),
        (1234.5, "1’234.50"),
        (12500, "١٢٬٥٠٠٫٠٠ ر.س"),
        (1250, "१,२५०"),
        # Credit notes write negative amounts with a minus or in parentheses.
        (-363.93, "Total credit: -$363.93"),
        (-250, "Goodwill discount: ($250.00)"),
        # A line break can split one number or separate two.
        (13100, "abonament w wysokości 13\n100,00 PLN"),
        (120, "użytkownicy: 120\n135"),
        (135, "użytkownicy: 120\n135"),
        # Trailing zeros are not compared, so a magnitude written in words is found too.
        (2500000, "2,5 mln zł"),
    ],
)
def test_finds_an_amount_written_in_any_format(value: float, text: str) -> None:
    assert amount_in(value, ascii_digits(text))


@pytest.mark.parametrize(
    ("value", "text"),
    [(5, "105 PLN"), (25, "rok 2025"), (1, "184 500,00 zł od 01.04.2026"), (1234.5, "1 234,56")],
)
def test_digits_inside_another_number_do_not_count(value: float, text: str) -> None:
    assert not amount_in(value, ascii_digits(text))


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
        "١٢ مارس ٢٠٢٦",
        "१२.०३.२०२६",
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
