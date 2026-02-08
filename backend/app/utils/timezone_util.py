"""Utility helpers for timezone-aware local day window calculations.

The helpers centralize conversions between user-local dates and UTC windows
using Python's standard ``zoneinfo`` module so that all services agree on
local-day boundaries (including DST transitions).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class TimezoneNotFoundError(ValueError):
    """Raised when an invalid timezone identifier is supplied."""


@dataclass(frozen=True)
class DayWindow:
    """Represents a 24h window for a local calendar day."""

    timezone: str
    reference_date: date
    start_local: datetime
    end_local: datetime
    start_utc: datetime
    end_utc: datetime

    @property
    def duration_minutes(self) -> int:
        """Number of minutes in the window (handles DST transitions)."""

        delta = self.end_utc - self.start_utc
        return int(delta.total_seconds() // 60)


LocalDateInput = Union[date, datetime]


def _load_timezone(timezone_str: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_str)
    except ZoneInfoNotFoundError as exc:  # pragma: no cover - defensive guard
        raise TimezoneNotFoundError(f"Unknown timezone: {timezone_str}") from exc


def utc_now() -> datetime:
    """Return the current UTC datetime."""

    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """Return the current UTC time in ISO 8601 format with Z suffix."""

    return utc_now().isoformat().replace("+00:00", "Z")


def utc_today() -> date:
    """Return current UTC calendar day."""

    return utc_now().date()


def ensure_utc(datetime_obj: datetime) -> datetime:
    """Force a datetime into UTC (assumes naive datetimes are UTC)."""

    if datetime_obj.tzinfo is None:
        return datetime_obj.replace(tzinfo=timezone.utc)
    return datetime_obj.astimezone(timezone.utc)


def resolve_timezone(timezone_str: Optional[str], *, default: str = "UTC") -> ZoneInfo:
    """Best-effort conversion from preference value to ZoneInfo instance."""

    candidate = (timezone_str or default).strip() or default
    try:
        return _load_timezone(candidate)
    except TimezoneNotFoundError:
        return _load_timezone(default)


def _coerce_to_local_date(value: LocalDateInput, tz: ZoneInfo) -> date:
    if isinstance(value, datetime):
        return value.astimezone(tz).date()
    return value


def _build_day_window(tz: ZoneInfo, timezone_str: str, local_day: date) -> DayWindow:
    start_local = datetime.combine(local_day, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    return DayWindow(
        timezone=timezone_str,
        reference_date=local_day,
        start_local=start_local,
        end_local=end_local,
        start_utc=start_utc,
        end_utc=end_utc,
    )


def get_day_window(timezone_str: str, reference: LocalDateInput) -> DayWindow:
    """Return the local-day window for ``reference`` in ``timezone_str``.

    ``reference`` may be a date or datetime (aware or naive). Naive datetimes are
    treated as UTC before conversion.
    """

    tz = _load_timezone(timezone_str)
    local_date = _coerce_to_local_date(reference, tz)
    return _build_day_window(tz, timezone_str, local_date)


def get_previous_day_window(timezone_str: str, reference: LocalDateInput) -> DayWindow:
    """Return the window for the day preceding ``reference`` in ``timezone_str``."""

    tz = _load_timezone(timezone_str)
    local_date = _coerce_to_local_date(reference, tz) - timedelta(days=1)
    return _build_day_window(tz, timezone_str, local_date)


def get_next_day_window(timezone_str: str, reference: LocalDateInput) -> DayWindow:
    """Return the window for the day following ``reference`` in ``timezone_str``."""

    tz = _load_timezone(timezone_str)
    local_date = _coerce_to_local_date(reference, tz) + timedelta(days=1)
    return _build_day_window(tz, timezone_str, local_date)


__all__ = [
    "DayWindow",
    "TimezoneNotFoundError",
    "ensure_utc",
    "get_day_window",
    "get_next_day_window",
    "get_previous_day_window",
    "resolve_timezone",
    "utc_now",
    "utc_now_iso",
    "utc_today",
]
