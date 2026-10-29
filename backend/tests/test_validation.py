from app.validation import count_sentences, normalize_payload, parse_and_validate, rule_errors


def test_count_sentences_handles_polish_abbreviations() -> None:
    text = (
        "Umowa nr 14/2026 dotyczy wdrożenia systemu CRM. "
        "Obowiązuje od 1 kwietnia 2026 r. do 31 marca 2028 r. "
        "Strony to Nordwave Logistics sp. z o.o. oraz Kwadrat Software S.A. "
        "Wynagrodzenie wynosi 184 500 zł. "
        "Aneks nr 1 podnosi abonament."
    )
    assert count_sentences(text) == 5


def test_count_sentences_three_to_five_boundary() -> None:
    three = "Pierwsze zdanie. Drugie zdanie. Trzecie zdanie."
    assert count_sentences(three) == 3
    two = "Tylko dwa. Zdania."
    assert count_sentences(two) == 2


def test_normalize_currency_and_dedupe() -> None:
    payload = normalize_payload(
        {
            "document": {"language": "PL", "type": "umowa", "title": "  T  ", "date": ""},
            "summary": " a. b. c. ",
            "keyPoints": [" a ", "a", " b ", " c "],
            "entities": {
                "organizations": ["Acme", "acme", "Beta"],
                "people": ["Anna", " anna "],
            },
            "amounts": [{"value": 10, "currency": "zł", "context": " x "}],
            "dates": [{"date": "2026-01-01", "context": " y "}],
            "keywords": ["CRM", "crm", "SLA"],
            "suspiciousInstructions": [" ignore "],
        }
    )
    assert payload["document"]["language"] == "pl"
    assert payload["document"]["title"] == "T"
    assert payload["document"]["date"] is None
    assert payload["amounts"][0]["currency"] == "PLN"
    assert payload["entities"]["organizations"] == ["Acme", "Beta"]
    assert payload["entities"]["people"] == ["Anna"]
    assert payload["keywords"] == ["CRM", "SLA"]


def _valid_llm_dict(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "document": {
            "language": "pl",
            "type": "umowa",
            "title": "Umowa testowa",
            "date": "2026-03-12",
        },
        "summary": (
            "Umowa dotyczy wdrożenia systemu. "
            "Obowiązuje przez dwa lata. "
            "Wynagrodzenie jest ryczałtowe."
        ),
        "keyPoints": ["Punkt jeden", "Punkt dwa", "Punkt trzy"],
        "entities": {"organizations": ["Acme"], "people": ["Anna"]},
        "amounts": [{"value": 100.0, "currency": "PLN", "context": "abonament"}],
        "dates": [{"date": "2026-03-12", "context": "podpisanie"}],
        "keywords": ["umowa"],
        "suspiciousInstructions": [],
    }
    base.update(overrides)
    return base


def test_parse_rejects_too_few_sentences() -> None:
    data = _valid_llm_dict(summary="Tylko jedno zdanie.")
    analysis, errors = parse_and_validate(data)
    assert analysis is None
    assert any("3-5" in error for error in errors)


def test_rule_errors_key_points() -> None:
    analysis, _ = parse_and_validate(_valid_llm_dict())
    assert analysis is not None
    bad = analysis.model_copy(update={"key_points": ["a", "b"]})
    assert rule_errors(bad)
