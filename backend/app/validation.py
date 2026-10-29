"""Turns the model's JSON text into a validated LlmAnalysis, or a list of errors for the retry."""

import json
import re
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from app.schema import LlmAnalysis

SUMMARY_SENTENCES = (3, 5)
KEY_POINTS = (3, 7)

# Dots inside these abbreviations do not end a sentence unless a new sentence starts after them.
ABBREVIATION_RE = re.compile(
    r"(?i:\bsp\.\s*z\s*o\.\s*o\.|\bs\.\s*a\.|\bm\.\s*in\.|\b(?:r|nr|ul|al|pl|św|dr|mgr|prof|tel|"
    r"godz|str|poz|pkt|art|ust|tzn|tzw|np|itd|itp|tj|ds|wg|ok|tys|mln|mld|zob|por|lit|dz)\.)"
)
SENTENCE_START_RE = re.compile(r"\s+[\"„(A-ZĄĆĘŁŃÓŚŹŻ]|\s*$")
# A single capital letter with a dot is an initial ("A. Kowalczyk"), never a sentence end.
INITIAL_RE = re.compile(r"\b([A-ZĄĆĘŁŃÓŚŹŻ])\.")
SENTENCE_END_RE = re.compile(r"[.!?…]+(?:\s+|$)")

CURRENCIES = {"zł": "PLN", "zl": "PLN", "€": "EUR", "$": "USD", "£": "GBP"}


def parse_analysis(raw: str) -> tuple[LlmAnalysis | None, list[str]]:
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
    return (None, errors) if (errors := rule_errors(analysis)) else (analysis, [])


def rule_errors(analysis: LlmAnalysis) -> list[str]:
    errors = []
    low, high = SUMMARY_SENTENCES
    if not low <= (sentences := count_sentences(analysis.summary)) <= high:
        errors.append(f"summary must have {low}-{high} sentences, has {sentences}")
    low, high = KEY_POINTS
    if not low <= (points := len(analysis.key_points)) <= high:
        errors.append(f"keyPoints must have {low}-{high} items, has {points}")
    return errors


def count_sentences(text: str) -> int:
    protected = INITIAL_RE.sub(r"\1", ABBREVIATION_RE.sub(_keep_final_dot_at_sentence_end, text))
    return sum(1 for part in SENTENCE_END_RE.split(protected) if part.strip())


def dedupe(items: Iterable[str]) -> list[str]:
    """Trims, drops empty strings and case-insensitive duplicates, keeps the first spelling."""
    seen: set[str] = set()
    unique = []
    for item in (item.strip() for item in items):
        if item and item.casefold() not in seen:
            seen.add(item.casefold())
            unique.append(item)
    return unique


def _keep_final_dot_at_sentence_end(match: re.Match[str]) -> str:
    bare = match.group(0).replace(".", "")
    return bare + "." if SENTENCE_START_RE.match(match.string, match.end()) else bare


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
