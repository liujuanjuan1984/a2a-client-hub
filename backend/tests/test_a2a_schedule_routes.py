from __future__ import annotations

import pytest

from app.api.routers import a2a_schedules
from app.db.models.a2a_agent import A2AAgent
from tests.api_utils import create_test_client
from tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _create_agent(async_db_session, *, user_id, suffix: str) -> A2AAgent:
    agent = A2AAgent(
        user_id=user_id,
        name=f"Agent {suffix}",
        card_url=f"https://example.com/{suffix}",
        auth_type="none",
        enabled=True,
    )
    async_db_session.add(agent)
    await async_db_session.commit()
    await async_db_session.refresh(agent)
    return agent


async def test_schedule_routes_crud_and_toggle(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="main")

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Morning digest",
                "agent_id": str(agent.id),
                "prompt": "Give me daily updates",
                "cycle_type": "daily",
                "time_point": {"time": "09:15"},
                "enabled": True,
            },
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        task_id = created["id"]
        assert created["name"] == "Morning digest"
        assert created["enabled"] is True
        assert created["consecutive_failures"] == 0

        list_resp = await client.get(
            "/me/a2a/schedules", params={"page": 1, "size": 20}
        )
        assert list_resp.status_code == 200
        assert list_resp.json()["pagination"]["total"] >= 1

        get_resp = await client.get(f"/me/a2a/schedules/{task_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == task_id

        update_resp = await client.patch(
            f"/me/a2a/schedules/{task_id}",
            json={
                "prompt": "Give me concise daily updates",
                "time_point": {"time": "10:00"},
            },
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["prompt"] == "Give me concise daily updates"

        name_resp = await client.patch(
            f"/me/a2a/schedules/{task_id}",
            json={"name": "Morning digest v2"},
        )
        assert name_resp.status_code == 200
        assert name_resp.json()["name"] == "Morning digest v2"

        disable_resp = await client.post(f"/me/a2a/schedules/{task_id}/disable")
        assert disable_resp.status_code == 200
        assert disable_resp.json()["enabled"] is False

        enable_resp = await client.post(f"/me/a2a/schedules/{task_id}/enable")
        assert enable_resp.status_code == 200
        assert enable_resp.json()["enabled"] is True

        executions_resp = await client.get(
            f"/me/a2a/schedules/{task_id}/executions",
            params={"page": 1, "size": 20},
        )
        assert executions_resp.status_code == 200
        assert executions_resp.json()["meta"]["task_id"] == task_id

        delete_resp = await client.delete(f"/me/a2a/schedules/{task_id}")
        assert delete_resp.status_code == 204

        after_delete_resp = await client.get(f"/me/a2a/schedules/{task_id}")
        assert after_delete_resp.status_code == 404


async def test_schedule_create_rejects_unowned_agent(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    current_user = await create_user(async_db_session, skip_onboarding_defaults=True)
    other_user = await create_user(async_db_session, skip_onboarding_defaults=True)
    other_agent = await _create_agent(
        async_db_session,
        user_id=other_user.id,
        suffix="other",
    )

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=current_user,
    ) as client:
        resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Invalid owner",
                "agent_id": str(other_agent.id),
                "prompt": "hello",
                "cycle_type": "daily",
                "time_point": {"time": "08:00"},
                "enabled": True,
            },
        )
        assert resp.status_code == 400


async def test_schedule_create_interval_normalizes_minutes(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "a2a_schedule_min_interval_minutes", 1)

    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="interval")

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Every few minutes",
                "agent_id": str(agent.id),
                "prompt": "ping",
                "cycle_type": "interval",
                "time_point": {"minutes": 9},
                "enabled": False,
            },
        )
        assert resp.status_code == 201
        payload = resp.json()
        assert payload["cycle_type"] == "interval"
        assert payload["time_point"] == {"minutes": 10}


async def test_schedule_create_weekly_uses_iso_weekday(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="weekly")

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Weekly digest",
                "agent_id": str(agent.id),
                "prompt": "ping",
                "cycle_type": "weekly",
                "time_point": {"weekday": 1, "time": "09:15"},
                "enabled": False,
            },
        )
        assert resp.status_code == 201
        payload = resp.json()
        assert payload["cycle_type"] == "weekly"
        assert payload["time_point"] == {"weekday": 1, "time": "09:15"}


async def test_schedule_create_rejects_over_quota(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "a2a_schedule_max_active_tasks_per_user", 1)

    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="quota")

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        # First task should succeed
        resp1 = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Task 1",
                "agent_id": str(agent.id),
                "prompt": "ping",
                "cycle_type": "daily",
                "time_point": {"time": "09:00"},
                "enabled": True,
            },
        )
        assert resp1.status_code == 201

        # Second task should fail due to quota
        resp2 = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Task 2",
                "agent_id": str(agent.id),
                "prompt": "ping 2",
                "cycle_type": "daily",
                "time_point": {"time": "10:00"},
                "enabled": True,
            },
        )
        assert resp2.status_code == 403
        assert "limit" in resp2.json()["detail"].lower()


async def test_schedule_admin_bypasses_quota_and_interval(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "a2a_schedule_max_active_tasks_per_user", 0)
    monkeypatch.setattr(settings, "a2a_schedule_min_interval_minutes", 60)

    admin_user = await create_user(
        async_db_session, skip_onboarding_defaults=True, is_superuser=True
    )
    agent = await _create_agent(async_db_session, user_id=admin_user.id, suffix="admin")

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=admin_user,
    ) as client:
        # Admin should be able to create task despite quota=0
        # Admin should also be able to use interval < min_interval_minutes and not rounded to 5
        resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Admin Task",
                "agent_id": str(agent.id),
                "prompt": "ping",
                "cycle_type": "interval",
                "time_point": {"minutes": 1},
                "enabled": True,
            },
        )
        assert resp.status_code == 201
        payload = resp.json()
        assert payload["time_point"] == {"minutes": 1}


async def test_schedule_interval_enforces_minimum(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "a2a_schedule_min_interval_minutes", 60)

    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="min_interval"
    )

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        # Should fail if minutes < min_interval_minutes
        resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Invalid interval",
                "agent_id": str(agent.id),
                "prompt": "ping",
                "cycle_type": "interval",
                "time_point": {"minutes": 30},
                "enabled": True,
            },
        )
        assert resp.status_code == 400
        assert "cannot be less than" in resp.json()["detail"].lower()
