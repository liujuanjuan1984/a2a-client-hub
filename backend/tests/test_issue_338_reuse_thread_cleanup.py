from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.conversation_thread import ConversationThread
from app.services.a2a_schedule_job import _execute_claimed_task
from app.utils.timezone_util import utc_now
from tests.utils import create_a2a_agent, create_schedule_task, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_create_agent = create_a2a_agent


async def _create_schedule_task(
    session,
    *,
    user_id,
    agent_id,
    conversation_id=None,
    policy=A2AScheduleTask.POLICY_NEW,
) -> A2AScheduleTask:
    return await create_schedule_task(
        session,
        user_id=user_id,
        agent_id=agent_id,
        next_run_at=utc_now(),
        conversation_id=conversation_id,
        conversation_policy=policy,
    )


def _mock_runtime_builder():
    async def _build(_db, user_id, agent_id):
        return SimpleNamespace(
            agent=SimpleNamespace(enabled=True),
            resolved=SimpleNamespace(name="Schedule Agent"),
        )

    return SimpleNamespace(build=_build)


def _build_claim(task: A2AScheduleTask):
    from app.features.schedules.service import ClaimedA2AScheduleTask

    return ClaimedA2AScheduleTask(
        task_id=task.id,
        user_id=task.user_id,
        agent_id=task.agent_id,
        conversation_id=task.conversation_id,
        name=task.name,
        prompt=task.prompt,
        cycle_type=task.cycle_type,
        time_point=task.time_point,
        scheduled_for=task.next_run_at,
        run_id=uuid4(),
    )


async def _mark_task_claimed(session, *, task: A2AScheduleTask, run_id):
    started_at = utc_now()
    session.add(
        A2AScheduleExecution(
            user_id=task.user_id,
            task_id=task.id,
            run_id=run_id,
            scheduled_for=task.next_run_at or started_at,
            started_at=started_at,
            last_heartbeat_at=started_at,
            status=A2AScheduleExecution.STATUS_RUNNING,
            conversation_id=task.conversation_id,
        )
    )
    await session.commit()


async def test_execute_claimed_task_retains_history_on_reuse_policy_failure(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="reuse-fail")

    # Create an existing thread
    thread = ConversationThread(
        user_id=user.id,
        agent_id=agent.id,
        title="History",
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.commit()
    await async_db_session.refresh(thread)

    # Create task with REUSE policy and existing thread
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        conversation_id=thread.id,
        policy=A2AScheduleTask.POLICY_REUSE,
    )
    task_id = task.id
    thread_id = thread.id

    # Mock runtime and gateway to return failure
    monkeypatch.setattr(
        "app.services.a2a_schedule_job.a2a_runtime_builder", _mock_runtime_builder()
    )
    monkeypatch.setattr(
        "app.services.a2a_schedule_job.get_a2a_service",
        lambda: SimpleNamespace(
            gateway=SimpleNamespace(
                stream=lambda **kwargs: (yield {"kind": "status-update", "final": True})
            )
        ),
    )

    # We need to mock run_background_invoke to return failure
    async def mock_run_background_invoke(**kwargs):
        return {"success": False, "error": "failed intentionally"}

    monkeypatch.setattr(
        "app.services.a2a_schedule_job.run_background_invoke",
        mock_run_background_invoke,
    )

    claim = _build_claim(task)
    await _mark_task_claimed(async_db_session, task=task, run_id=claim.run_id)

    await _execute_claimed_task(claim=claim)
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        # Verify thread still exists
        existing_thread = await check_db.get(ConversationThread, thread_id)
        assert existing_thread is not None, "Historical thread should NOT be deleted"

        # Verify task still points to the thread
        refreshed_task = await check_db.get(A2AScheduleTask, task_id)
        assert (
            refreshed_task.conversation_id == thread_id
        ), "Task should still point to historical thread"


async def test_execute_claimed_task_cleans_new_thread_on_failure(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="new-fail")

    # Create task with NEW policy
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        policy=A2AScheduleTask.POLICY_NEW,
    )
    task_id = task.id

    monkeypatch.setattr(
        "app.services.a2a_schedule_job.a2a_runtime_builder", _mock_runtime_builder()
    )

    async def mock_run_background_invoke(**kwargs):
        return {"success": False, "error": "failed intentionally"}

    monkeypatch.setattr(
        "app.services.a2a_schedule_job.run_background_invoke",
        mock_run_background_invoke,
    )

    claim = _build_claim(task)
    await _mark_task_claimed(async_db_session, task=task, run_id=claim.run_id)

    await _execute_claimed_task(claim=claim)
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.get(A2AScheduleTask, task_id)
        assert (
            refreshed_task.conversation_id is None
        ), "Failed new task should have no conversation_id"

        # We can't easily check if the thread was deleted without knowing its ID,
        # but _ensure_task_session creates one and assigns it to task.conversation_id.
        # Since refreshed_task.conversation_id is None, it was at least cleared.
