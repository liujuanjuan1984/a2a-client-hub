"""
Statistics services for aggregating ActualEvent data into daily per-dimension minutes.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import Column, and_, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.actual_event import ActualEvent
from app.db.models.aggregated_dimension_stat import AggregatedDimensionStat
from app.db.models.daily_dimension_stat import DailyDimensionStat
from app.db.models.note import Note
from app.db.models.person import Person
from app.db.models.tag import Tag
from app.db.models.tag_associations import tag_associations
from app.db.models.user_preference import UserPreference
from app.db.models.vision import Vision
from app.db.session import AsyncSessionLocal
from app.db.transaction import commit_safely
from app.schemas.stats import (
    AggregatedDimensionStatResponse,
    AggregationGranularity,
    DailyDimensionStatResponse,
    TagUsageStatResponse,
)
from app.utils.timezone_util import (
    DayWindow,
    TimezoneNotFoundError,
    ensure_utc,
    get_day_window,
    utc_now,
)

logger = get_logger(__name__)

_FALLBACK_RECOMPUTE_CACHE: Dict[Tuple[UUID, str], datetime] = {}
_FALLBACK_TTL = timedelta(minutes=15)


def _iter_local_days(
    start: datetime, end: datetime, tzinfo: ZoneInfo
) -> Iterable[date]:
    start_local = ensure_utc(start).astimezone(tzinfo)
    end_local = (ensure_utc(end) - timedelta(microseconds=1)).astimezone(tzinfo)
    current = start_local.date()
    last = end_local.date()
    while current <= last:
        yield current
        current = current + timedelta(days=1)


async def _get_user_timezones(db: AsyncSession, user_id: UUID) -> Set[str]:
    stmt = (
        select(UserPreference.value)
        .where(
            UserPreference.user_id == user_id,
            UserPreference.key == "system.timezone",
            UserPreference.deleted_at.is_(None),
        )
        .limit(1)
    )
    value = await db.scalar(stmt)
    if isinstance(value, str) and value:
        return {value}
    return {"UTC"}


async def compute_timezone_day_dimension_minutes(
    db: AsyncSession, local_day: date, timezone_str: str, user_id: UUID
) -> Dict[UUID, int]:
    """Compute per-dimension minutes for a local calendar day using an IANA timezone."""

    try:
        window: DayWindow = get_day_window(timezone_str, local_day)
    except TimezoneNotFoundError:
        # Fall back to UTC if timezone invalid
        window = get_day_window("UTC", local_day)

    stmt = (
        select(ActualEvent)
        .where(ActualEvent.user_id == user_id)
        .where(ActualEvent.deleted_at.is_(None))
        .where(ActualEvent.start_time < window.end_utc)
        .where(ActualEvent.end_time > window.start_utc)
    )
    events = (await db.execute(stmt)).scalars().all()

    totals: Dict[UUID, int] = {}
    for ev in events:
        ev_start = ev.start_time
        ev_end = ev.end_time  # type: ignore[assignment]
        if ev_end is None:
            continue
        # Skip events without dimension_id to avoid null constraint violations
        if ev.dimension_id is None:
            continue
        overlap_start = max(ev_start, window.start_utc)
        overlap_end = min(ev_end, window.end_utc)
        if overlap_end <= overlap_start:
            continue
        minutes = int((overlap_end - overlap_start).total_seconds() // 60)
        if minutes <= 0:
            continue
        totals[ev.dimension_id] = totals.get(ev.dimension_id, 0) + minutes

    return totals


async def collect_daily_dimension_stats(
    db: AsyncSession,
    *,
    user_id: UUID,
    timezone: str,
    start: date,
    end: date,
    dimension_ids: Optional[List[str]] = None,
) -> Tuple[List[DailyDimensionStatResponse], List[date], str]:
    """Fetch cached daily stats and compute fallbacks for missing days."""

    requested_days: List[date] = []
    cursor = start
    while cursor <= end:
        requested_days.append(cursor)
        cursor = date.fromordinal(cursor.toordinal() + 1)

    dimension_filter = set(dimension_ids) if dimension_ids else None

    stmt = (
        select(DailyDimensionStat)
        .where(
            DailyDimensionStat.user_id == user_id,
            DailyDimensionStat.stat_date >= start,
            DailyDimensionStat.stat_date <= end,
            DailyDimensionStat.timezone == timezone,
        )
        .order_by(
            DailyDimensionStat.stat_date.asc(),
            DailyDimensionStat.dimension_id.asc(),
        )
    )
    if dimension_ids:
        stmt = stmt.where(DailyDimensionStat.dimension_id.in_(dimension_ids))

    rows = (await db.execute(stmt)).scalars().all()

    responses: List[DailyDimensionStatResponse] = []
    existing_by_day: Dict[date, List[DailyDimensionStatResponse]] = {}
    for record in rows:
        response_item = DailyDimensionStatResponse(
            date=record.stat_date.isoformat(),
            dimension_id=record.dimension_id,
            minutes=record.minutes,
        )
        responses.append(response_item)
        existing_by_day.setdefault(record.stat_date, []).append(response_item)

    missing_days = [d for d in requested_days if d not in existing_by_day]

    effective_timezone = timezone
    if missing_days:
        fallback_results: List[DailyDimensionStatResponse] = []
        for missing in missing_days:
            try:
                totals = await compute_timezone_day_dimension_minutes(
                    db, missing, timezone, user_id=user_id
                )
            except TimezoneNotFoundError:
                effective_timezone = "UTC"
                totals = await compute_timezone_day_dimension_minutes(
                    db, missing, "UTC", user_id=user_id
                )

            for dim_id, minutes in totals.items():
                if dimension_filter and dim_id not in dimension_filter:
                    continue
                fallback_results.append(
                    DailyDimensionStatResponse(
                        date=missing.isoformat(),
                        dimension_id=dim_id,
                        minutes=minutes,
                    )
                )

        if fallback_results:
            logger.info(
                "stats.daily_dimensions.fallback",
                extra={
                    "user_id": str(user_id),
                    "timezone": timezone,
                    "effective_timezone": effective_timezone,
                    "days": [d.isoformat() for d in missing_days],
                    "dimensions": dimension_ids or "all",
                },
            )
            responses.extend(fallback_results)

    responses.sort(key=lambda item: (item.date, item.dimension_id))
    return responses, missing_days, effective_timezone


async def _recompute_daily_stats_background(
    day_strings: Sequence[str], timezone_name: str, user_id: UUID
) -> None:
    days = [date.fromisoformat(day_str) for day_str in day_strings]
    try:
        async with AsyncSessionLocal() as session:
            await recompute_daily_stats_for_dates_timezone(
                session, days, timezone_name, user_id=user_id
            )
    except Exception:  # pragma: no cover - defensive safeguard
        logger.exception(
            "Failed to recompute daily stats in background",
            extra={
                "user_id": str(user_id),
                "timezone": timezone_name,
                "days": list(day_strings),
            },
        )


def schedule_recompute_missing_days(
    *,
    missing_days: Sequence[date],
    timezone_name: str,
    user_id: UUID,
    now: Optional[datetime] = None,
) -> None:
    """Enqueue a background recompute if cache TTL allows."""

    if not missing_days:
        return

    reference_time = now or utc_now()
    cache_key = (user_id, timezone_name)
    last_triggered = _FALLBACK_RECOMPUTE_CACHE.get(cache_key)
    if last_triggered and reference_time - last_triggered < _FALLBACK_TTL:
        return

    _FALLBACK_RECOMPUTE_CACHE[cache_key] = reference_time
    day_strings = [day.isoformat() for day in missing_days]

    async def _runner() -> None:
        await _recompute_daily_stats_background(day_strings, timezone_name, user_id)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_runner())
    else:
        loop.create_task(_runner())


async def fetch_cached_aggregated_stats(
    db: AsyncSession,
    *,
    user_id: UUID,
    granularity: AggregationGranularity,
    timezone: str,
    calendar_system: str,
    first_day_of_week: int,
    start: date,
    end: date,
) -> List[AggregatedDimensionStat]:
    """Return persisted aggregated stats overlapping the requested window."""

    granularity_value = (
        granularity.value
        if isinstance(granularity, AggregationGranularity)
        else granularity
    )

    stmt = (
        select(AggregatedDimensionStat)
        .where(AggregatedDimensionStat.user_id == user_id)
        .where(AggregatedDimensionStat.granularity == granularity_value)
        .where(AggregatedDimensionStat.timezone == timezone)
        .where(AggregatedDimensionStat.calendar_system == calendar_system)
        .where(AggregatedDimensionStat.period_start <= end)
        .where(AggregatedDimensionStat.period_end >= start)
        .order_by(
            AggregatedDimensionStat.period_start.asc(),
            AggregatedDimensionStat.dimension_id.asc(),
        )
    )

    if granularity == AggregationGranularity.week:
        stmt = stmt.where(
            AggregatedDimensionStat.first_day_of_week == first_day_of_week
        )
    else:
        stmt = stmt.where(AggregatedDimensionStat.first_day_of_week == 0)

    return (await db.execute(stmt)).scalars().all()


async def upsert_aggregated_dimension_stats(
    db: AsyncSession,
    *,
    user_id: UUID,
    timezone: str,
    calendar_system: str,
    first_day_of_week: int,
    granularity: AggregationGranularity,
    rows: List[AggregatedDimensionStatResponse],
) -> None:
    """Persist aggregated rows with upsert semantics."""

    if not rows or granularity == AggregationGranularity.day:
        return

    first_day_value = (
        first_day_of_week if granularity == AggregationGranularity.week else 0
    )

    values: List[Dict[str, Any]] = []
    for row in rows:
        granularity_value = (
            row.granularity.value
            if isinstance(row.granularity, AggregationGranularity)
            else row.granularity
        )
        values.append(
            {
                "id": uuid4(),
                "user_id": user_id,
                "granularity": granularity_value,
                "period_start": date.fromisoformat(row.period_start),
                "period_end": date.fromisoformat(row.period_end),
                "timezone": timezone,
                "calendar_system": calendar_system,
                "first_day_of_week": first_day_value,
                "dimension_id": row.dimension_id,
                "minutes": row.minutes,
            }
        )

    if not values:
        return

    stmt = pg_insert(AggregatedDimensionStat).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            AggregatedDimensionStat.user_id,
            AggregatedDimensionStat.granularity,
            AggregatedDimensionStat.timezone,
            AggregatedDimensionStat.calendar_system,
            AggregatedDimensionStat.first_day_of_week,
            AggregatedDimensionStat.period_start,
            AggregatedDimensionStat.period_end,
            AggregatedDimensionStat.dimension_id,
        ],
        set_={
            "minutes": stmt.excluded.minutes,
            "updated_at": func.now(),
        },
    )

    await db.execute(stmt)
    await commit_safely(db)


async def recompute_daily_stats_for_dates_timezone(
    db: AsyncSession, days_local: Iterable[date], timezone_str: str, user_id: UUID
) -> None:
    """Recompute stats for given LOCAL dates within the specified timezone."""

    day_list = sorted({d for d in days_local})
    if not day_list:
        return

    delete_daily_stmt = delete(DailyDimensionStat).where(
        DailyDimensionStat.user_id == user_id,
        DailyDimensionStat.timezone == timezone_str,
        DailyDimensionStat.stat_date.in_(day_list),
    )
    await db.execute(delete_daily_stmt)

    min_day = day_list[0]
    max_day = day_list[-1]
    delete_agg_stmt = delete(AggregatedDimensionStat).where(
        AggregatedDimensionStat.user_id == user_id,
        AggregatedDimensionStat.timezone == timezone_str,
        AggregatedDimensionStat.period_start <= max_day,
        AggregatedDimensionStat.period_end >= min_day,
    )
    await db.execute(delete_agg_stmt)

    for day in day_list:
        totals = await compute_timezone_day_dimension_minutes(
            db, day, timezone_str, user_id=user_id
        )
        for dim_id, minutes in totals.items():
            db.add(
                DailyDimensionStat(
                    stat_date=day,
                    dimension_id=dim_id,
                    timezone=timezone_str,
                    minutes=minutes,
                    user_id=user_id,
                )
            )

    await commit_safely(db)


async def recompute_daily_stats_for_event(
    db: AsyncSession, event: ActualEvent, user_id: UUID
) -> None:
    """Recompute stats for all timezones affected by a single event."""

    # end_time is now always required, no need to check for None

    timezones = await _get_user_timezones(db, user_id)
    for tz_name in timezones:
        try:
            tzinfo = ZoneInfo(tz_name)
        except Exception:
            tzinfo = ZoneInfo("UTC")
        local_days = list(_iter_local_days(event.start_time, event.end_time, tzinfo))
        if not local_days:
            continue
        await recompute_daily_stats_for_dates_timezone(
            db, local_days, tz_name, user_id=user_id
        )


# Business Exceptions
class InvalidEntityTypeError(Exception):
    """Raised when an invalid entity type is provided."""


class StatsComputationError(Exception):
    """Raised when statistics computation fails."""


# Tag Usage Statistics Functions
async def get_tag_usage_by_entity_type(
    db: AsyncSession, *, user_id: Union[UUID, Column], entity_type: str
) -> Dict[str, Any]:
    """Get tag usage statistics for a specific entity type.

    Args:
        db: Database session
        user_id: User ID
        entity_type: The entity type (person, note, vision)

    Returns:
        Dictionary containing tag usage statistics for the specified entity type

    Raises:
        InvalidEntityTypeError: If entity_type is not valid
        StatsComputationError: If computation fails
    """
    # Validate entity_type parameter
    valid_types = {"person", "note", "vision"}
    if entity_type not in valid_types:
        raise InvalidEntityTypeError(
            f"Invalid entity_type. Must be one of: {', '.join(valid_types)}"
        )

    def _base_query():
        return (
            select(
                Tag.id,
                Tag.name,
                func.count(tag_associations.c.entity_id).label("usage_count"),
            )
            .select_from(Tag)
            .join(tag_associations, Tag.id == tag_associations.c.tag_id)
            .where(Tag.user_id == user_id)
            .where(Tag.deleted_at.is_(None))
            .group_by(Tag.id, Tag.name)
            .order_by(Tag.name)
        )

    try:
        if entity_type == "person":
            stmt = (
                _base_query()
                .join(
                    Person,
                    and_(
                        Person.id == tag_associations.c.entity_id,
                        tag_associations.c.entity_type == "person",
                    ),
                )
                .where(tag_associations.c.entity_type == "person")
                .where(Tag.entity_type == "person")
                .where(Person.deleted_at.is_(None))
                .where(Person.user_id == user_id)
            )
        elif entity_type == "note":
            stmt = (
                _base_query()
                .join(
                    Note,
                    and_(
                        Note.id == tag_associations.c.entity_id,
                        tag_associations.c.entity_type == "note",
                    ),
                )
                .where(tag_associations.c.entity_type == "note")
                .where(Tag.entity_type == "note")
                .where(Note.deleted_at.is_(None))
                .where(Note.user_id == user_id)
            )
        elif entity_type == "vision":
            stmt = (
                _base_query()
                .join(
                    Vision,
                    and_(
                        Vision.id == tag_associations.c.entity_id,
                        tag_associations.c.entity_type == "vision",
                    ),
                )
                .where(tag_associations.c.entity_type == "vision")
                .where(Tag.entity_type == "vision")
                .where(Vision.deleted_at.is_(None))
                .where(Vision.user_id == user_id)
            )
        else:
            stmt = _base_query()

        tag_stats_result = (await db.execute(stmt)).all()
        tag_stats = [
            TagUsageStatResponse(id=row.id, name=row.name, usage_count=row.usage_count)
            for row in tag_stats_result
        ]

        return {
            "entity_type": entity_type,
            "tag_stats": tag_stats,
            "total_tags": len(tag_stats),
        }

    except Exception as exc:  # pragma: no cover - defensive
        raise StatsComputationError(
            f"Failed to get tag usage statistics for {entity_type}: {str(exc)}"
        )
