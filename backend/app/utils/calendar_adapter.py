"""Calendar adapter implementations for different calendar systems.

These utilities mirror the frontend calendar adapters so the backend can
compute period boundaries (week/month/year) consistently for analytics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol, Tuple


class CalendarAdapter(Protocol):
    """Interface for calendar adapters."""

    def week_range(self, target: date, first_day_of_week: int) -> Tuple[date, date]:
        """Return inclusive week boundaries for the given date."""

    def month_range(self, target: date) -> Tuple[date, date]:
        """Return inclusive month boundaries for the given date."""

    def year_range(self, target: date) -> Tuple[date, date]:
        """Return inclusive year boundaries for the given date."""


@dataclass(frozen=True)
class GregorianCalendarAdapter:
    """Standard Gregorian calendar adapter."""

    def week_range(self, target: date, first_day_of_week: int) -> Tuple[date, date]:
        # first_day_of_week: 1=Monday ... 7=Sunday (ISO style)
        offset = (target.isoweekday() - first_day_of_week) % 7
        start = target - timedelta(days=offset)
        end = start + timedelta(days=6)
        return start, end

    def month_range(self, target: date) -> Tuple[date, date]:
        start = target.replace(day=1)
        if start.month == 12:
            next_month = date(start.year + 1, 1, 1)
        else:
            next_month = date(start.year, start.month + 1, 1)
        end = next_month - timedelta(days=1)
        return start, end

    def year_range(self, target: date) -> Tuple[date, date]:
        start = target.replace(month=1, day=1)
        end = target.replace(month=12, day=31)
        return start, end


@dataclass(frozen=True)
class MayanCalendarAdapter:
    """Mayan 13-moon calendar adapter (28-day months + Day Out of Time)."""

    _DAY_OUT_OF_TIME_OFFSET: int = 364
    _MOON_LENGTH_DAYS: int = 28

    def _year_start(self, target: date) -> date:
        july_26_this_year = date(target.year, 7, 26)
        if target >= july_26_this_year:
            return july_26_this_year
        return date(target.year - 1, 7, 26)

    def _day_offset(self, target: date) -> int:
        start = self._year_start(target)
        return (target - start).days

    def _clamp_day_out_of_time(self, target: date) -> Tuple[date, date]:
        start = self._year_start(target)
        day_out = start + timedelta(days=self._DAY_OUT_OF_TIME_OFFSET)
        return day_out, day_out

    def week_range(self, target: date, _: int) -> Tuple[date, date]:
        offset = self._day_offset(target)
        if offset >= self._DAY_OUT_OF_TIME_OFFSET:
            return self._clamp_day_out_of_time(target)
        start = self._year_start(target) + timedelta(days=(offset // 7) * 7)
        end = start + timedelta(days=6)
        return start, end

    def month_range(self, target: date) -> Tuple[date, date]:
        offset = self._day_offset(target)
        if offset >= self._DAY_OUT_OF_TIME_OFFSET:
            return self._clamp_day_out_of_time(target)
        start = self._year_start(target) + timedelta(
            days=(offset // self._MOON_LENGTH_DAYS) * self._MOON_LENGTH_DAYS
        )
        end = start + timedelta(days=self._MOON_LENGTH_DAYS - 1)
        return start, end

    def year_range(self, target: date) -> Tuple[date, date]:
        start = self._year_start(target)
        end = start.replace(year=start.year + 1) - timedelta(days=1)
        return start, end


def get_calendar_adapter(system: str) -> CalendarAdapter:
    """Factory for calendar adapters."""

    if system == "mayan_13_moon":
        return MayanCalendarAdapter()
    return GregorianCalendarAdapter()
