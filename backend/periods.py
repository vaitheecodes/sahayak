"""Reporting periods: fixed presets, computed in IST (weeks start Monday).

One helper for the manager and technician dashboards (the frontend has
one matching PeriodSelect). A period is [start, end) in UTC; `end` is the
start of the next period, so "this week" ends next Monday 00:00 IST even
while it is still Wednesday. `until` caps it at now for "so far" figures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from backend.timeutil import IST, utcnow

PRESETS = ("today", "yesterday", "this_week", "last_week", "this_month", "last_month", "this_quarter",
           "this_year")
DEFAULT = "this_week"
LABELS = {
    "today": "Today", "yesterday": "Yesterday", "this_week": "This week", "last_week": "Last week",
    "this_month": "This month", "last_month": "Last month", "this_quarter": "This quarter",
    "this_year": "This year",
}


@dataclass(frozen=True)
class Period:
    preset: str
    label: str
    start: datetime  # UTC, inclusive
    end: datetime  # UTC, exclusive
    days: tuple[date, ...]  # the IST calendar days in the period

    def until(self, now: datetime | None = None) -> datetime:
        """The end, or now if the period is still running."""
        return min(self.end, now or utcnow())

    def as_dict(self) -> dict:
        return {"preset": self.preset, "label": self.label, "start": self.start.isoformat(),
                "end": self.end.isoformat()}


def _month_start(day: date, months_back: int = 0) -> date:
    index = day.year * 12 + day.month - 1 - months_back
    return date(index // 12, index % 12 + 1, 1)


def _next_month(day: date) -> date:
    index = day.year * 12 + day.month
    return date(index // 12, index % 12 + 1, 1)


def _bounds(preset: str, today: date) -> tuple[date, date]:
    """[first, after) IST calendar days."""
    monday = today - timedelta(days=today.weekday())
    if preset == "today":
        return today, today + timedelta(days=1)
    if preset == "yesterday":
        return today - timedelta(days=1), today
    if preset == "this_week":
        return monday, monday + timedelta(days=7)
    if preset == "last_week":
        return monday - timedelta(days=7), monday
    if preset == "this_month":
        first = _month_start(today)
        return first, _next_month(first)
    if preset == "last_month":
        first = _month_start(today, 1)
        return first, _month_start(today)
    if preset == "this_quarter":
        first = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
        return first, _next_month(_next_month(_next_month(first)))
    if preset == "this_year":
        return date(today.year, 1, 1), date(today.year + 1, 1, 1)
    raise ValueError(f"Unknown period {preset!r}")


def period_range(preset: str = DEFAULT, now: datetime | None = None) -> Period:
    """Raises ValueError for an unknown preset."""
    if preset not in PRESETS:
        raise ValueError(f"Unknown period {preset!r}")
    today = (now or utcnow()).astimezone(IST).date()
    first, after = _bounds(preset, today)

    def utc(day: date) -> datetime:
        return datetime.combine(day, time.min, tzinfo=IST).astimezone(timezone.utc)

    days = tuple(first + timedelta(days=i) for i in range((after - first).days))
    return Period(preset, LABELS[preset], utc(first), utc(after), days)


def ist_day(value: datetime) -> date:
    return value.astimezone(IST).date()
