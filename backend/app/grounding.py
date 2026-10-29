"""Keeps only the amounts and dates that appear in the source text (Polish and English formats)."""

import re
from contextlib import suppress
from datetime import date

from app.schema import LlmAnalysis

# "184 500,00", "1.234,56", "1,234.56", "8600": thousands split by a space, nbsp, dot or comma.
NUMBER_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[ \u00a0\u202f.,]\d{3})+|\d+)(?:[.,](\d+))?(?!\d)")
AMOUNT_TOLERANCE = 0.01

MONTHS = {
    month: number
    for number, names in enumerate(
        (
            ("stycznia", "january"),
            ("lutego", "february"),
            ("marca", "march"),
            ("kwietnia", "april"),
            ("maja", "may"),
            ("czerwca", "june"),
            ("lipca", "july"),
            ("sierpnia", "august"),
            ("września", "wrzesnia", "september"),
            ("października", "pazdziernika", "october"),
            ("listopada", "november"),
            ("grudnia", "december"),
        ),
        start=1,
    )
    for month in names
}
MONTH_NAME = "|".join(MONTHS)

# (pattern, group numbers of year, month, day)
DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), (1, 2, 3)),
    (re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b"), (3, 2, 1)),
    (re.compile(rf"\b(\d{{1,2}})\s+({MONTH_NAME})\s+(\d{{4}})\b", re.IGNORECASE), (3, 2, 1)),
    (re.compile(rf"\b({MONTH_NAME})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.IGNORECASE), (3, 1, 2)),
]


def ground_analysis(analysis: LlmAnalysis, source: str) -> tuple[LlmAnalysis, int]:
    """Returns the analysis without ungrounded amounts and dates, and how many were removed."""
    numbers, dates = numbers_in(source), dates_in(source)
    amounts = [
        amount
        for amount in analysis.amounts
        if any(abs(amount.value - number) < AMOUNT_TOLERANCE for number in numbers)
    ]
    entries = [entry for entry in analysis.dates if entry.date in dates]
    doc_date = analysis.document.date if analysis.document.date in dates else None
    removed = len(analysis.amounts) - len(amounts) + len(analysis.dates) - len(entries)
    if doc_date != analysis.document.date:
        removed += 1
    grounded = analysis.model_copy(
        update={
            "document": analysis.document.model_copy(update={"date": doc_date}),
            "amounts": amounts,
            "dates": entries,
        }
    )
    return grounded, removed


def numbers_in(text: str) -> set[float]:
    return {
        float(re.sub(r"\D", "", whole) + "." + (fraction or "0"))
        for whole, fraction in NUMBER_RE.findall(text)
    }


def dates_in(text: str) -> set[str]:
    found = set()
    for pattern, (year, month, day) in DATE_PATTERNS:
        for match in pattern.finditer(text):
            month_text = match[month].lower()
            month_number = int(month_text) if month_text.isdigit() else MONTHS[month_text]
            with suppress(ValueError):
                found.add(date(int(match[year]), month_number, int(match[day])).isoformat())
    return found
