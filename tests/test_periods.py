"""Reporting periods (backend/periods.py): IST calendar days, weeks from
Monday, [start, end) in UTC. Pure functions, no database."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from backend import periods


def _ist(y, m, d, hh=0, mm=0):
    """An IST wall-clock time as UTC (IST is UTC+5:30, no DST)."""
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc) - timedelta(hours=5, minutes=30)


def _range(preset, now):
    p = periods.period_range(preset, now)
    return p.start, p.end


def test_today_follows_the_ist_day_not_the_utc_one():
    # 19:00 UTC on Nov 4 is already 00:30 IST on Nov 5.
    now = datetime(2026, 11, 4, 19, 0, tzinfo=timezone.utc)
    assert _range("today", now) == (_ist(2026, 11, 5), _ist(2026, 11, 6))
    assert _range("yesterday", now) == (_ist(2026, 11, 4), _ist(2026, 11, 5))


def test_weeks_start_on_monday():
    sunday_night = _ist(2026, 11, 8, 23, 59)  # Sunday
    assert _range("this_week", sunday_night) == (_ist(2026, 11, 2), _ist(2026, 11, 9))
    assert _range("last_week", sunday_night) == (_ist(2026, 10, 26), _ist(2026, 11, 2))
    monday = _ist(2026, 11, 9, 0, 0)
    assert _range("this_week", monday) == (_ist(2026, 11, 9), _ist(2026, 11, 16))
    p = periods.period_range("this_week", monday)
    assert p.days[0] == date(2026, 11, 9) and p.days[0].weekday() == 0 and len(p.days) == 7


def test_month_quarter_and_year_edges():
    now = _ist(2026, 1, 3, 10)
    assert _range("this_month", now) == (_ist(2026, 1, 1), _ist(2026, 2, 1))
    # Last month crosses the year boundary.
    assert _range("last_month", now) == (_ist(2025, 12, 1), _ist(2026, 1, 1))
    assert _range("this_quarter", now) == (_ist(2026, 1, 1), _ist(2026, 4, 1))
    assert _range("this_year", now) == (_ist(2026, 1, 1), _ist(2027, 1, 1))

    december = _ist(2026, 12, 31, 23, 59)
    assert _range("this_quarter", december) == (_ist(2026, 10, 1), _ist(2027, 1, 1))
    assert _range("this_month", december) == (_ist(2026, 12, 1), _ist(2027, 1, 1))
    assert _range("this_quarter", _ist(2026, 6, 30, 12)) == (_ist(2026, 4, 1), _ist(2026, 7, 1))
    # A minute later in IST it is a new year, even though UTC is still Dec 31.
    new_year = _ist(2027, 1, 1, 0, 1)
    assert new_year.day == 31
    assert _range("this_year", new_year) == (_ist(2027, 1, 1), _ist(2028, 1, 1))


def test_until_caps_a_running_period_at_now():
    now = _ist(2026, 11, 4, 12)
    p = periods.period_range("this_week", now)
    assert p.until(now) == now
    last = periods.period_range("last_week", now)
    assert last.until(now) == last.end


def test_default_and_unknown_presets():
    assert periods.DEFAULT == "this_week"
    assert set(periods.LABELS) == set(periods.PRESETS)
    with pytest.raises(ValueError):
        periods.period_range("last_decade", _ist(2026, 11, 4))
