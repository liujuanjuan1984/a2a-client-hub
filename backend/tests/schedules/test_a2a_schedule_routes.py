from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.retry_after import DB_BUSY_RETRY_AFTER_SECONDS
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.features.schedules import router as a2a_schedules
from app.features.schedules.common import (
    A2AScheduleConflictError,
    A2AScheduleServiceBusyError,
)
from app.features.schedules.hub_assistant_jobs_service import (
    hub_assistant_jobs_service,
)
from app.features.schedules.service import a2a_schedule_service
from app.utils.timezone_util import utc_now
from tests.support.api_utils import create_test_client
from tests.support.utils import create_a2a_agent, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_create_agent = create_a2a_agent


async def test_call_schedule_maps_db_lock_conflict_to_http_409() -> None:
    async def _raise_lock_conflict():
        raise A2AScheduleConflictError(
            "Schedule task is currently locked by another operation; retry shortly."
        )

    with pytest.raises(HTTPException) as exc_info:
        await a2a_schedules._call_schedule(_raise_lock_conflict())

    error = exc_info.value
    assert error.status_code == 409
    assert "retry shortly" in str(error.detail)


async def test_call_schedule_maps_db_statement_timeout_to_http_503() -> None:
    async def _raise_statement_timeout():
        raise A2AScheduleServiceBusyError(
            "Schedule task operation timed out; service busy, retry shortly.",
        )

    with pytest.raises(HTTPException) as exc_info:
        await a2a_schedules._call_schedule(_raise_statement_timeout())

    error = exc_info.value
    assert error.status_code == 503
    assert "service busy" in str(error.detail)
    assert error.headers == {"Retry-After": str(DB_BUSY_RETRY_AFTER_SECONDS)}


async def test_schedule_list_route_returns_503_and_retry_after_when_service_busy(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async def _raise_service_busy(*_args, **_kwargs):
        raise A2AScheduleServiceBusyError(
            "Schedule task list timed out; service busy, retry shortly.",
        )

    monkeypatch.setattr(a2a_schedule_service, "list_tasks", _raise_service_busy)

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.get("/me/a2a/schedules", params={"page": 1, "size": 20})

    assert response.status_code == 503
    assert "service busy" in response.json()["detail"]
    assert response.headers.get("Retry-After") == str(DB_BUSY_RETRY_AFTER_SECONDS)


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
                "schedule_timezone": user.timezone or "UTC",
            },
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        task_id = created["id"]
        assert created["name"] == "Morning digest"
        assert created["enabled"] is True
        assert created["consecutive_failures"] == 0
        assert created["status_summary"]["state"] == "idle"
        assert created["status_summary"]["manual_intervention_recommended"] is False

        list_resp = await client.get(
            "/me/a2a/schedules", params={"page": 1, "size": 20}
        )
        assert list_resp.status_code == 200
        assert list_resp.json()["pagination"]["total"] >= 1
        assert list_resp.json()["items"][0]["status_summary"]["state"] == "idle"

        get_resp = await client.get(f"/me/a2a/schedules/{task_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == task_id
        assert get_resp.json()["status_summary"]["state"] == "idle"

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


async def test_schedule_patch_prompt_uses_hub_assistant_jobs_service(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="prompt-gateway"
    )

    original = hub_assistant_jobs_service.update_prompt
    called = {"value": False}

    async def _wrapped_update_prompt(**kwargs):
        called["value"] = True
        return await original(**kwargs)

    monkeypatch.setattr(
        hub_assistant_jobs_service,
        "update_prompt",
        _wrapped_update_prompt,
    )

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Prompt route",
                "agent_id": str(agent.id),
                "prompt": "original prompt",
                "cycle_type": "daily",
                "time_point": {"time": "09:15"},
                "enabled": True,
                "schedule_timezone": user.timezone or "UTC",
            },
        )
        task_id = create_resp.json()["id"]

        update_resp = await client.patch(
            f"/me/a2a/schedules/{task_id}",
            json={"prompt": "updated via gateway"},
        )

    assert update_resp.status_code == 200
    assert update_resp.json()["prompt"] == "updated via gateway"
    assert called["value"] is True


async def test_schedule_patch_schedule_uses_hub_assistant_jobs_service(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="schedule-gateway"
    )

    original = hub_assistant_jobs_service.update_schedule
    called = {"value": False}

    async def _wrapped_update_schedule(**kwargs):
        called["value"] = True
        return await original(**kwargs)

    monkeypatch.setattr(
        hub_assistant_jobs_service,
        "update_schedule",
        _wrapped_update_schedule,
    )

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Schedule route",
                "agent_id": str(agent.id),
                "prompt": "original prompt",
                "cycle_type": "daily",
                "time_point": {"time": "09:15"},
                "enabled": True,
                "schedule_timezone": user.timezone or "UTC",
            },
        )
        task_id = create_resp.json()["id"]

        update_resp = await client.patch(
            f"/me/a2a/schedules/{task_id}",
            json={"time_point": {"time": "10:45"}},
        )

    assert update_resp.status_code == 200
    assert update_resp.json()["time_point"]["time"] == "10:45"
    assert called["value"] is True


async def test_schedule_list_prioritizes_attention_then_running_then_recent_activity(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="ordering")

    enabled_attention = await a2a_schedule_service.create_task(
        async_db_session,
        user_id=user.id,
        is_superuser=False,
        timezone_str=user.timezone or "UTC",
        name="Enabled attention",
        agent_id=agent.id,
        prompt="first",
        cycle_type="daily",
        time_point={"time": "08:00"},
        enabled=True,
    )
    enabled_running = await a2a_schedule_service.create_task(
        async_db_session,
        user_id=user.id,
        is_superuser=False,
        timezone_str=user.timezone or "UTC",
        name="Enabled running",
        agent_id=agent.id,
        prompt="second",
        cycle_type="daily",
        time_point={"time": "09:00"},
        enabled=True,
    )
    enabled_recent_run = await a2a_schedule_service.create_task(
        async_db_session,
        user_id=user.id,
        is_superuser=False,
        timezone_str=user.timezone or "UTC",
        name="Enabled recent run",
        agent_id=agent.id,
        prompt="third",
        cycle_type="daily",
        time_point={"time": "10:00"},
        enabled=True,
    )
    disabled_newest = await a2a_schedule_service.create_task(
        async_db_session,
        user_id=user.id,
        is_superuser=False,
        timezone_str=user.timezone or "UTC",
        name="Disabled newest",
        agent_id=agent.id,
        prompt="fourth",
        cycle_type="daily",
        time_point={"time": "11:00"},
        enabled=False,
    )

    now = utc_now()
    async_db_session.add_all(
        [
            A2AScheduleExecution(
                user_id=user.id,
                task_id=enabled_attention.id,
                run_id=uuid4(),
                scheduled_for=now - timedelta(minutes=20),
                started_at=now - timedelta(minutes=20),
                last_heartbeat_at=now - timedelta(minutes=20),
                status=A2AScheduleExecution.STATUS_RUNNING,
            ),
            A2AScheduleExecution(
                user_id=user.id,
                task_id=enabled_running.id,
                run_id=uuid4(),
                scheduled_for=now - timedelta(minutes=5),
                started_at=now - timedelta(minutes=5),
                last_heartbeat_at=now - timedelta(seconds=10),
                status=A2AScheduleExecution.STATUS_RUNNING,
            ),
        ]
    )
    enabled_attention.updated_at = now - timedelta(hours=6)
    enabled_attention.last_run_at = now - timedelta(hours=6)
    enabled_running.updated_at = now - timedelta(hours=5)
    enabled_running.last_run_at = now - timedelta(hours=5)
    enabled_recent_run.updated_at = now - timedelta(hours=4)
    enabled_recent_run.last_run_at = now - timedelta(minutes=10)
    disabled_newest.updated_at = now
    disabled_newest.last_run_at = None
    await async_db_session.commit()

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        list_resp = await client.get(
            "/me/a2a/schedules",
            params={"page": 1, "size": 20},
        )

    assert list_resp.status_code == 200
    assert [item["id"] for item in list_resp.json()["items"][:4]] == [
        str(enabled_attention.id),
        str(enabled_running.id),
        str(enabled_recent_run.id),
        str(disabled_newest.id),
    ]
    assert (
        list_resp.json()["items"][0]["status_summary"][
            "manual_intervention_recommended"
        ]
        is True
    )
    assert list_resp.json()["items"][1]["is_running"] is True


async def test_schedule_conversation_policy_persists_on_create_and_update(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="policy")

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Policy check",
                "agent_id": str(agent.id),
                "prompt": "Use policy",
                "cycle_type": "daily",
                "time_point": {"time": "08:30"},
                "enabled": False,
                "conversation_policy": "reuse_single",
                "schedule_timezone": user.timezone or "UTC",
            },
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        task_id = created["id"]
        assert created["conversation_policy"] == "reuse_single"

        get_created_resp = await client.get(f"/me/a2a/schedules/{task_id}")
        assert get_created_resp.status_code == 200
        assert get_created_resp.json()["conversation_policy"] == "reuse_single"

        update_resp = await client.patch(
            f"/me/a2a/schedules/{task_id}",
            json={"conversation_policy": "new_each_run"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["conversation_policy"] == "new_each_run"

        get_updated_resp = await client.get(f"/me/a2a/schedules/{task_id}")
        assert get_updated_resp.status_code == 200
        assert get_updated_resp.json()["conversation_policy"] == "new_each_run"


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
                "schedule_timezone": current_user.timezone or "UTC",
            },
        )
        assert resp.status_code == 400


async def test_schedule_create_rejects_mismatched_schedule_timezone(
    async_db_session,
    async_session_maker,
):
    user = await create_user(
        async_db_session,
        skip_onboarding_defaults=True,
        timezone="Asia/Shanghai",
    )
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="tz-mismatch")

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Timezone mismatch",
                "agent_id": str(agent.id),
                "prompt": "hello",
                "cycle_type": "daily",
                "time_point": {"time": "08:00"},
                "enabled": False,
                "schedule_timezone": "UTC",
            },
        )
        assert resp.status_code == 400
        assert (
            resp.json()["detail"]
            == "schedule_timezone must match current user's timezone"
        )


async def test_schedule_create_rejects_invalid_schedule_timezone(
    async_db_session,
    async_session_maker,
):
    user = await create_user(
        async_db_session,
        skip_onboarding_defaults=True,
        timezone="Asia/Shanghai",
    )
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="tz-invalid")

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Timezone invalid",
                "agent_id": str(agent.id),
                "prompt": "hello",
                "cycle_type": "daily",
                "time_point": {"time": "08:00"},
                "enabled": False,
                "schedule_timezone": "Invalid/Timezone",
            },
        )
        assert resp.status_code == 400
        assert (
            resp.json()["detail"] == "schedule_timezone must be a valid IANA timezone"
        )


async def test_schedule_mark_failed_transitions_running_task_and_is_idempotent(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="mark-failed")

    task = await a2a_schedule_service.create_task(
        async_db_session,
        user_id=user.id,
        is_superuser=False,
        timezone_str=user.timezone or "UTC",
        name="Running task",
        agent_id=agent.id,
        prompt="ping",
        cycle_type="daily",
        time_point={"time": "09:00"},
        enabled=False,
    )
    started_at = utc_now() - timedelta(minutes=3)
    run_id = uuid4()
    async_db_session.add(
        A2AScheduleExecution(
            user_id=user.id,
            task_id=task.id,
            run_id=run_id,
            scheduled_for=started_at,
            started_at=started_at,
            last_heartbeat_at=started_at,
            status=A2AScheduleExecution.STATUS_RUNNING,
        )
    )
    await async_db_session.commit()
    await async_db_session.refresh(task)

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/a2a/schedules/{task.id}/mark-failed",
            json={},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["id"] == str(task.id)
        assert payload["last_run_status"] == "failed"
        assert payload["is_running"] is False
        assert payload["last_run_at"] is not None
        assert payload["status_summary"]["state"] == "recent_failed"
        assert (
            payload["status_summary"]["recent_failure_message"]
            == "Stopped by user as failed"
        )
        assert payload["status_summary"]["recent_failure_error_code"] == "manual_failed"

        await async_db_session.refresh(task)
        failures_after_first_call = task.consecutive_failures
        assert task.last_run_status == A2AScheduleTask.STATUS_FAILED
        assert failures_after_first_call >= 1

        execution = await async_db_session.scalar(
            select(A2AScheduleExecution).where(
                A2AScheduleExecution.task_id == task.id,
                A2AScheduleExecution.run_id == run_id,
            )
        )
        assert execution is not None
        assert execution.status == A2AScheduleExecution.STATUS_FAILED
        assert execution.finished_at is not None
        assert execution.error_code == "manual_failed"
        assert execution.error_message == "Stopped by user as failed"

        second_resp = await client.post(
            f"/me/a2a/schedules/{task.id}/mark-failed",
            json={},
        )
        assert second_resp.status_code == 200
        await async_db_session.refresh(task)
        assert task.consecutive_failures == failures_after_first_call


async def test_schedule_execution_history_exposes_structured_error_code(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="history")

    task = await a2a_schedule_service.create_task(
        async_db_session,
        user_id=user.id,
        is_superuser=False,
        timezone_str=user.timezone or "UTC",
        name="History task",
        agent_id=agent.id,
        prompt="ping",
        cycle_type="daily",
        time_point={"time": "09:00"},
        enabled=True,
    )
    finished_at = utc_now()
    async_db_session.add(
        A2AScheduleExecution(
            user_id=user.id,
            task_id=task.id,
            run_id=uuid4(),
            scheduled_for=finished_at,
            started_at=finished_at,
            finished_at=finished_at,
            status=A2AScheduleExecution.STATUS_FAILED,
            error_code="agent_unavailable",
            error_message="Agent card unavailable",
        )
    )
    await async_db_session.commit()

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.get(
            f"/me/a2a/schedules/{task.id}/executions",
            params={"page": 1, "size": 20},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["items"][0]["error_code"] == "agent_unavailable"
    assert payload["items"][0]["error_message"] == "Agent card unavailable"


async def test_schedule_get_exposes_attention_summary_for_stale_running_execution(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="summary")

    task = await a2a_schedule_service.create_task(
        async_db_session,
        user_id=user.id,
        is_superuser=False,
        timezone_str=user.timezone or "UTC",
        name="Summary task",
        agent_id=agent.id,
        prompt="ping",
        cycle_type="daily",
        time_point={"time": "09:00"},
        enabled=True,
    )
    started_at = utc_now() - timedelta(minutes=10)
    last_heartbeat_at = utc_now() - timedelta(minutes=3)
    async_db_session.add(
        A2AScheduleExecution(
            user_id=user.id,
            task_id=task.id,
            run_id=uuid4(),
            scheduled_for=started_at,
            started_at=started_at,
            last_heartbeat_at=last_heartbeat_at,
            status=A2AScheduleExecution.STATUS_RUNNING,
        )
    )
    await async_db_session.commit()

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.get(f"/me/a2a/schedules/{task.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status_summary"]["state"] == "running"
    assert payload["status_summary"]["manual_intervention_recommended"] is True
    assert payload["status_summary"]["last_heartbeat_at"] is not None
    assert payload["status_summary"]["heartbeat_stale_after_seconds"] == 90


async def test_schedule_mark_failed_sequential_reschedules_next_run(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="mark-failed-sequential"
    )

    task = await a2a_schedule_service.create_task(
        async_db_session,
        user_id=user.id,
        is_superuser=False,
        timezone_str=user.timezone or "UTC",
        name="Sequential running task",
        agent_id=agent.id,
        prompt="ping",
        cycle_type="sequential",
        time_point={"minutes": 60},
        enabled=True,
    )
    started_at = utc_now() - timedelta(minutes=3)
    run_id = uuid4()
    task.next_run_at = None
    async_db_session.add(
        A2AScheduleExecution(
            user_id=user.id,
            task_id=task.id,
            run_id=run_id,
            scheduled_for=started_at,
            started_at=started_at,
            last_heartbeat_at=started_at,
            status=A2AScheduleExecution.STATUS_RUNNING,
        )
    )
    await async_db_session.commit()
    await async_db_session.refresh(task)

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/a2a/schedules/{task.id}/mark-failed",
            json={},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["last_run_status"] == "failed"
        assert payload["next_run_at_utc"] is not None

        await async_db_session.refresh(task)
        assert task.next_run_at is not None
        assert task.last_run_at is not None
        assert task.next_run_at >= task.last_run_at + timedelta(minutes=59)


async def test_schedule_mark_failed_rejects_non_running_task(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="mark-failed-state"
    )

    task = await a2a_schedule_service.create_task(
        async_db_session,
        user_id=user.id,
        is_superuser=False,
        timezone_str=user.timezone or "UTC",
        name="Idle task",
        agent_id=agent.id,
        prompt="ping",
        cycle_type="daily",
        time_point={"time": "09:00"},
        enabled=False,
    )

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/a2a/schedules/{task.id}/mark-failed",
            json={},
        )
        assert resp.status_code == 400
        assert (
            "Only running tasks can be manually marked as failed"
            in resp.json()["detail"]
        )


async def test_schedule_mark_failed_rejects_missing_execution(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="mark-failed-backfill"
    )

    task = await a2a_schedule_service.create_task(
        async_db_session,
        user_id=user.id,
        is_superuser=False,
        timezone_str=user.timezone or "UTC",
        name="Running task no execution",
        agent_id=agent.id,
        prompt="ping",
        cycle_type="daily",
        time_point={"time": "09:00"},
        enabled=False,
    )
    await async_db_session.commit()
    await async_db_session.refresh(task)

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/a2a/schedules/{task.id}/mark-failed",
            json={},
        )
        assert resp.status_code == 400
        assert (
            "Only running tasks can be manually marked as failed"
            in resp.json()["detail"]
        )


async def test_schedule_create_interval_normalizes_minutes(
    async_db_session,
    async_session_maker,
):
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
                "schedule_timezone": user.timezone or "UTC",
            },
        )
        assert resp.status_code == 201
        payload = resp.json()
        assert payload["cycle_type"] == "interval"
        assert payload["time_point"] == {"minutes": 9}


async def test_schedule_create_interval_accepts_start_at(
    async_db_session,
    async_session_maker,
):
    user = await create_user(
        async_db_session,
        skip_onboarding_defaults=True,
        timezone="Asia/Shanghai",
    )
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="interval")

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Backfill job",
                "agent_id": str(agent.id),
                "prompt": "ping",
                "cycle_type": "interval",
                "time_point": {
                    "minutes": 30,
                    "start_at_local": "2026-02-23T08:15",
                },
                "enabled": False,
                "schedule_timezone": user.timezone or "UTC",
            },
        )
        assert resp.status_code == 201
        payload = resp.json()
        assert payload["cycle_type"] == "interval"
        assert payload["time_point"]["minutes"] == 30
        assert payload["time_point"]["start_at_local"] == "2026-02-23T08:15"
        assert payload["time_point"]["start_at_utc"] == "2026-02-23T00:15:00+00:00"


async def test_schedule_enable_interval_accepts_persisted_utc_start_at(
    async_db_session,
    async_session_maker,
):
    user = await create_user(
        async_db_session,
        skip_onboarding_defaults=True,
        timezone="Asia/Shanghai",
    )
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="enable")

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Interval enable",
                "agent_id": str(agent.id),
                "prompt": "ping",
                "cycle_type": "interval",
                "time_point": {
                    "minutes": 30,
                    "start_at_local": "2026-02-23T08:15",
                },
                "enabled": False,
                "schedule_timezone": user.timezone or "UTC",
            },
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        task_id = created["id"]
        assert created["time_point"]["start_at_local"] == "2026-02-23T08:15"
        assert created["time_point"]["start_at_utc"] == "2026-02-23T00:15:00+00:00"

        enable_resp = await client.post(f"/me/a2a/schedules/{task_id}/enable")
        assert enable_resp.status_code == 200
        enabled_payload = enable_resp.json()
        assert enabled_payload["enabled"] is True
        assert enabled_payload["next_run_at_utc"] is not None
        assert enabled_payload["next_run_at_local"] is not None


async def test_schedule_create_interval_rejects_start_at_with_timezone_offset(
    async_db_session,
    async_session_maker,
):
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
                "name": "Backfill job",
                "agent_id": str(agent.id),
                "prompt": "ping",
                "cycle_type": "interval",
                "time_point": {
                    "minutes": 30,
                    "start_at_local": "2026-02-23T08:15:00+08:00",
                },
                "enabled": False,
                "schedule_timezone": user.timezone or "UTC",
            },
        )
        assert resp.status_code == 400
        assert (
            resp.json()["detail"]
            == "interval time_point.start_at_local must be timezone-naive "
            "(without Z or offset)"
        )


async def test_schedule_create_sequential_normalizes_minutes_and_strips_anchors(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="sequential")

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Sequential digest",
                "agent_id": str(agent.id),
                "prompt": "ping",
                "cycle_type": "sequential",
                "time_point": {"minutes": 9},
                "enabled": False,
                "schedule_timezone": user.timezone or "UTC",
            },
        )
        assert resp.status_code == 201
        payload = resp.json()
        assert payload["cycle_type"] == "sequential"
        assert payload["time_point"] == {"minutes": 9}


async def test_schedule_create_sequential_rejects_start_anchor_fields(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="sequential")

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Sequential digest",
                "agent_id": str(agent.id),
                "prompt": "ping",
                "cycle_type": "sequential",
                "time_point": {
                    "minutes": 30,
                    "start_at_local": "2026-02-23T08:15",
                },
                "enabled": False,
                "schedule_timezone": user.timezone or "UTC",
            },
        )
        assert resp.status_code == 400
        assert (
            resp.json()["detail"]
            == "sequential does not support start_at_local/start_at_utc; use minutes only"
        )


async def test_schedule_get_sequential_omits_legacy_anchor_fields(
    async_db_session,
    async_session_maker,
):
    user = await create_user(
        async_db_session,
        skip_onboarding_defaults=True,
        timezone="Asia/Shanghai",
    )
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="sequential")
    task = A2AScheduleTask(
        user_id=user.id,
        name="Sequential persisted UTC",
        agent_id=agent.id,
        prompt="ping",
        cycle_type=A2AScheduleTask.CYCLE_SEQUENTIAL,
        time_point={
            "minutes": 99999,
            "start_at_utc": "2026-02-23T00:15:00+00:00",
            "start_at_local": "2026-02-23T08:15",
        },
        enabled=False,
    )
    async_db_session.add(task)
    await async_db_session.commit()
    await async_db_session.refresh(task)

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.get(f"/me/a2a/schedules/{task.id}")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["cycle_type"] == "sequential"
        assert payload["time_point"] == {"minutes": 1440}


async def test_schedule_get_interval_sanitizes_dirty_minutes(
    async_db_session,
    async_session_maker,
):
    user = await create_user(
        async_db_session,
        skip_onboarding_defaults=True,
        timezone="Asia/Shanghai",
    )
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="interval")
    task = A2AScheduleTask(
        user_id=user.id,
        name="Interval dirty minutes",
        agent_id=agent.id,
        prompt="ping",
        cycle_type=A2AScheduleTask.CYCLE_INTERVAL,
        time_point={
            "minutes": -7,
            "start_at_utc": "2026-02-23T00:15:00+00:00",
        },
        enabled=False,
    )
    async_db_session.add(task)
    await async_db_session.commit()
    await async_db_session.refresh(task)

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.get(f"/me/a2a/schedules/{task.id}")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["cycle_type"] == "interval"
        assert payload["time_point"]["minutes"] == 5
        assert payload["time_point"]["start_at_utc"] == "2026-02-23T00:15:00+00:00"
        assert payload["time_point"]["start_at_local"] == "2026-02-23T08:15"


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
                "schedule_timezone": user.timezone or "UTC",
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
                "schedule_timezone": user.timezone or "UTC",
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
                "schedule_timezone": user.timezone or "UTC",
            },
        )
        assert resp2.status_code == 403
        assert "limit" in resp2.json()["detail"].lower()


async def test_schedule_admin_bypasses_quota_and_minutes_are_still_normalized(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "a2a_schedule_max_active_tasks_per_user", 0)

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
        # Minutes still follow shared clamp rules for both interval/sequential.
        resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Admin Task",
                "agent_id": str(agent.id),
                "prompt": "ping",
                "cycle_type": "interval",
                "time_point": {"minutes": 1},
                "enabled": True,
                "schedule_timezone": admin_user.timezone or "UTC",
            },
        )
        assert resp.status_code == 201
        payload = resp.json()
        assert payload["time_point"] == {"minutes": 5}


async def test_schedule_interval_clamps_minutes_into_valid_range(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="min_interval"
    )

    async with create_test_client(
        a2a_schedules.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        low_resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "Low interval",
                "agent_id": str(agent.id),
                "prompt": "ping",
                "cycle_type": "interval",
                "time_point": {"minutes": 1},
                "enabled": True,
                "schedule_timezone": user.timezone or "UTC",
            },
        )
        assert low_resp.status_code == 201
        assert low_resp.json()["time_point"]["minutes"] == 5

        high_resp = await client.post(
            "/me/a2a/schedules",
            json={
                "name": "High interval",
                "agent_id": str(agent.id),
                "prompt": "ping",
                "cycle_type": "interval",
                "time_point": {"minutes": 99999},
                "enabled": False,
                "schedule_timezone": user.timezone or "UTC",
            },
        )
        assert high_resp.status_code == 201
        assert high_resp.json()["time_point"]["minutes"] == 1440
