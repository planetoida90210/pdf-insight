"""Deterministic normalization and rule checks for LLM analysis output."""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from app.schema import LlmAnalysis

# Company forms and common Polish abbrevs. Dots are removed unless the match
# sits at a sentence boundary (whitespace + capital letter, or end of text).
_ABBREV = re.compile(
    r"\bsp\.\s*z\s*o\.\s*o\.|\bs\.\s*a\.|\bm\.\s*in\.|\bp\.\s*p\.|"
    r"\b(?:r|nr|ul|al|pl|św|sw|dr|mgr|prof|tel|godz|str|poz|pkt|art|ust|"
    r"tzn|tzw|np|itd|itp|cd|ww|tj|pt|ds|wg)\.",
    re.IGNORECASE | re.UNICODE,
)
_SENTENCE_BOUNDARY_AHEAD = re.compile(r"\s+[\"„''(A-ZĄĆĘŁŃÓŚŹŻ]|\s*$")
_SENTENCE_SPLIT = re.compile(r"[.!?…]+(?:\s+|$)")

_CURRENCY_MAP = {
    "zł": "PLN",
    "zl": "PLN",
    "pln": "PLN",
    "€": "EUR",
    "eur": "EUR",
    "$": "USD",
    "usd": "USD",
    "£": "GBP",
    "gbp": "GBP",
}


def _replace_abbrev(match: re.Match[str]) -> str:
    body = match.group(0).replace(".", "")
    ahead = match.string[match.end() :]
    if _SENTENCE_BOUNDARY_AHEAD.match(ahead):
        return body + "."
    return body


def count_sentences(text: str) -> int:
    """Count sentences; Polish abbreviations like „r.” / „sp. z o.o.” do not end a sentence."""
    stripped = text.strip()
    if not stripped:
        return 0
    protected = _ABBREV.sub(_replace_abbrev, stripped)
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(protected) if part.strip()]
    return len(parts) if parts else 1


def _normalize_currency(raw: str) -> str:
    key = raw.strip().lower().replace(" ", "")
    mapped = _CURRENCY_MAP.get(key)
    if mapped:
        return mapped
    return raw.strip().upper()


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        trimmed = item.strip()
        if not trimmed:
            continue
        key = trimmed.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(trimmed)
    return out


def normalize_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Trim, dedupe, map zł→PLN, uppercase currencies — before Pydantic validation."""
    payload = dict(data)
    document = dict(payload.get("document") or {})
    if isinstance(document.get("title"), str):
        title = document["title"].strip()
        document["title"] = title or None
    if isinstance(document.get("type"), str):
        document["type"] = document["type"].strip()
    if isinstance(document.get("language"), str):
        document["language"] = document["language"].strip().lower()
    if isinstance(document.get("date"), str):
        document["date"] = document["date"].strip() or None
    payload["document"] = document

    if isinstance(payload.get("summary"), str):
        payload["summary"] = payload["summary"].strip()

    for list_key in ("keyPoints", "key_points"):
        if list_key in payload and isinstance(payload[list_key], list):
            payload[list_key] = [
                str(item).strip() for item in payload[list_key] if str(item).strip()
            ]

    entities = dict(payload.get("entities") or {})
    for key in ("organizations", "people"):
        if isinstance(entities.get(key), list):
            entities[key] = _dedupe_preserve([str(item) for item in entities[key]])
    payload["entities"] = entities

    amounts: list[dict[str, Any]] = []
    for item in payload.get("amounts") or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if isinstance(row.get("currency"), str):
            row["currency"] = _normalize_currency(row["currency"])
        if isinstance(row.get("context"), str):
            row["context"] = row["context"].strip()
        amounts.append(row)
    payload["amounts"] = amounts

    dates: list[dict[str, Any]] = []
    for item in payload.get("dates") or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if isinstance(row.get("context"), str):
            row["context"] = row["context"].strip()
        if isinstance(row.get("date"), str):
            row["date"] = row["date"].strip()
        dates.append(row)
    payload["dates"] = dates

    for list_key in ("keywords", "suspiciousInstructions", "suspicious_instructions"):
        if list_key in payload and isinstance(payload[list_key], list):
            payload[list_key] = _dedupe_preserve([str(item) for item in payload[list_key]])

    return payload


def rule_errors(analysis: LlmAnalysis) -> list[str]:
    errors: list[str] = []
    sentences = count_sentences(analysis.summary)
    if sentences < 3 or sentences > 5:
        errors.append(f"summary must have 3-5 sentences (got {sentences})")
    n_points = len(analysis.key_points)
    if n_points < 3 or n_points > 7:
        errors.append(f"keyPoints must have 3-7 items (got {n_points})")
    return errors


def parse_and_validate(data: dict[str, Any]) -> tuple[LlmAnalysis | None, list[str]]:
    normalized = normalize_payload(data)
    try:
        analysis = LlmAnalysis.model_validate(normalized)
    except ValidationError as error:
        return None, [err["msg"] for err in error.errors()]
    rules = rule_errors(analysis)
    if rules:
        return None, rules
    return analysis, []
