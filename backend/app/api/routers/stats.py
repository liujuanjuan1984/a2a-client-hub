"""
Statistics API Router

Provides endpoints to query and recompute daily per-dimension minutes.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.config import settings
from app.core.constants import CALENDAR_SYSTEM_OPTIONS, USER_PREFERENCE_DEFAULTS
from app.core.logging import get_logger
from app.db.models.user import User
from app.handlers import user_preferences as user_preferences_service
from app.handlers.metrics import stats as stats_service
from app.handlers.metrics.stats import InvalidEntityTypeError, StatsComputationError
from app.schemas.stats import (
    AggregatedDimensionStatListResponse,
    AggregatedDimensionStatResponse,
    AggregationGranularity,
    DailyDimensionStatListResponse,
    DailyDimensionStatResponse,
    DayBreakdownListResponse,
    DayBreakdownResponse,
    RecomputeResponse,
    TagUsageStatsResponse,
)
from app.utils.calendar_adapter import get_calendar_adapter

router = StrictAPIRouter(
    prefix="/stats",
    tags=["stats"],
    responses={404: {"description": "Not found"}},
    dependencies=[Depends(get_current_user)],
)

logger = get_logger(__name__)


def _expected_periods_for_range(
    *,
    start: date,
    end: date,
    granularity: AggregationGranularity,
    first_day_of_week: int,
    calendar_system: str,
) -> List[Tuple[date, date]]:
    adapter = get_calendar_adapter(calendar_system)
    periods: Dict[Tuple[date, date], None] = {}
    cursor = start
    while cursor <= end:
        if granularity == AggregationGranularity.day:
            period_start = cursor
            period_end = cursor
        elif granularity == AggregationGranularity.week:
            period_start, period_end = adapter.week_range(cursor, first_day_of_week)
        elif granularity == AggregationGranularity.month:
            period_start, period_end = adapter.month_range(cursor)
        elif granularity == AggregationGranularity.year:
            period_start, period_end = adapter.year_range(cursor)
        else:  # pragma: no cover - safety fallback
            period_start = cursor
            period_end = cursor

        periods.setdefault((period_start, period_end), None)
        cursor = date.fromordinal(cursor.toordinal() + 1)

    return sorted(periods.keys(), key=lambda item: (item[0], item[1]))


def _missing_periods(
    expected_periods: List[Tuple[date, date]],
    cached_rows: Iterable[Any],
) -> List[Tuple[date, date]]:
    existing = {(row.period_start, row.period_end) for row in cached_rows}
    return [period for period in expected_periods if period not in existing]


@router.get("/daily-dimensions", response_model=DailyDimensionStatListResponse)
async def get_daily_dimensions(
    start: date = Query(
        ..., description="Start date (local-day in given timezone) inclusive"
    ),
    end: date = Query(
        ..., description="End date (local-day in given timezone) inclusive"
    ),
    timezone: str = Query(
        ..., description="Timezone identifier (IANA, e.g. 'Asia/Shanghai')"
    ),
    dimension_ids: List[str]
    | None = Query(None, description="Optional filter for dimension IDs"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> DailyDimensionStatListResponse:
    """Return minutes per day per dimension within [start, end] for the specified timezone offset."""

    (
        rows,
        missing_days,
        effective_timezone,
    ) = await stats_service.collect_daily_dimension_stats(
        db,
        user_id=current_user.id,
        timezone=timezone,
        start=start,
        end=end,
        dimension_ids=dimension_ids,
    )

    stats_service.schedule_recompute_missing_days(
        missing_days=missing_days,
        timezone_name=effective_timezone,
        user_id=current_user.id,
    )

    total = len(rows)
    pages = 1 if total > 0 else 0
    return DailyDimensionStatListResponse(
        items=rows,
        pagination={
            "page": 1,
            "size": total,
            "total": total,
            "pages": pages,
        },
        meta={
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": effective_timezone,
            "dimension_ids": dimension_ids,
        },
    )


def _normalize_calendar_value(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    value = raw.strip()
    # handle json-encoded strings like "\"mayan_13_moon\""
    if value.startswith('"') and value.endswith('"'):
        value = value.strip('"')
    return value


async def _get_user_calendar_system(db: AsyncSession, user_id: UUID) -> str:
    preference = await user_preferences_service.get_preference_value(
        db,
        user_id=user_id,
        key="calendar.system",
        default=USER_PREFERENCE_DEFAULTS["calendar.system"]["value"],
    )
    if isinstance(preference, str):
        value = _normalize_calendar_value(preference)
        if value in CALENDAR_SYSTEM_OPTIONS:
            return value
    return USER_PREFERENCE_DEFAULTS["calendar.system"]["value"]


async def _resolve_calendar_system(
    db: AsyncSession, user_id: UUID, override: Optional[str]
) -> str:
    if override:
        normalized = _normalize_calendar_value(override)
        if normalized not in CALENDAR_SYSTEM_OPTIONS:
            raise HTTPException(status_code=400, detail="Invalid calendar_system")
        return normalized
    return await _get_user_calendar_system(db, user_id)


def _aggregate_daily_dimension_stats(
    rows: Iterable[DailyDimensionStatResponse],
    *,
    granularity: AggregationGranularity,
    first_day_of_week: int,
    calendar_system: str,
) -> List[AggregatedDimensionStatResponse]:
    buckets: Dict[tuple[date, date, UUID], int] = {}
    adapter = get_calendar_adapter(calendar_system)

    for row in rows:
        day = date.fromisoformat(row.date)

        if granularity == AggregationGranularity.day:
            period_start = day
            period_end = day
        elif granularity == AggregationGranularity.week:
            period_start, period_end = adapter.week_range(day, first_day_of_week)
        elif granularity == AggregationGranularity.month:
            period_start, period_end = adapter.month_range(day)
        elif granularity == AggregationGranularity.year:
            period_start, period_end = adapter.year_range(day)
        else:  # pragma: no cover - defensive fallback
            period_start = day
            period_end = day

        key = (period_start, period_end, row.dimension_id)
        buckets[key] = buckets.get(key, 0) + row.minutes

    ordered_keys = sorted(buckets.keys(), key=lambda item: (item[0], item[2]))

    return [
        AggregatedDimensionStatResponse(
            granularity=granularity,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            dimension_id=dimension_id,
            minutes=buckets[(period_start, period_end, dimension_id)],
        )
        for period_start, period_end, dimension_id in ordered_keys
    ]


@router.get(
    "/aggregated-dimensions",
    response_model=AggregatedDimensionStatListResponse,
)
async def get_aggregated_dimensions(
    granularity: AggregationGranularity = Query(
        ..., description="Aggregation granularity (day/week/month/year)"
    ),
    start: date = Query(
        ..., description="Start date (local-day in given timezone) inclusive"
    ),
    end: date = Query(
        ..., description="End date (local-day in given timezone) inclusive"
    ),
    timezone: str = Query(
        ..., description="Timezone identifier (IANA, e.g. 'Asia/Shanghai')"
    ),
    dimension_ids: List[str]
    | None = Query(None, description="Optional filter for dimension IDs"),
    first_day_of_week: int = Query(
        1,
        ge=1,
        le=7,
        description="First day of the week (1=Monday ... 7=Sunday)",
    ),
    calendar_system: Optional[str] = Query(
        None,
        description="Calendar system override (gregorian, mayan_13_moon)",
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> AggregatedDimensionStatListResponse:
    """Return aggregated minutes per dimension using the requested granularity."""

    if end < start:
        raise HTTPException(status_code=400, detail="end must be >= start")

    dimension_filter: Optional[Set[UUID]] = None
    if dimension_ids:
        try:
            dimension_filter = {UUID(value) for value in dimension_ids}
        except ValueError as exc:  # pragma: no cover - defensive
            raise HTTPException(
                status_code=400, detail="Invalid dimension_ids"
            ) from exc

    resolved_calendar_system = await _resolve_calendar_system(
        db,
        user_id=current_user.id,
        override=calendar_system,
    )

    if granularity == AggregationGranularity.day:
        (
            daily_rows,
            missing_days,
            effective_timezone,
        ) = await stats_service.collect_daily_dimension_stats(
            db,
            user_id=current_user.id,
            timezone=timezone,
            start=start,
            end=end,
            dimension_ids=dimension_ids,
        )

        stats_service.schedule_recompute_missing_days(
            missing_days=missing_days,
            timezone_name=effective_timezone,
            user_id=current_user.id,
        )
        items = [
            AggregatedDimensionStatResponse(
                granularity=AggregationGranularity.day,
                period_start=row.date,
                period_end=row.date,
                dimension_id=row.dimension_id,
                minutes=row.minutes,
            )
            for row in daily_rows
        ]
        total = len(items)
        pages = 1 if total > 0 else 0
        return AggregatedDimensionStatListResponse(
            items=items,
            pagination={
                "page": 1,
                "size": total,
                "total": total,
                "pages": pages,
            },
            meta={
                "granularity": granularity,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "timezone": effective_timezone,
                "dimension_ids": dimension_ids,
                "first_day_of_week": first_day_of_week,
                "calendar_system": resolved_calendar_system,
            },
        )

    normalized_first_day = (
        first_day_of_week if granularity == AggregationGranularity.week else 1
    )
    persisted_first_day = (
        first_day_of_week if granularity == AggregationGranularity.week else 0
    )

    expected_periods = _expected_periods_for_range(
        start=start,
        end=end,
        granularity=granularity,
        first_day_of_week=normalized_first_day,
        calendar_system=resolved_calendar_system,
    )

    if not expected_periods:
        return AggregatedDimensionStatListResponse(
            items=[],
            pagination={
                "page": 1,
                "size": 0,
                "total": 0,
                "pages": 0,
            },
            meta={
                "granularity": granularity,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "timezone": timezone,
                "dimension_ids": dimension_ids,
                "first_day_of_week": first_day_of_week,
                "calendar_system": resolved_calendar_system,
            },
        )

    canonical_start = expected_periods[0][0]
    canonical_end = expected_periods[-1][1]

    cached_rows = await stats_service.fetch_cached_aggregated_stats(
        db,
        user_id=current_user.id,
        granularity=granularity,
        timezone=timezone,
        calendar_system=resolved_calendar_system,
        first_day_of_week=persisted_first_day,
        start=canonical_start,
        end=canonical_end,
    )

    missing_periods = _missing_periods(expected_periods, cached_rows)
    if missing_periods:
        (
            daily_rows,
            missing_days,
            effective_timezone,
        ) = await stats_service.collect_daily_dimension_stats(
            db,
            user_id=current_user.id,
            timezone=timezone,
            start=canonical_start,
            end=canonical_end,
            dimension_ids=None,
        )

        stats_service.schedule_recompute_missing_days(
            missing_days=missing_days,
            timezone_name=effective_timezone,
            user_id=current_user.id,
        )

        aggregated_rows = _aggregate_daily_dimension_stats(
            daily_rows,
            granularity=granularity,
            first_day_of_week=normalized_first_day,
            calendar_system=resolved_calendar_system,
        )

        await stats_service.upsert_aggregated_dimension_stats(
            db,
            user_id=current_user.id,
            timezone=timezone,
            calendar_system=resolved_calendar_system,
            first_day_of_week=persisted_first_day,
            granularity=granularity,
            rows=aggregated_rows,
        )

        cached_rows = await stats_service.fetch_cached_aggregated_stats(
            db,
            user_id=current_user.id,
            granularity=granularity,
            timezone=timezone,
            calendar_system=resolved_calendar_system,
            first_day_of_week=persisted_first_day,
            start=canonical_start,
            end=canonical_end,
        )

    expected_period_set = set(expected_periods)
    filtered_rows = [
        row
        for row in cached_rows
        if (row.period_start, row.period_end) in expected_period_set
    ]

    if dimension_filter:
        filtered_rows = [
            row for row in filtered_rows if row.dimension_id in dimension_filter
        ]

    filtered_rows.sort(key=lambda item: (item.period_start, item.dimension_id))

    items = [
        AggregatedDimensionStatResponse(
            granularity=AggregationGranularity(row.granularity),
            period_start=row.period_start.isoformat(),
            period_end=row.period_end.isoformat(),
            dimension_id=row.dimension_id,
            minutes=row.minutes,
        )
        for row in filtered_rows
    ]
    total = len(items)
    pages = 1 if total > 0 else 0
    return AggregatedDimensionStatListResponse(
        items=items,
        pagination={
            "page": 1,
            "size": total,
            "total": total,
            "pages": pages,
        },
        meta={
            "granularity": granularity,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": timezone,
            "dimension_ids": dimension_ids,
            "first_day_of_week": first_day_of_week,
            "calendar_system": resolved_calendar_system,
        },
    )


@router.post("/daily-dimensions/recompute", response_model=RecomputeResponse)
async def recompute_daily_dimensions(
    start: date = Query(..., description="Start date (local-day) inclusive"),
    end: date = Query(..., description="End date (local-day) inclusive"),
    timezone: str = Query(..., description="Timezone identifier (IANA)"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> RecomputeResponse:
    """Trigger recomputation for the date range. Returns count of days recomputed.

    Uses the supplied timezone to determine local-day boundaries.
    """
    if end < start:
        raise HTTPException(status_code=400, detail="end must be >= start")
    days = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur = date.fromordinal(cur.toordinal() + 1)
    await stats_service.recompute_daily_stats_for_dates_timezone(
        db,
        days_local=days,
        timezone_str=timezone,
        user_id=current_user.id,
    )
    return RecomputeResponse(days_recomputed=len(days))


@router.get("/day-breakdown", response_model=DayBreakdownListResponse)
async def get_day_breakdown(
    day: date = Query(..., description="Local calendar day (YYYY-MM-DD)"),
    timezone: str = Query(..., description="Timezone identifier (IANA)"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> DayBreakdownListResponse:
    """Return per-dimension minutes for a single local day, given the timezone offset.

    This endpoint is intended for the Timelog page's 24h distribution to match
    client-local day boundaries exactly.
    """
    totals = await stats_service.compute_timezone_day_dimension_minutes(
        db,
        day,
        timezone,
        user_id=current_user.id,
    )
    items = [
        DayBreakdownResponse(dimension_id=k, minutes=v)
        for k, v in sorted(totals.items())
    ]
    total = len(items)
    pages = 1 if total > 0 else 0
    return DayBreakdownListResponse(
        items=items,
        pagination={
            "page": 1,
            "size": total,
            "total": total,
            "pages": pages,
        },
        meta={"day": day.isoformat(), "timezone": timezone},
    )


@router.get("/tags/usage/{entity_type}", response_model=TagUsageStatsResponse)
async def get_tag_usage_by_entity_type(
    entity_type: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TagUsageStatsResponse:
    """
    Get tag usage statistics for a specific entity type

    Args:
        entity_type: The entity type (person, note, vision)
        db: Database session

    Returns:
        Dictionary containing tag usage statistics for the specified entity type
    """
    try:
        result = await stats_service.get_tag_usage_by_entity_type(
            db,
            user_id=current_user.id,
            entity_type=entity_type,
        )
        return TagUsageStatsResponse(**result)
    except InvalidEntityTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StatsComputationError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
