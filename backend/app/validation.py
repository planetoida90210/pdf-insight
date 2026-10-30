"""Turns the model's JSON text into a validated LlmAnalysis, or a list of errors for the retry."""

import json
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from functools import cache
from itertools import groupby
from typing import Any

from pydantic import ValidationError

from app.schema import LlmAnalysis

CURRENCIES = {"zł": "PLN", "zl": "PLN", "€": "EUR", "$": "USD", "£": "GBP"}
# Chinese, Japanese and Korean text mixes these scripts, so they count as one.
EAST_ASIAN = {"CJK", "HIRAGANA", "KATAKANA", "HANGUL", "BOPOMOFO"}
# One East Asian character holds about as much text as three letters of an alphabet.
EAST_ASIAN_WEIGHT = 3
# A script with this share of the main script's letters belongs to the document, like the English
# names in a Japanese invoice; its words may appear in the summary.
SECOND_SCRIPT_SHARE = 0.25
# Codes and names usually written in Latin ("USD", "PDF") may appear in any summary.
FOREIGN_WORDS_ALLOWED = 3
LETTERS = re.compile(r"[^\W\d_]+")


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


@cache
def _script(char: str) -> str:
    """The first word of the letter's Unicode name ("HEBREW LETTER ALEF"); Chinese, Japanese and
    Korean scripts count as one."""
    script = unicodedata.name(char, "").partition(" ")[0]
    return "CJK" if script in EAST_ASIAN else script


def _script_weights(text: str) -> Counter[str]:
    """Letters per script; an East Asian character weighs EAST_ASIAN_WEIGHT letters."""
    weights: Counter[str] = Counter()
    for char, count in Counter(text).items():
        if char.isalpha():
            script = _script(char)
            weights[script] += count * EAST_ASIAN_WEIGHT if script == "CJK" else count
    return weights


def _words(text: str) -> set[tuple[str, str]]:
    """Casefolded runs of letters of one script, with the script: "東京Tower" is two words. Marks
    are left out, so a vowel sign does not split a word."""
    letters = "".join(char for char in text.casefold() if unicodedata.category(char)[0] != "M")
    return {
        (script, "".join(run))
        for word in LETTERS.findall(letters)
        for script, run in groupby(word, _script)
    }


def _script_error(analysis: LlmAnalysis, document: str) -> str | None:
    """The summary must be in the document's main script, and its words in a script the document
    hardly uses must come from the document. Languages that share a script, like most European
    ones, cannot be told apart this way."""
    # NFKC turns full-width and presentation forms into plain letters.
    answer = unicodedata.normalize(
        "NFKC", " ".join(analysis.summary_sentences + analysis.key_points)
    )
    document = unicodedata.normalize("NFKC", document)
    written, scripts = _script_weights(answer), _script_weights(document)
    if not written or not scripts:
        return None
    [(main, main_weight)] = scripts.most_common(1)
    if (answer_main := written.most_common(1)[0][0]) != main:
        return (
            f"summarySentences and keyPoints are mostly in {answer_main} script, but the document "
            f"is mostly in {main} script: set document.language to the document's main language "
            "and write them in it"
        )
    own = {
        script for script, weight in scripts.items() if weight >= SECOND_SCRIPT_SHARE * main_weight
    }
    foreign = {(script, word) for script, word in _words(answer) if script not in own}
    if len(foreign) > FOREIGN_WORDS_ALLOWED:
        foreign -= _words(document)
    if len(foreign) <= FOREIGN_WORDS_ALLOWED:
        return None
    listed = ", ".join(sorted(word for _, word in foreign))
    return (
        f"summarySentences and keyPoints use words in another script than the document's {main} "
        f"script that the document does not contain ({listed}): write them in the language of "
        "document.language"
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
