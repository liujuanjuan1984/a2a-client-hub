from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.api.routers import stats as stats_router
from app.handlers import actual_events as actual_events_service
from app.handlers.metrics import stats as stats_service
from app.schemas.actual_event import ActualEventCreate
from backend.tests.api_utils import create_test_client
from backend.tests.utils import (
    create_dimension,
    create_task,
    create_user,
    create_vision,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_get_daily_dimensions_returns_minutes(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await create_dimension(async_db_session, user)
    vision = await create_vision(async_db_session, user, dimension=dimension)
    task = await create_task(async_db_session, user, vision)

    async with async_session_maker() as async_session:
        await actual_events_service.create_actual_event(
            async_session,
            user_id=user.id,
            event_in=ActualEventCreate(
                title="Focus Block",
                start_time=datetime(2025, 5, 1, 9, 0, tzinfo=timezone.utc),
                end_time=datetime(2025, 5, 1, 10, 0, tzinfo=timezone.utc),
                dimension_id=dimension.id,
                task_id=task.id,
            ),
        )

        await stats_service.recompute_daily_stats_for_dates_timezone(
            async_session,
            days_local=[date(2025, 5, 1)],
            timezone_str="UTC",
            user_id=user.id,
        )
        await async_session.commit()

    async with create_test_client(
        stats_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.get(
            "/stats/daily-dimensions",
            params={
                "start": "2025-05-01",
                "end": "2025-05-01",
                "timezone": "UTC",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    items = payload["items"]
    assert len(items) >= 1
    matching = [row for row in items if row["dimension_id"] == str(dimension.id)]
    assert matching and matching[0]["minutes"] == 60


async def test_get_tag_usage_invalid_type(async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        stats_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.get("/stats/tags/usage/invalid")

    assert response.status_code == 400
