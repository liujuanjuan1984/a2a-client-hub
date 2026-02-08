#!/usr/bin/env python
"""Bulk recompute helper for task effort totals and timelog statistics.

This script iterates through all active users, re-schedules work recalculation
jobs for every task and vision, processes them inline, and then recomputes the
daily timelog statistics across the full extent of recorded actual events.

Usage:
    python scripts/bulk_recompute_work.py

The script assumes the backend virtual environment is active and environment
variables (e.g., database URL) are already configured.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError


def _bootstrap_environment() -> None:
    """Ensure repository paths and .env files are loaded before importing app code."""
    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent
    backend_dir = repo_root / "backend"

    for path in (repo_root, backend_dir):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    env_candidates = [
        repo_root / ".env",
        backend_dir / ".env",
    ]
    for env_path in env_candidates:
        if env_path.exists():
            load_dotenv(env_path, override=False)


_bootstrap_environment()

from app.core.constants import USER_PREFERENCE_DEFAULTS
from app.db.models.actual_event import ActualEvent
from app.db.models.daily_dimension_stat import DailyDimensionStat
from app.db.models.task import Task
from app.db.models.user import User
from app.db.models.user_preference import UserPreference
from app.db.models.vision import Vision
from app.db.models.work_recalc_job import WorkRecalcJob
from app.db.session import AsyncSessionLocal, SessionLocal
from app.handlers.metrics.stats import (
    recompute_daily_stats_for_dates_timezone,
    upsert_aggregated_dimension_stats,
)
from app.schemas.stats import AggregatedDimensionStatResponse, AggregationGranularity
from app.services import work_recalc
from app.utils.calendar_adapter import get_calendar_adapter

logger = logging.getLogger("bulk_recompute_work")


async def _recompute_days(
    days: List[date], timezone_name: str, user_id: UUID
) -> None:
    async with AsyncSessionLocal() as async_session:
        await recompute_daily_stats_for_dates_timezone(
            async_session,
            days_local=days,
            timezone_str=timezone_name,
            user_id=user_id,
        )


def _run_recompute_days(days: List[date], timezone_name: str, user_id: UUID) -> None:
    asyncio.run(_recompute_days(days, timezone_name, user_id))


async def _upsert_aggregated(
    *,
    user_id: UUID,
    timezone: str,
    calendar_system: str,
    first_day_of_week: int,
    granularity: AggregationGranularity,
    rows: List[AggregatedDimensionStatResponse],
) -> None:
    async with AsyncSessionLocal() as async_session:
        await upsert_aggregated_dimension_stats(
            async_session,
            user_id=user_id,
            timezone=timezone,
            calendar_system=calendar_system,
            first_day_of_week=first_day_of_week,
            granularity=granularity,
            rows=rows,
        )


def _run_upsert_aggregated(
    *,
    user_id: UUID,
    timezone: str,
    calendar_system: str,
    first_day_of_week: int,
    granularity: AggregationGranularity,
    rows: List[AggregatedDimensionStatResponse],
) -> None:
    asyncio.run(
        _upsert_aggregated(
            user_id=user_id,
            timezone=timezone,
            calendar_system=calendar_system,
            first_day_of_week=first_day_of_week,
            granularity=granularity,
            rows=rows,
        )
    )


async def _schedule_work_recalc_jobs(
    *,
    user_id: UUID,
    task_ids: Sequence[UUID],
    vision_ids: Sequence[UUID],
    reason: str,
) -> None:
    async with AsyncSessionLocal() as async_session:
        await work_recalc.schedule_recalc_jobs(
            async_session,
            user_id=user_id,
            task_ids=task_ids,
            vision_ids=vision_ids,
            reason=reason,
            background_tasks=None,
        )


def _iter_local_days(timezone_name: str, start_utc, end_utc) -> Iterator:
    """Yield each local calendar day touched by the UTC window."""
    from zoneinfo import ZoneInfo

    try:
        tzinfo = ZoneInfo(timezone_name)
    except Exception:
        tzinfo = ZoneInfo("UTC")

    current_day = start_utc.astimezone(tzinfo).date()
    last_inclusive = (end_utc - timedelta(microseconds=1)).astimezone(tzinfo).date()

    while current_day <= last_inclusive:
        yield current_day
        current_day = current_day + timedelta(days=1)


def _get_preference_value(session, user_id, key):
    preference = (
        session.query(UserPreference)
        .filter(
            UserPreference.user_id == user_id,
            UserPreference.key == key,
            UserPreference.deleted_at.is_(None),
        )
        .first()
    )
    return preference.value if preference else None


def _resolve_timezone(session, user_id) -> str:
    """Return preferred timezone; fall back to UTC."""
    value = _get_preference_value(session, user_id, "system.timezone")
    if isinstance(value, str) and value.strip():
        return value
    default_timezone = USER_PREFERENCE_DEFAULTS.get("system.timezone", {}).get(
        "value", "UTC"
    )
    return default_timezone


def _resolve_calendar_preferences(session, user_id) -> tuple[str, int]:
    """Return (calendar_system, first_day_of_week) with defaults applied."""
    default_calendar = USER_PREFERENCE_DEFAULTS["calendar.system"]["value"]
    calendar_value = _get_preference_value(session, user_id, "calendar.system")
    if not isinstance(calendar_value, str):
        calendar_value = default_calendar
    allowed_calendars = USER_PREFERENCE_DEFAULTS["calendar.system"]["allowed_values"]
    if allowed_calendars and calendar_value not in allowed_calendars:
        calendar_value = default_calendar

    default_first_day = USER_PREFERENCE_DEFAULTS["calendar.first_day_of_week"]["value"]
    first_day_value = _get_preference_value(session, user_id, "calendar.first_day_of_week")
    try:
        first_day = int(first_day_value)
    except (TypeError, ValueError):
        first_day = default_first_day
    allowed_days = USER_PREFERENCE_DEFAULTS["calendar.first_day_of_week"][
        "allowed_values"
    ]
    if allowed_days and first_day not in allowed_days:
        first_day = default_first_day

    return calendar_value, first_day


def _load_task_ids(session, user_id) -> list:
    """Fetch all active task IDs for the user."""
    rows = (
        Task.active(session, user_id=user_id)
        .with_entities(Task.id)
        .all()
    )
    return [row.id for row in rows]


def _load_vision_ids(session, user_id) -> list:
    """Fetch all active vision IDs for the user."""
    rows = (
        Vision.active(session, user_id=user_id)
        .with_entities(Vision.id)
        .all()
    )
    return [row.id for row in rows]


def _fetch_time_bounds(session, user_id):
    """Return earliest start and latest end timestamps for actual events."""
    return (
        session.query(
            func.min(ActualEvent.start_time),
            func.max(ActualEvent.end_time),
        )
        .filter(
            ActualEvent.user_id == user_id,
            ActualEvent.deleted_at.is_(None),
        )
        .one()
    )


def _recompute_user(session, user: User) -> None:
    """Run effort and timelog recomputation flow for a single user."""
    logger.info("Recomputing data for user=%s", user.id)
    task_ids = _load_task_ids(session, user.id)
    vision_ids = _load_vision_ids(session, user.id)

    if not task_ids and not vision_ids:
        logger.info("User %s has no active tasks or visions; skipping jobs", user.id)
    else:
        asyncio.run(
            _schedule_work_recalc_jobs(
                user_id=user.id,
                task_ids=task_ids,
                vision_ids=vision_ids,
                reason="bulk-recalc",
            )
        )

    min_start, max_end = _fetch_time_bounds(session, user.id)
    if not min_start or not max_end:
        logger.info("User %s has no actual events; skipping timelog recompute", user.id)
        return

    timezone_name = _resolve_timezone(session, user.id)
    days = list(_iter_local_days(timezone_name, min_start, max_end))
    if not days:
        logger.info("User %s has empty day range after timezone conversion", user.id)
        return

    _run_recompute_days(days, timezone_name, user.id)
    session.expire_all()
    logger.info(
        "Recomputed %d days of timelog stats for user=%s timezone=%s",
        len(days),
        user.id,
        timezone_name,
    )

    calendar_system, first_day_of_week = _resolve_calendar_preferences(
        session, user.id
    )
    min_day: date = min(days)
    max_day: date = max(days)
    daily_rows: Sequence[DailyDimensionStat] = (
        session.query(DailyDimensionStat)
        .filter(
            DailyDimensionStat.user_id == user.id,
            DailyDimensionStat.timezone == timezone_name,
            DailyDimensionStat.stat_date >= min_day,
            DailyDimensionStat.stat_date <= max_day,
        )
        .all()
    )
    if not daily_rows:
        logger.info(
            "User %s has no daily_stat rows for timezone=%s after recompute",
            user.id,
            timezone_name,
        )
        return

    def _aggregate(
        records: Sequence[DailyDimensionStat],
        granularity: AggregationGranularity,
    ) -> List[AggregatedDimensionStatResponse]:
        adapter = get_calendar_adapter(calendar_system)
        buckets = {}
        for record in records:
            if record.minutes is None or record.dimension_id is None:
                continue
            day = record.stat_date
            if granularity == AggregationGranularity.day:
                period_start = day
                period_end = day
            elif granularity == AggregationGranularity.week:
                period_start, period_end = adapter.week_range(day, first_day_of_week)
            elif granularity == AggregationGranularity.month:
                period_start, period_end = adapter.month_range(day)
            elif granularity == AggregationGranularity.year:
                period_start, period_end = adapter.year_range(day)
            else:  # defensive fallback
                period_start = day
                period_end = day
            key = (period_start, period_end, record.dimension_id)
            buckets[key] = buckets.get(key, 0) + record.minutes

        ordered = sorted(buckets.items(), key=lambda item: (item[0][0], item[0][2]))
        return [
            AggregatedDimensionStatResponse(
                granularity=granularity,
                period_start=period_start.isoformat(),
                period_end=period_end.isoformat(),
                dimension_id=dimension_id,
                minutes=minutes,
            )
            for (period_start, period_end, dimension_id), minutes in ordered
        ]

    for granularity in (
        AggregationGranularity.week,
        AggregationGranularity.month,
        AggregationGranularity.year,
    ):
        aggregated_rows = _aggregate(daily_rows, granularity)
        if not aggregated_rows:
            logger.info(
                "No %s aggregated rows for user=%s timezone=%s",
                granularity.value,
                user.id,
                timezone_name,
            )
            continue

        _run_upsert_aggregated(
            user_id=user.id,
            timezone=timezone_name,
            calendar_system=calendar_system,
            first_day_of_week=first_day_of_week,
            granularity=granularity,
            rows=aggregated_rows,
        )
        logger.info(
                "Upserted %d %s aggregated buckets for user=%s timezone=%s",
                len(aggregated_rows),
                granularity.value,
                user.id,
            timezone_name,
        )


def iter_active_users(session) -> Iterable[User]:
    """Return a stable list of active users.

    Streaming with yield_per would keep a server-side cursor open. Once we
    commit within the loop (which happens frequently), the cursor becomes
    invalid and SQLAlchemy raises ProgrammingError. Fetch into memory first.
    """
    return (
        session.query(User)
        .filter(User.deleted_at.is_(None))
        .order_by(User.created_at.asc())
        .all()
    )


def _log_job_status(session, *, label: str) -> None:
    """Log current work_recalc_jobs status distribution."""
    rows = (
        session.query(
            WorkRecalcJob.status,
            func.count(WorkRecalcJob.id),
        )
        .group_by(WorkRecalcJob.status)
        .all()
    )
    summary = {status or "unknown": count for status, count in rows}
    logger.info("[%s] work_recalc_jobs status snapshot: %s", label, summary or {})

    problematic = {
        status: count
        for status, count in summary.items()
        if status
        not in (
            WorkRecalcJob.STATUS_PENDING,
            WorkRecalcJob.STATUS_PROCESSING,
            WorkRecalcJob.STATUS_DONE,
        )
    }
    if problematic:
        logger.warning(
            "[%s] Detected unexpected job statuses needing attention: %s",
            label,
            problematic,
        )
    if label.lower() == "after":
        failed_count = summary.get(WorkRecalcJob.STATUS_FAILED, 0)
        processing_count = summary.get(WorkRecalcJob.STATUS_PROCESSING, 0)
        if failed_count or processing_count:
            logger.warning(
                "[%s] Remaining jobs still not finished: processing=%d, failed=%d. "
                "Inspect work_recalc_jobs.reason for details.",
                label,
                processing_count,
                failed_count,
            )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    with contextlib.closing(SessionLocal()) as session:
        _log_job_status(session, label="before")

        for user in iter_active_users(session):
            try:
                _recompute_user(session, user)
            except SQLAlchemyError:
                session.rollback()
                logger.exception("SQL error while recomputing user %s", user.id)
            except Exception:
                session.rollback()
                logger.exception("Unexpected error while recomputing user %s", user.id)

        _log_job_status(session, label="after")


if __name__ == "__main__":
    main()
