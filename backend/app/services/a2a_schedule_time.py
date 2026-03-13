"""Time normalization and scheduling helpers for A2A schedules."""

from __future__ import annotations

import calendar
from datetime import datetime, time, timedelta, timezone
from typing import Any

from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.services.a2a_schedule_common import A2AScheduleValidationError
from app.utils.timezone_util import ensure_utc, resolve_timezone


class A2AScheduleTimeHelper:
    """Normalize schedule payloads and compute next run timestamps."""

    _schedule_minutes_min = 5
    _schedule_minutes_max = 24 * 60

    _allowed_cycle_types = {
        A2AScheduleTask.CYCLE_DAILY,
        A2AScheduleTask.CYCLE_WEEKLY,
        A2AScheduleTask.CYCLE_MONTHLY,
        A2AScheduleTask.CYCLE_INTERVAL,
        A2AScheduleTask.CYCLE_SEQUENTIAL,
    }
    _allowed_conversation_policies = {
        A2AScheduleTask.POLICY_NEW,
        A2AScheduleTask.POLICY_REUSE,
    }

    @staticmethod
    def normalize_timezone_str(timezone_str: str | None) -> str:
        return (timezone_str or "UTC").strip() or "UTC"

    def normalize_name(self, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise A2AScheduleValidationError("Task name is required")
        if len(normalized) > 120:
            raise A2AScheduleValidationError("Task name must be <= 120 characters")
        return normalized

    def normalize_prompt(self, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise A2AScheduleValidationError("Prompt is required")
        if len(normalized) > 128_000:
            raise A2AScheduleValidationError("Prompt exceeds max length")
        return normalized

    def normalize_cycle_type(self, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in self._allowed_cycle_types:
            raise A2AScheduleValidationError(
                "cycle_type must be one of daily, weekly, monthly, interval, sequential"
            )
        return normalized

    def normalize_conversation_policy(self, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in self._allowed_conversation_policies:
            raise A2AScheduleValidationError(
                "conversation_policy must be one of new_each_run, reuse_single"
            )
        return normalized

    def normalize_time_point(
        self,
        *,
        cycle_type: str,
        time_point: dict[str, Any],
        is_superuser: bool = False,
        timezone_str: str = "UTC",
    ) -> dict[str, Any]:
        del is_superuser

        if not isinstance(time_point, dict):
            raise A2AScheduleValidationError("time_point must be an object")

        if cycle_type == A2AScheduleTask.CYCLE_INTERVAL:
            minutes_raw = time_point.get("minutes", time_point.get("interval_minutes"))
            minutes = self.normalize_schedule_minutes(
                minutes_raw,
                cycle_type="interval",
            )
            interval_start_at_local = self.normalize_interval_start_at_local(
                time_point.get("start_at_local")
            )
            normalized: dict[str, Any] = {"minutes": minutes}
            if interval_start_at_local is not None:
                normalized["start_at_local"] = interval_start_at_local
                normalized["start_at_utc"] = self.to_utc_from_local_iso(
                    interval_start_at_local,
                    timezone_str=timezone_str,
                )
            return normalized
        if cycle_type == A2AScheduleTask.CYCLE_SEQUENTIAL:
            minutes_raw = time_point.get("minutes", time_point.get("interval_minutes"))
            minutes = self.normalize_schedule_minutes(
                minutes_raw,
                cycle_type="sequential",
            )
            if time_point.get("start_at_local") not in (None, "") or time_point.get(
                "start_at_utc"
            ) not in (None, ""):
                raise A2AScheduleValidationError(
                    "sequential does not support start_at_local/start_at_utc; use minutes only"
                )
            return {"minutes": minutes}

        hh, mm = self.parse_hhmm(time_point.get("time"))
        normalized: dict[str, Any] = {"time": f"{hh:02d}:{mm:02d}"}

        if cycle_type == A2AScheduleTask.CYCLE_DAILY:
            return normalized

        if cycle_type == A2AScheduleTask.CYCLE_WEEKLY:
            weekday = self.coerce_int(time_point.get("weekday"))
            if weekday is None or weekday < 1 or weekday > 7:
                raise A2AScheduleValidationError(
                    "weekly time_point requires weekday in range 1..7 (1=Monday, 7=Sunday)"
                )
            normalized["weekday"] = weekday
            return normalized

        if cycle_type == A2AScheduleTask.CYCLE_MONTHLY:
            day = self.coerce_int(time_point.get("day"))
            if day is None or day < 1 or day > 31:
                raise A2AScheduleValidationError(
                    "monthly time_point requires day in range 1..31"
                )
            normalized["day"] = day
            return normalized

        raise A2AScheduleValidationError("Unsupported cycle_type")

    def normalize_schedule_minutes(
        self,
        value: Any,
        *,
        cycle_type: str,
    ) -> int:
        minutes = self.coerce_int(value)
        if minutes is None:
            raise A2AScheduleValidationError(
                f"{cycle_type} time_point requires minutes"
            )
        return max(self._schedule_minutes_min, min(self._schedule_minutes_max, minutes))

    def sanitize_schedule_minutes_for_read(self, value: Any) -> int:
        minutes = self.coerce_int(value)
        if minutes is None:
            return self._schedule_minutes_min
        return max(self._schedule_minutes_min, min(self._schedule_minutes_max, minutes))

    @staticmethod
    def format_local_minute_iso(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M")

    @classmethod
    def normalize_interval_start_at_local(
        cls,
        value: Any,
    ) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            trimmed = value.strip()
            if not trimmed:
                return None
            try:
                dt = datetime.fromisoformat(trimmed)
            except ValueError as exc:
                raise A2AScheduleValidationError(
                    "interval time_point.start_at_local must be a valid ISO datetime"
                ) from exc
            if dt.tzinfo is not None:
                raise A2AScheduleValidationError(
                    "interval time_point.start_at_local must be timezone-naive "
                    "(without Z or offset)"
                )
            return cls.format_local_minute_iso(dt)
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                raise A2AScheduleValidationError(
                    "interval time_point.start_at_local must be timezone-naive "
                    "(without Z or offset)"
                )
            return cls.format_local_minute_iso(value)

        raise A2AScheduleValidationError(
            "interval time_point.start_at_local must be an ISO datetime string"
        )

    @classmethod
    def to_utc_from_local_iso(cls, value: str, *, timezone_str: str) -> str:
        try:
            local_naive = datetime.fromisoformat(value)
        except ValueError as exc:
            raise A2AScheduleValidationError(
                "interval time_point.start_at_local must be a valid ISO datetime"
            ) from exc
        timezone_value = cls.normalize_timezone_str(timezone_str)
        tz = resolve_timezone(timezone_value, default="UTC")
        return ensure_utc(local_naive.replace(tzinfo=tz)).isoformat()

    def format_local_datetime(
        self,
        value: datetime | None,
        *,
        timezone_str: str,
    ) -> str | None:
        if value is None:
            return None
        timezone_value = self.normalize_timezone_str(timezone_str)
        tz = resolve_timezone(timezone_value, default="UTC")
        local_dt = ensure_utc(value).astimezone(tz)
        return self.format_local_minute_iso(local_dt)

    def serialize_time_point_for_response(
        self,
        *,
        cycle_type: str,
        time_point: dict[str, Any] | None,
        timezone_str: str,
    ) -> dict[str, Any]:
        payload = dict(time_point or {})
        if cycle_type == A2AScheduleTask.CYCLE_SEQUENTIAL:
            minutes = self.sanitize_schedule_minutes_for_read(
                payload.get("minutes", payload.get("interval_minutes"))
            )
            return {"minutes": minutes}
        if cycle_type != A2AScheduleTask.CYCLE_INTERVAL:
            return payload

        timezone_value = self.normalize_timezone_str(timezone_str)
        normalized: dict[str, Any] = {
            "minutes": self.sanitize_schedule_minutes_for_read(
                payload.get("minutes", payload.get("interval_minutes"))
            )
        }

        start_at_local = payload.get("start_at_local")
        if isinstance(start_at_local, str) and start_at_local.strip():
            raw_local = start_at_local.strip()
            normalized["start_at_local"] = raw_local
            try:
                normalized_local = self.normalize_interval_start_at_local(raw_local)
            except A2AScheduleValidationError:
                normalized_local = None
            if normalized_local is not None:
                normalized["start_at_local"] = normalized_local
                normalized["start_at_utc"] = self.to_utc_from_local_iso(
                    normalized_local,
                    timezone_str=timezone_value,
                )

        start_at_utc = payload.get("start_at_utc")
        if isinstance(start_at_utc, str) and start_at_utc.strip():
            raw_utc = start_at_utc.strip()
            if "start_at_utc" not in normalized:
                normalized["start_at_utc"] = raw_utc
            if "start_at_local" not in normalized:
                try:
                    start_at_dt = self.resolve_interval_start_at_utc(raw_utc)
                except A2AScheduleValidationError:
                    start_at_dt = None
                if start_at_dt is not None:
                    normalized["start_at_local"] = self.format_local_datetime(
                        start_at_dt,
                        timezone_str=timezone_value,
                    )

        return normalized

    @staticmethod
    def resolve_interval_start_at_utc(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return ensure_utc(value)
        if not isinstance(value, str):
            return None

        trimmed = value.strip()
        if not trimmed:
            return None

        try:
            dt = datetime.fromisoformat(trimmed)
        except ValueError as exc:
            if trimmed.endswith("Z"):
                dt = datetime.fromisoformat(trimmed.replace("Z", "+00:00"))
            else:
                raise A2AScheduleValidationError(
                    "interval time_point.start_at_utc is not a valid ISO datetime"
                ) from exc

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return ensure_utc(dt)

    def compute_sequential_next_run_at(
        self,
        *,
        time_point: dict[str, Any] | None,
        after_utc: datetime,
    ) -> datetime:
        minutes = self.sanitize_schedule_minutes_for_read(
            (time_point or {}).get(
                "minutes", (time_point or {}).get("interval_minutes")
            )
        )
        return ensure_utc(after_utc) + timedelta(minutes=minutes)

    @staticmethod
    def next_interval_candidate(
        *,
        after_utc: datetime,
        interval: timedelta,
        start_at_utc: datetime | None,
        guard_utc: datetime,
    ) -> datetime:
        anchor = ensure_utc(start_at_utc) if start_at_utc else None
        after = ensure_utc(after_utc)
        if anchor is None:
            candidate = after + interval
            if candidate <= guard_utc:
                interval_seconds = max(interval.total_seconds(), 1.0)
                return candidate + timedelta(
                    seconds=(guard_utc - candidate).total_seconds()
                    // interval_seconds
                    * interval_seconds
                    + interval_seconds
                )
            return candidate
        if after < anchor:
            candidate = anchor
        else:
            interval_seconds = max(interval.total_seconds(), 1.0)
            delta_seconds = (after - anchor).total_seconds()
            steps = int((delta_seconds + interval_seconds - 1) // interval_seconds)
            candidate = anchor + timedelta(seconds=steps * interval_seconds)

            if candidate <= guard_utc:
                additional_steps = (
                    int((guard_utc - candidate).total_seconds() // interval_seconds) + 1
                )
                return candidate + timedelta(
                    seconds=additional_steps * interval_seconds
                )
        return candidate

    @staticmethod
    def coerce_int(value: Any) -> int | None:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def parse_hhmm(value: Any) -> tuple[int, int]:
        raw = str(value or "").strip()
        pieces = raw.split(":", 1)
        if len(pieces) != 2:
            raise A2AScheduleValidationError("time_point.time must be HH:MM")
        hour = A2AScheduleTimeHelper.coerce_int(pieces[0])
        minute = A2AScheduleTimeHelper.coerce_int(pieces[1])
        if hour is None or minute is None:
            raise A2AScheduleValidationError("time_point.time must be HH:MM")
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise A2AScheduleValidationError("time_point.time must be HH:MM")
        return hour, minute

    @staticmethod
    def monthly_candidate(
        *,
        year: int,
        month: int,
        day: int,
        hour: int,
        minute: int,
        tz: Any,
    ) -> datetime:
        last_day = calendar.monthrange(year, month)[1]
        resolved_day = min(day, last_day)
        return datetime(year, month, resolved_day, hour, minute, tzinfo=tz)

    @staticmethod
    def resolve_local_wall_clock(candidate_local: datetime) -> datetime:
        if candidate_local.tzinfo is None:
            return candidate_local

        normalized = candidate_local.astimezone(timezone.utc).astimezone(
            candidate_local.tzinfo
        )
        original_wall = (
            candidate_local.year,
            candidate_local.month,
            candidate_local.day,
            candidate_local.hour,
            candidate_local.minute,
            candidate_local.second,
            candidate_local.microsecond,
        )
        normalized_wall = (
            normalized.year,
            normalized.month,
            normalized.day,
            normalized.hour,
            normalized.minute,
            normalized.second,
            normalized.microsecond,
        )
        if normalized_wall != original_wall:
            return normalized.replace(fold=0)

        return candidate_local.replace(fold=0)

    def next_occurrence_local(
        self,
        *,
        cycle_type: str,
        time_point: dict[str, Any],
        after_local: datetime,
        is_superuser: bool = False,
    ) -> datetime:
        del is_superuser

        if cycle_type == A2AScheduleTask.CYCLE_INTERVAL:
            minutes = self.normalize_schedule_minutes(
                time_point.get("minutes", time_point.get("interval_minutes")),
                cycle_type="interval",
            )
            return after_local + timedelta(minutes=minutes)

        hh, mm = self.parse_hhmm(time_point.get("time"))
        target_time = time(hour=hh, minute=mm)

        if cycle_type == A2AScheduleTask.CYCLE_DAILY:
            candidate = datetime.combine(
                after_local.date(),
                target_time,
                tzinfo=after_local.tzinfo,
            )
            candidate = self.resolve_local_wall_clock(candidate)
            if candidate <= after_local:
                candidate = self.resolve_local_wall_clock(candidate + timedelta(days=1))
            return candidate

        if cycle_type == A2AScheduleTask.CYCLE_WEEKLY:
            weekday = self.coerce_int(time_point.get("weekday"))
            if weekday is None or weekday < 1 or weekday > 7:
                raise A2AScheduleValidationError("Invalid weekday")

            delta_days = (weekday - after_local.isoweekday()) % 7
            candidate_date = after_local.date() + timedelta(days=delta_days)
            candidate = datetime.combine(
                candidate_date,
                target_time,
                tzinfo=after_local.tzinfo,
            )
            candidate = self.resolve_local_wall_clock(candidate)
            if candidate <= after_local:
                candidate = self.resolve_local_wall_clock(candidate + timedelta(days=7))
            return candidate

        if cycle_type == A2AScheduleTask.CYCLE_MONTHLY:
            day = self.coerce_int(time_point.get("day"))
            if day is None or day < 1 or day > 31:
                raise A2AScheduleValidationError("Invalid day")

            candidate = self.monthly_candidate(
                year=after_local.year,
                month=after_local.month,
                day=day,
                hour=hh,
                minute=mm,
                tz=after_local.tzinfo,
            )
            candidate = self.resolve_local_wall_clock(candidate)
            if candidate <= after_local:
                if after_local.month == 12:
                    year = after_local.year + 1
                    month = 1
                else:
                    year = after_local.year
                    month = after_local.month + 1

                candidate = self.monthly_candidate(
                    year=year,
                    month=month,
                    day=day,
                    hour=hh,
                    minute=mm,
                    tz=after_local.tzinfo,
                )
                candidate = self.resolve_local_wall_clock(candidate)
            return candidate

        raise A2AScheduleValidationError("Unsupported cycle_type")

    def compute_next_run_at(
        self,
        *,
        cycle_type: str,
        time_point: dict[str, Any],
        timezone_str: str,
        after_utc: datetime,
        not_before_utc: datetime | None = None,
        is_superuser: bool = False,
    ) -> datetime:
        normalized_cycle = self.normalize_cycle_type(cycle_type)
        timezone_value = self.normalize_timezone_str(timezone_str)
        normalized_point = self.normalize_time_point(
            cycle_type=normalized_cycle,
            time_point=time_point,
            is_superuser=is_superuser,
            timezone_str=timezone_value,
        )
        if normalized_cycle == A2AScheduleTask.CYCLE_SEQUENTIAL:
            after = ensure_utc(after_utc)
            guard = ensure_utc(not_before_utc or after_utc)
            baseline = after if after >= guard else guard
            return self.compute_sequential_next_run_at(
                time_point=normalized_point,
                after_utc=baseline,
            )

        if normalized_cycle == A2AScheduleTask.CYCLE_INTERVAL:
            minutes = self.normalize_schedule_minutes(
                normalized_point.get(
                    "minutes", normalized_point.get("interval_minutes")
                ),
                cycle_type="interval",
            )
            interval = timedelta(minutes=minutes)
            after = ensure_utc(after_utc)
            guard = ensure_utc(not_before_utc or after_utc)
            start_at = self.resolve_interval_start_at_utc(
                normalized_point.get("start_at_utc")
            )
            return self.next_interval_candidate(
                after_utc=after,
                interval=interval,
                start_at_utc=start_at,
                guard_utc=guard,
            )

        tz = resolve_timezone(timezone_value, default="UTC")
        after_local = ensure_utc(after_utc).astimezone(tz)
        guard_utc = ensure_utc(not_before_utc or after_utc)

        candidate_local = self.next_occurrence_local(
            cycle_type=normalized_cycle,
            time_point=normalized_point,
            after_local=after_local,
            is_superuser=is_superuser,
        )
        while ensure_utc(candidate_local) <= guard_utc:
            candidate_local = self.next_occurrence_local(
                cycle_type=normalized_cycle,
                time_point=normalized_point,
                after_local=candidate_local,
                is_superuser=is_superuser,
            )

        return candidate_local.astimezone(timezone.utc)
