from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.routers import habits as habits_router
from app.db.models.habit import Habit
from app.db.models.habit_action import HabitAction
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _habit_payload(start: date) -> dict:
    return {
        "title": "Morning Run",
        "description": "",
        "start_date": start.isoformat(),
        "duration_days": 7,
        "task_id": None,
    }


async def test_create_habit_route(async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    today = date.today()

    async with create_test_client(
        habits_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.post("/habits/", json=_habit_payload(today))

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Morning Run"


async def test_list_habits_invalid_status_filter_returns_400(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        habits_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.get("/habits/", params={"status_filter": "invalid"})

    assert response.status_code == 400


async def test_list_habits_expired_filter_returns_expired_habits(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    today = date.today()
    expired_start = today - timedelta(days=10)
    expired_payload = {
        "title": "Expired Habit",
        "description": "",
        "start_date": expired_start.isoformat(),
        "duration_days": 7,
        "task_id": None,
    }
    active_payload = {
        "title": "Active Habit",
        "description": "",
        "start_date": today.isoformat(),
        "duration_days": 7,
        "task_id": None,
    }

    async with create_test_client(
        habits_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        await client.post("/habits/", json=expired_payload)
        await client.post("/habits/", json=active_payload)
        response = await client.get("/habits/", params={"status_filter": "expired"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"]["total"] == 1
    assert payload["items"][0]["status"] == "expired"
    assert payload["items"][0]["title"] == "Expired Habit"

    result = await async_db_session.execute(
        select(Habit).where(Habit.user_id == user.id, Habit.title == "Expired Habit")
    )
    stored = result.scalar_one()
    assert stored.status == "expired"


async def test_list_habits_active_filter_excludes_expired(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    today = date.today()
    expired_start = today - timedelta(days=10)
    expired_payload = {
        "title": "Expired Habit",
        "description": "",
        "start_date": expired_start.isoformat(),
        "duration_days": 7,
        "task_id": None,
    }
    active_payload = {
        "title": "Active Habit",
        "description": "",
        "start_date": today.isoformat(),
        "duration_days": 7,
        "task_id": None,
    }

    async with create_test_client(
        habits_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        await client.post("/habits/", json=expired_payload)
        await client.post("/habits/", json=active_payload)
        response = await client.get("/habits/", params={"status_filter": "active"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"]["total"] == 1
    assert payload["items"][0]["status"] == "active"
    assert payload["items"][0]["title"] == "Active Habit"


async def test_update_habit_not_found_returns_404(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        habits_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.put(
            f"/habits/{uuid4()}",
            json={"title": "Updated"},
        )

    assert response.status_code == 404


async def test_update_habit_action_future_date_returns_400(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    today = date.today()

    async with create_test_client(
        habits_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_resp = await client.post("/habits/", json=_habit_payload(today))
        habit_id = create_resp.json()["id"]

        result = await async_db_session.execute(
            select(HabitAction)
            .where(HabitAction.habit_id == habit_id)
            .order_by(HabitAction.action_date.asc())
        )
        actions = result.scalars().all()
        future_action = next(a for a in actions if a.action_date > today)

        response = await client.put(
            f"/habits/{habit_id}/actions/{future_action.id}",
            json={"status": "done"},
        )

    assert response.status_code == 400


async def test_get_habit_actions_accepts_window_query(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    today = date.today()

    async with create_test_client(
        habits_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_resp = await client.post("/habits/", json=_habit_payload(today))
        habit_id = create_resp.json()["id"]

        response = await client.get(
            f"/habits/{habit_id}/actions",
            params={
                "center_date": today.isoformat(),
                "days_before": 1,
                "days_after": 1,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["pagination"]["total"] == len(data["items"]) == 2


async def test_get_habit_overview_endpoint_returns_stats(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    today = date.today()

    async with create_test_client(
        habits_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_resp = await client.post("/habits/", json=_habit_payload(today))
        habit_id = create_resp.json()["id"]

        response = await client.get(f"/habits/{habit_id}/overview")

    assert response.status_code == 200
    data = response.json()
    assert data["habit"]["id"] == habit_id
    assert data["stats"]["habit_id"] == habit_id


async def test_list_habit_overviews_endpoint_includes_stats(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    today = date.today()

    async with create_test_client(
        habits_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        await client.post("/habits/", json=_habit_payload(today))
        await client.post(
            "/habits/",
            json=_habit_payload(today),
        )

        response = await client.get("/habits/overviews")

    assert response.status_code == 200
    body = response.json()
    assert body["pagination"]["total"] >= 2
    assert len(body["items"]) >= 2
    assert "stats" in body["items"][0]
