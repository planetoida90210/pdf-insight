"""Heuristic detection of instruction-like text aimed at an AI model (prompt injection)."""

import re

INJECTION_RE = re.compile(
    "|".join(
        (
            r"zignoruj\s+(wszystkie\s+)?(wcze[sś]niejsze\s+)?(polecenia|instrukcje)",
            r"instrukcja\s+dla\s+systemu\s+ai",
            r"w\s+podsumowaniu\s+napisz",
            r"nie\s+wspominaj\s+o\s+tej\s+instrukcji",
            r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)",
            r"disregard\s+(all\s+)?(previous|prior)\s+(instructions?|prompts?)",
            r"you\s+are\s+now\s+an?\s",
            r"<\s*/?\s*system\s*>",
        )
    ),
    re.IGNORECASE,
)


def find_injection(text: str) -> str | None:
    """Returns the first instruction-like phrase, or None when the text looks clean."""
    match = INJECTION_RE.search(text)
    return match.group(0) if match else None
