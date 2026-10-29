"""Ground amounts and dates against source document text (PL/EN formats)."""

from __future__ import annotations

import re
from datetime import date

from app.schema import Amount, AnalysisWarning, DateEntry, LlmAnalysis

# Thousands may use space/nbsp/thin-space; decimals comma or dot.
_NUMBER_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[\s\u00a0\u202f.]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(?!\d)",
    re.UNICODE,
)

_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DOT_DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")

_PL_MONTHS: dict[str, int] = {
    "stycznia": 1,
    "lutego": 2,
    "marca": 3,
    "kwietnia": 4,
    "maja": 5,
    "czerwca": 6,
    "lipca": 7,
    "sierpnia": 8,
    "września": 9,
    "wrzesnia": 9,
    "października": 10,
    "pazdziernika": 10,
    "listopada": 11,
    "grudnia": 12,
}
_EN_MONTHS: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_PL_LONG_RE = re.compile(
    r"\b(\d{1,2})\s+("
    + "|".join(sorted(_PL_MONTHS, key=len, reverse=True))
    + r")\s+(\d{4})\s*r?\.?\b",
    re.IGNORECASE | re.UNICODE,
)
_EN_LONG_RE = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(sorted(_EN_MONTHS, key=len, reverse=True)) + r")\s+(\d{4})\b",
    re.IGNORECASE,
)
_EN_LONG_RE_ALT = re.compile(
    r"\b(" + "|".join(sorted(_EN_MONTHS, key=len, reverse=True)) + r")\s+(\d{1,2}),?\s+(\d{4})\b",
    re.IGNORECASE,
)


def parse_number_token(token: str) -> float | None:
    cleaned = token.replace("\u00a0", " ").replace("\u202f", " ").strip()
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        # European: 1.234,56 vs US: 1,234.56 — last separator is decimal.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            cleaned = cleaned.replace(" ", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    else:
        # "184 500" or "184.500" (thousands) without decimals
        if re.fullmatch(r"\d{1,3}(?:[.\s]\d{3})+", cleaned):
            cleaned = re.sub(r"[.\s]", "", cleaned)
        else:
            cleaned = cleaned.replace(" ", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def collect_numbers(text: str) -> set[float]:
    values: set[float] = set()
    for match in _NUMBER_RE.finditer(text):
        value = parse_number_token(match.group(1))
        if value is not None:
            values.add(value)
            # Also store integer form when close (184500.0 and 184500)
            if abs(value - round(value)) < 1e-9:
                values.add(float(round(value)))
    return values


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def collect_dates(text: str) -> set[str]:
    found: set[str] = set()
    for match in _ISO_DATE_RE.finditer(text):
        d = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if d:
            found.add(d.isoformat())
    for match in _DOT_DATE_RE.finditer(text):
        d = _safe_date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        if d:
            found.add(d.isoformat())
    for match in _PL_LONG_RE.finditer(text):
        month = _PL_MONTHS.get(match.group(2).lower())
        if month:
            d = _safe_date(int(match.group(3)), month, int(match.group(1)))
            if d:
                found.add(d.isoformat())
    for match in _EN_LONG_RE.finditer(text):
        month = _EN_MONTHS.get(match.group(2).lower())
        if month:
            d = _safe_date(int(match.group(3)), month, int(match.group(1)))
            if d:
                found.add(d.isoformat())
    for match in _EN_LONG_RE_ALT.finditer(text):
        month = _EN_MONTHS.get(match.group(1).lower())
        if month:
            d = _safe_date(int(match.group(3)), month, int(match.group(2)))
            if d:
                found.add(d.isoformat())
    return found


def _amount_grounded(value: float, numbers: set[float]) -> bool:
    return any(abs(candidate - value) < 0.01 for candidate in numbers)


def ground_analysis(
    analysis: LlmAnalysis, source_text: str
) -> tuple[LlmAnalysis, list[AnalysisWarning]]:
    numbers = collect_numbers(source_text)
    dates = collect_dates(source_text)
    warnings: list[AnalysisWarning] = []
    kept_amounts: list[Amount] = []
    removed = 0

    for amount in analysis.amounts:
        if _amount_grounded(amount.value, numbers):
            kept_amounts.append(amount)
        else:
            removed += 1

    kept_dates: list[DateEntry] = []
    for entry in analysis.dates:
        if entry.date in dates:
            kept_dates.append(entry)
        else:
            removed += 1

    doc = analysis.document
    doc_date = doc.date
    if doc_date is not None and doc_date not in dates:
        doc_date = None
        removed += 1

    if removed:
        warnings.append(
            AnalysisWarning(
                code="UNGROUNDED_REMOVED",
                page=None,
                message=(
                    f"Usunięto {removed} wartości (kwoty/daty), których nie znaleziono "
                    "w tekście źródłowym."
                ),
            )
        )

    grounded = analysis.model_copy(
        update={
            "document": doc.model_copy(update={"date": doc_date}),
            "amounts": kept_amounts,
            "dates": kept_dates,
        }
    )
    return grounded, warnings
