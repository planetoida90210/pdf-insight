from app.grounding import collect_dates, collect_numbers, ground_analysis, parse_number_token
from app.schema import Amount, DateEntry, Entities, LlmAnalysis, LlmDocument


def test_parse_polish_and_english_numbers() -> None:
    assert parse_number_token("184 500,00") == 184500.0
    assert parse_number_token("12\u00a0300") == 12300.0
    assert parse_number_token("2 150") == 2150.0
    assert parse_number_token("1,234.56") == 1234.56
    assert parse_number_token("99.5") == 99.5


def test_collect_numbers_from_source() -> None:
    text = "Wynagrodzenie 184 500,00 zł oraz abonament 12 300 PLN. Aneks: 13 100."
    numbers = collect_numbers(text)
    assert 184500.0 in numbers
    assert 12300.0 in numbers
    assert 13100.0 in numbers


def test_collect_polish_and_iso_dates() -> None:
    text = "Umowa z 12.03.2026, start 1 kwietnia 2026 r., ISO 2027-04-01, March 15, 2026."
    dates = collect_dates(text)
    assert "2026-03-12" in dates
    assert "2026-04-01" in dates
    assert "2027-04-01" in dates
    assert "2026-03-15" in dates


def _analysis(**kwargs: object) -> LlmAnalysis:
    base = LlmAnalysis(
        document=LlmDocument(language="pl", type="umowa", title="T", date="2026-03-12"),
        summary="Pierwsze zdanie. Drugie zdanie. Trzecie zdanie.",
        key_points=["a", "b", "c"],
        entities=Entities(organizations=["Acme"], people=["Anna"]),
        amounts=[
            Amount(value=184500.0, currency="PLN", context="wdrożenie"),
            Amount(value=999_999.0, currency="PLN", context="fałszywa kwota"),
        ],
        dates=[
            DateEntry(date="2026-04-01", context="start"),
            DateEntry(date="2099-01-01", context="fikcja"),
        ],
        keywords=["crm"],
        suspicious_instructions=[],
    )
    return base.model_copy(update=kwargs) if kwargs else base


def test_grounding_drops_ungrounded_and_nulls_date() -> None:
    source = "Umowa z dnia 12.03.2026. Wynagrodzenie 184 500,00 zł. Start 1 kwietnia 2026 r."
    grounded, warnings = ground_analysis(_analysis(), source)
    assert len(grounded.amounts) == 1
    assert grounded.amounts[0].value == 184500.0
    assert len(grounded.dates) == 1
    assert grounded.dates[0].date == "2026-04-01"
    assert grounded.document.date == "2026-03-12"
    assert any(w.code == "UNGROUNDED_REMOVED" for w in warnings)

    # Ungrounded document.date → null
    bad_date = _analysis(
        document=LlmDocument(language="pl", type="umowa", title="T", date="2099-12-31"),
        amounts=[Amount(value=184500.0, currency="PLN", context="ok")],
        dates=[DateEntry(date="2026-04-01", context="start")],
    )
    grounded2, _ = ground_analysis(bad_date, source)
    assert grounded2.document.date is None
