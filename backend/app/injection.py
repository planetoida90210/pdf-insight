"""Heuristics for instruction-like text embedded in a PDF (prompt injection)."""

from __future__ import annotations

import re

# PL/EN phrases that ask the model to ignore prior rules or invent a summary.
_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE | re.UNICODE)
    for p in (
        r"zignoruj\s+(wszystkie\s+)?(wcze[sś]niejsze\s+)?polecenia",
        r"zignoruj\s+(wszystkie\s+)?instrukcje",
        r"instrukcja\s+dla\s+systemu\s+ai",
        r"w\s+podsumowaniu\s+napisz",
        r"nie\s+wspominaj\s+o\s+tej\s+instrukcji",
        r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)",
        r"disregard\s+(all\s+)?(previous|prior)\s+(instructions?|prompts?)",
        r"you\s+are\s+now\s+(a|an)\s+",
        r"system\s*:\s*",
        r"<\s*/?\s*system\s*>",
    )
]


def scan_injection(text: str) -> bool:
    """True when the visible text looks like an instruction aimed at the model."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _PATTERNS)
