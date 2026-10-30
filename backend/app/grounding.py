"""Keeps only the amounts and dates whose digits appear in the source text, in any script."""

import re
from decimal import Decimal

from app.schema import LlmAnalysis


def ground_analysis(analysis: LlmAnalysis, source: str) -> tuple[LlmAnalysis, int]:
    """Returns the analysis without ungrounded amounts and dates, and how many were removed."""
    text, integers = ascii_digits(source), integers_in(source)
    amounts = [amount for amount in analysis.amounts if amount_in(amount.value, text)]
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


def ascii_digits(text: str) -> str:
    """The decimal digits of every script ("١٢", "१२") as ASCII digits."""
    return re.sub(r"\d", lambda digit: str(int(digit[0])), text)


def amount_in(value: float, text: str) -> bool:
    """Whether the text (with ASCII digits) writes the value: its digits without trailing zeros,
    in order from the start of a digit group, at most one separator of any kind between two of
    them, then only zeros to the group's end, at least the ones its integer part needs.
    "12 300,00", "1,23,600", "13\\n100,00" and "(105.00)" write 12300, 123600, 13100 and -105;
    "1" does not write 1000."""
    # str() gives the shortest decimal form of a float; format(value, "f") would round to six
    # places and add float noise to large values.
    digits = re.sub(r"\D", "", format(Decimal(str(abs(value))), "f")).rstrip("0") or "0"
    zeros = max(len(str(int(abs(value)))) - len(digits), 0)
    # The pattern starts with the first digit and only then checks that no digit precedes it:
    # a pattern that starts with a literal is searched for several times faster.
    separated = "".join(rf"\W?{digit}" for digit in digits[1:])
    pattern = digits[0] + r"(?<!\d\d)" + separated + r"(?:\W?0)" + f"{{{zeros},}}" + r"(?!\d)"
    return re.search(pattern, text) is not None


def integers_in(text: str) -> set[int]:
    """Every run of digits as a number; int() reads the decimal digits of any script."""
    return {int(digits) for digits in re.findall(r"\d+", text)}


def date_in(iso_date: str, integers: set[int]) -> bool:
    """Month names differ in every language, so only what every date format writes in digits is
    checked: the year (all four digits or the last two) and the day."""
    year, _, day = (int(part) for part in iso_date.split("-"))
    return (year in integers or year % 100 in integers) and day in integers
