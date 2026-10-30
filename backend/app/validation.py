"""Turns the model's JSON text into a validated LlmAnalysis, or a list of errors for the retry."""

import json
import unicodedata
from collections import Counter
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from app.schema import LlmAnalysis

CURRENCIES = {"zł": "PLN", "zl": "PLN", "€": "EUR", "$": "USD", "£": "GBP"}
# Chinese, Japanese and Korean text mixes these scripts, so they count as one.
EAST_ASIAN = {"CJK", "HIRAGANA", "KATAKANA", "HANGUL", "BOPOMOFO"}
# One East Asian character holds about as much text as three letters of an alphabet.
EAST_ASIAN_WEIGHT = 3


def parse_analysis(raw: str, document: str) -> tuple[LlmAnalysis | None, list[str]]:
    """`document` is the text the model analysed; the summary must be in its main script."""
    try:
        data = json.loads(raw)
    except ValueError as error:
        # Also an integer longer than Python's 4300-digit limit, which is not a JSONDecodeError.
        return None, [f"response is not valid JSON ({error})"]
    if not isinstance(data, dict):
        return None, ["response must be a JSON object"]
    try:
        analysis = LlmAnalysis.model_validate(_normalize(data))
    except ValidationError as error:
        return None, [_describe(detail) for detail in error.errors()]
    if script_error := _script_error(analysis, document):
        return None, [script_error]
    return analysis, []


def dedupe(items: Iterable[str]) -> list[str]:
    """Trims, drops empty strings and case-insensitive duplicates, keeps the first spelling."""
    seen: set[str] = set()
    unique = []
    for item in (item.strip() for item in items):
        if item and item.casefold() not in seen:
            seen.add(item.casefold())
            unique.append(item)
    return unique


def _main_script(text: str) -> str | None:
    """The Unicode script of most of the text's letters: the first word of their Unicode names
    ("HEBREW LETTER ALEF"), after NFKC turns full-width and presentation forms into plain ones."""
    weights: Counter[str] = Counter()
    for char, count in Counter(unicodedata.normalize("NFKC", text)).items():
        if char.isalpha():
            script = unicodedata.name(char, "").partition(" ")[0]
            if script in EAST_ASIAN:
                script, count = "CJK", count * EAST_ASIAN_WEIGHT
            weights[script] += count
    return weights.most_common(1)[0][0] if weights else None


def _script_error(analysis: LlmAnalysis, document: str) -> str | None:
    """A summary in another script than the document is in another language. Languages that
    share a script, like most European ones, cannot be told apart this way."""
    written = _main_script(" ".join([*analysis.summary_sentences, *analysis.key_points]))
    expected = _main_script(document)
    if written is None or expected is None or written == expected:
        return None
    return (
        f"summarySentences and keyPoints are mostly in {written} script, but the document is "
        f"mostly in {expected} script: set document.language to the document's main language "
        "and write them in it"
    )


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    """Deterministic clean-up before validation: trim, dedupe, empty strings to null, zł to PLN."""
    document = data.get("document")
    if isinstance(document, dict):
        for key in ("title", "date"):
            if isinstance(document.get(key), str):
                document[key] = document[key].strip() or None
        if isinstance(document.get("language"), str):
            document["language"] = document["language"].strip().lower()
    for key in ("organizations", "people"):
        _dedupe_strings(data.get("entities"), key)
    for key in ("keyPoints", "keywords", "suspiciousInstructions"):
        _dedupe_strings(data, key)
    for amount in data.get("amounts") or []:
        if isinstance(amount, dict) and isinstance(amount.get("currency"), str):
            currency = amount["currency"].strip()
            amount["currency"] = CURRENCIES.get(currency.lower(), currency.upper())
    return data


def _dedupe_strings(container: Any, key: str) -> None:
    value = container.get(key) if isinstance(container, dict) else None
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        container[key] = dedupe(value)


def _describe(detail: Any) -> str:
    location = ".".join(str(part) for part in detail["loc"])
    return f"{location}: {detail['msg']}"
