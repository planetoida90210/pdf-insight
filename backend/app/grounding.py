"""Keeps only the amounts and dates whose digits appear in the source text, in any language."""

import re

from app.schema import LlmAnalysis

# "184 500,00", "1.234,56", "1,234.56", "1'234.50", "8600": thousands split by a space, nbsp,
# dot, comma or apostrophe.
NUMBER_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[ \u00a0\u202f.,'\u2019]\d{3})+|\d+)(?:[.,](\d+))?(?!\d)"
)
AMOUNT_TOLERANCE = 0.01


def ground_analysis(analysis: LlmAnalysis, source: str) -> tuple[LlmAnalysis, int]:
    """Returns the analysis without ungrounded amounts and dates, and how many were removed."""
    numbers, integers = numbers_in(source), integers_in(source)
    amounts = [
        amount
        for amount in analysis.amounts
        if any(abs(amount.value - number) < AMOUNT_TOLERANCE for number in numbers)
    ]
    entries = [entry for entry in analysis.dates if date_in(entry.date, integers)]
    doc_date = analysis.document.date
    if doc_date is not None and not date_in(doc_date, integers):
        doc_date = None
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
    """A line break can split one number ("13\\n100,00") or separate two; both readings count."""
    return _numbers(text) | _numbers(text.replace("\n", " "))


def integers_in(text: str) -> set[int]:
    return {int(digits) for digits in re.findall(r"\d+", text)}


def date_in(iso_date: str, integers: set[int]) -> bool:
    """Month names differ in every language, so only what every date format writes in digits is
    checked: the year (all four digits or the last two) and the day."""
    year, _, day = (int(part) for part in iso_date.split("-"))
    return (year in integers or year % 100 in integers) and day in integers


def _numbers(text: str) -> set[float]:
    return {
        float(re.sub(r"\D", "", whole) + "." + (fraction or "0"))
        for whole, fraction in NUMBER_RE.findall(text)
    }
