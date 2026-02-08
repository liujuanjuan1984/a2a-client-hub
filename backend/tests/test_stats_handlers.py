from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models.actual_event import ActualEvent
from app.db.models.daily_dimension_stat import DailyDimensionStat
from app.handlers.metrics import stats as stats_service
from app.handlers.metrics.stats import InvalidEntityTypeError
from backend.tests.utils import create_dimension, create_user

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


async def _create_event(async_db_session, user, dimension, *, start, end):
    event = ActualEvent(
        title="Work Block",
        user_id=user.id,
        start_time=start,
        end_time=end,
        dimension_id=dimension.id,
    )
    async_db_session.add(event)
    await async_db_session.flush()
    return event


async def test_compute_timezone_day_dimension_minutes(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await create_dimension(async_db_session, user)
    await _create_event(
        async_db_session,
        user,
        dimension,
        start=datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc),
        end=datetime(2025, 1, 1, 10, 30, tzinfo=timezone.utc),
    )

    totals = await stats_service.compute_timezone_day_dimension_minutes(
        async_db_session,
        local_day=date(2025, 1, 1),
        timezone_str="UTC",
        user_id=user.id,
    )
    assert totals[dimension.id] == 90


async def test_recompute_daily_stats_creates_rows(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await create_dimension(async_db_session, user)
    await _create_event(
        async_db_session,
        user,
        dimension,
        start=datetime(2025, 5, 10, 13, 0, tzinfo=timezone.utc),
        end=datetime(2025, 5, 10, 14, 0, tzinfo=timezone.utc),
    )

    await stats_service.recompute_daily_stats_for_dates_timezone(
        async_db_session,
        days_local=[date(2025, 5, 10)],
        timezone_str="UTC",
        user_id=user.id,
    )

    stmt = select(DailyDimensionStat).where(
        DailyDimensionStat.user_id == user.id,
        DailyDimensionStat.dimension_id == dimension.id,
        DailyDimensionStat.stat_date == date(2025, 5, 10),
        DailyDimensionStat.timezone == "UTC",
    )
    stat = (await async_db_session.execute(stmt)).scalars().first()
    assert stat is not None
    assert stat.minutes == 60


@pytest.mark.asyncio
async def test_get_tag_usage_invalid_entity_type_raises():
    with pytest.raises(InvalidEntityTypeError):
        await stats_service.get_tag_usage_by_entity_type(
            None, user_id=uuid4(), entity_type="invalid"
        )
