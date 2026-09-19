"""Duration parsing and deadline arithmetic.

Language models are unreliable at date arithmetic, and a contract deadline that
is wrong by three days is worse than no deadline at all -- it is wrong with
confidence, on a calendar the user will act on.  So the division of labour here
is strict: a model (or a regex, offline) may identify *that* a clause says "within
thirty (30) days of the Effective Date", and this module computes what date that
is.  Nothing else in the system performs date arithmetic.

Business-day counting follows the common commercial convention: count only
weekdays, skip listed holidays, and if a calendar-day deadline lands on a
non-working day, roll forward.  Jurisdictions differ on rolling, so the behaviour
is a parameter rather than an assumption.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta

#: Number words that appear in contract durations. Contracts habitually write
#: "thirty (30) days"; the digits are captured preferentially, and these cover
#: the cases where they are absent.
_NUMBER_WORDS: Final[dict[str, int]] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "forty-five": 45,
    "fifty": 50,
    "sixty": 60,
    "ninety": 90,
    "one hundred and eighty": 180,
    "one hundred eighty": 180,
    "three hundred and sixty-five": 365,
}

_UNIT_DAYS: Final[dict[str, int]] = {
    "day": 1,
    "week": 7,
    "fortnight": 14,
}

#: "(30)" in "thirty (30) days" -- the parenthetical digits are authoritative,
#: since that is the convention the drafting style exists to enforce.
_DURATION = re.compile(
    r"""
    (?P<words>[a-z\- ]+?)?\s*
    (?:\((?P<paren>\d{1,4})\)\s*)?
    (?P<digits>\d{1,4})?\s*
    (?P<unit>business\s+day|working\s+day|calendar\s+day|day|week|fortnight|month|year)s?
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class Duration:
    """A parsed period, in the unit the contract used."""

    quantity: int
    unit: str
    business_days: bool

    @property
    def approximate_days(self) -> int:
        """Calendar-day estimate, for ordering deadlines before resolution."""
        if self.unit == "month":
            return self.quantity * 30
        if self.unit == "year":
            return self.quantity * 365
        return self.quantity * _UNIT_DAYS.get(self.unit, 1)


def parse_duration(text: str) -> Duration | None:
    """Extract the first duration from a phrase.

    >>> parse_duration("within thirty (30) days of receipt")
    Duration(quantity=30, unit='day', business_days=False)
    >>> parse_duration("no later than 5 business days")
    Duration(quantity=5, unit='day', business_days=True)
    """
    for match in _DURATION.finditer(text):
        unit_raw = match.group("unit").lower()
        business = unit_raw.startswith(("business", "working"))
        unit = "day" if unit_raw.endswith("day") else unit_raw

        quantity = _resolve_quantity(match)
        if quantity is None or quantity <= 0:
            continue
        return Duration(quantity=quantity, unit=unit, business_days=business)
    return None


def _resolve_quantity(match: re.Match[str]) -> int | None:
    """Digits win over words; parenthetical digits win over both."""
    if match.group("paren"):
        return int(match.group("paren"))
    if match.group("digits"):
        return int(match.group("digits"))
    words = (match.group("words") or "").strip().lower()
    if not words:
        return None
    # Take the longest matching number word so "one hundred and eighty" is not
    # read as "one".
    for phrase in sorted(_NUMBER_WORDS, key=len, reverse=True):
        if words.endswith(phrase):
            return _NUMBER_WORDS[phrase]
    return None


def add_duration(
    anchor: date,
    duration: Duration,
    *,
    holidays: frozenset[date] = frozenset(),
    roll_forward: bool = True,
) -> date:
    """Add a parsed duration to an anchor date.

    Args:
        anchor: The date the period runs from.
        duration: The period to add.
        holidays: Non-working days to skip when counting business days.
        roll_forward: Whether a calendar deadline landing on a non-working day
            moves to the next working day. Common in commercial practice, but not
            universal, so it is explicit.
    """
    if duration.business_days:
        return add_business_days(anchor, duration.quantity, holidays=holidays)

    if duration.unit == "month":
        result = anchor + relativedelta(months=duration.quantity)
    elif duration.unit == "year":
        result = anchor + relativedelta(years=duration.quantity)
    else:
        result = anchor + timedelta(days=duration.approximate_days)

    if roll_forward:
        result = next_working_day(result, holidays=holidays)
    return result


def add_business_days(anchor: date, count: int, *, holidays: frozenset[date] = frozenset()) -> date:
    """Advance ``count`` working days from ``anchor``, skipping weekends and holidays.

    Counting starts the day *after* the anchor, which is the standard reading of
    "within five business days of receipt".
    """
    if count < 0:
        raise ValueError("business-day count must not be negative")
    current = anchor
    remaining = count
    while remaining > 0:
        current += timedelta(days=1)
        if is_working_day(current, holidays=holidays):
            remaining -= 1
    return current


def is_working_day(day: date, *, holidays: frozenset[date] = frozenset()) -> bool:
    return day.weekday() < 5 and day not in holidays


def next_working_day(day: date, *, holidays: frozenset[date] = frozenset()) -> date:
    current = day
    while not is_working_day(current, holidays=holidays):
        current += timedelta(days=1)
    return current


#: Date shapes that appear in contracts. Ordered so the least ambiguous wins.
_DATE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"\b(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{4})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b((?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s+\d{4})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
)


def find_dates(text: str) -> tuple[tuple[date, int, int], ...]:
    """Every unambiguous date in the text, with its offsets.

    Purely numeric forms such as ``03/04/2026`` are deliberately *not* matched:
    they mean 3 April in most of the world and 4 March in the United States, and
    a contract analysis tool that guesses wrong about a deadline has done real
    harm. Ambiguous dates are surfaced to the user to confirm instead.
    """
    found: list[tuple[date, int, int]] = []
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            try:
                parsed = date_parser.parse(match.group(1), dayfirst=True).date()
            except (ValueError, OverflowError):
                continue
            found.append((parsed, match.start(1), match.end(1)))
    return tuple(sorted(found, key=lambda item: item[1]))


AMBIGUOUS_DATE = re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b")


def find_ambiguous_dates(text: str) -> tuple[tuple[str, int, int], ...]:
    """Numeric dates whose day/month order cannot be determined from the text."""
    return tuple(
        (m.group(0), m.start(), m.end())
        for m in AMBIGUOUS_DATE.finditer(text)
        # A day component above 12 disambiguates it; those are not reported.
        if not _disambiguated(m.group(0))
    )


def _disambiguated(value: str) -> bool:
    parts = re.split(r"[/.-]", value)
    return any(part.isdigit() and 12 < int(part) <= 31 for part in parts[:2])


def earliest(dates: Iterable[date | None]) -> date | None:
    present = [d for d in dates if d is not None]
    return min(present) if present else None


def sort_by_due(items: Sequence[tuple[str, date | None]]) -> tuple[tuple[str, date | None], ...]:
    """Order by due date, with undated items last rather than dropped."""
    return tuple(sorted(items, key=lambda item: (item[1] is None, item[1] or date.max)))
