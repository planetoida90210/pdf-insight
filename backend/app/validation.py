"""Turns the model's JSON text into a validated LlmAnalysis, or a list of errors for the retry."""

import json
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from app.schema import LlmAnalysis

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
        return LlmAnalysis.model_validate(_normalize(data)), []
    except ValidationError as error:
        return None, [_describe(detail) for detail in error.errors()]


def dedupe(items: Iterable[str]) -> list[str]:
    """Trims, drops empty strings and case-insensitive duplicates, keeps the first spelling."""
    seen: set[str] = set()
    unique = []
    for item in (item.strip() for item in items):
        if item and item.casefold() not in seen:
            seen.add(item.casefold())
            unique.append(item)
    return unique


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
