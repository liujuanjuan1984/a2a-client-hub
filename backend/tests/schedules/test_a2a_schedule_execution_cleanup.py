from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.features.schedules import service as a2a_schedule_service_module
from app.features.schedules.service import a2a_schedule_service
from app.utils.timezone_util import utc_now
from tests.utils import create_a2a_agent, create_schedule_task, create_user

pytestmark = pytest.mark.integration


async def _create_agent(async_db_session, *, user_id):
    return await create_a2a_agent(
        async_db_session,
        user_id=user_id,
        suffix="cleanup-agent",
        name="Cleanup Agent",
        card_url="https://example.com/cleanup-agent",
    )


async def _create_task(async_db_session, *, user_id, agent_id):
    return await create_schedule_task(
        async_db_session,
        user_id=user_id,
        agent_id=agent_id,
        name="Cleanup Task",
        prompt="cleanup",
        next_run_at=utc_now(),
    )


@pytest.mark.asyncio
async def test_cleanup_terminal_executions_removes_only_old_terminal_rows(
    async_db_session,
) -> None:
    now = utc_now()
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id)
    task = await _create_task(async_db_session, user_id=user.id, agent_id=agent.id)
    pending_task = await _create_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
    )

    old_success = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=uuid4(),
        scheduled_for=now - timedelta(days=46),
        started_at=now - timedelta(days=46),
        finished_at=now - timedelta(days=45),
        status=A2AScheduleExecution.STATUS_SUCCESS,
    )
    old_failed_without_finished_at = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=uuid4(),
        scheduled_for=now - timedelta(days=41),
        started_at=now - timedelta(days=40),
        finished_at=None,
        status=A2AScheduleExecution.STATUS_FAILED,
        error_message="legacy failure row",
    )
    old_running = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=uuid4(),
        scheduled_for=now - timedelta(days=50),
        started_at=now - timedelta(days=50),
        last_heartbeat_at=now - timedelta(days=50),
        finished_at=None,
        status=A2AScheduleExecution.STATUS_RUNNING,
    )
    old_pending = A2AScheduleExecution(
        user_id=user.id,
        task_id=pending_task.id,
        run_id=uuid4(),
        scheduled_for=now - timedelta(days=60),
        started_at=None,
        finished_at=None,
        status=A2AScheduleExecution.STATUS_PENDING,
    )
    recent_success = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=uuid4(),
        scheduled_for=now - timedelta(days=5),
        started_at=now - timedelta(days=5),
        finished_at=now - timedelta(days=4),
        status=A2AScheduleExecution.STATUS_SUCCESS,
    )
    async_db_session.add_all(
        [
            old_success,
            old_failed_without_finished_at,
            old_running,
            old_pending,
            recent_success,
        ]
    )
    await async_db_session.commit()
    deleted_execution_ids = {old_success.id, old_failed_without_finished_at.id}

    total_deleted = 0
    while True:
        deleted_count = await a2a_schedule_service.cleanup_terminal_executions(
            async_db_session,
            now=now,
            retention_days=30,
            batch_size=10,
        )
        if deleted_count <= 0:
            break
        total_deleted += deleted_count

    assert total_deleted == 2

    remaining = (
        await async_db_session.scalars(
            select(A2AScheduleExecution).order_by(A2AScheduleExecution.id.asc())
        )
    ).all()
    remaining_statuses = {execution.status for execution in remaining}

    assert len(remaining) == 3
    assert A2AScheduleExecution.STATUS_RUNNING in remaining_statuses
    assert A2AScheduleExecution.STATUS_PENDING in remaining_statuses
    assert A2AScheduleExecution.STATUS_SUCCESS in remaining_statuses
    assert all(execution.id not in deleted_execution_ids for execution in remaining)


@pytest.mark.asyncio
async def test_cleanup_terminal_executions_honors_batch_size(async_db_session) -> None:
    now = utc_now()
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id)
    task = await _create_task(async_db_session, user_id=user.id, agent_id=agent.id)

    for days_ago in (45, 44):
        async_db_session.add(
            A2AScheduleExecution(
                user_id=user.id,
                task_id=task.id,
                run_id=uuid4(),
                scheduled_for=now - timedelta(days=days_ago + 1),
                started_at=now - timedelta(days=days_ago + 1),
                finished_at=now - timedelta(days=days_ago),
                status=A2AScheduleExecution.STATUS_SUCCESS,
            )
        )
    await async_db_session.commit()

    deleted_count = await a2a_schedule_service.cleanup_terminal_executions(
        async_db_session,
        now=now,
        retention_days=30,
        batch_size=1,
    )

    remaining_count = int(
        await async_db_session.scalar(select(func.count(A2AScheduleExecution.id))) or 0
    )
    assert deleted_count == 1
    assert remaining_count == 1


def test_ensure_schedule_execution_cleanup_job_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _DummyScheduler:
        def __init__(self) -> None:
            self.jobs: dict[str, dict[str, object]] = {}

        def get_job(self, job_id: str) -> dict[str, object] | None:
            return self.jobs.get(job_id)

        def add_job(self, func, *, id: str, **kwargs) -> None:
            self.jobs[id] = {"func": func, **kwargs}

    scheduler = _DummyScheduler()
    monkeypatch.setattr(
        a2a_schedule_service_module,
        "get_scheduler",
        lambda: scheduler,
    )

    a2a_schedule_service_module.ensure_a2a_schedule_execution_cleanup_job()
    a2a_schedule_service_module.ensure_a2a_schedule_execution_cleanup_job()

    assert len(scheduler.jobs) == 1
    job = scheduler.jobs["a2a-schedule-execution-cleanup-daily"]
    assert (
        job["func"] is a2a_schedule_service_module.cleanup_a2a_schedule_executions_job
    )


@pytest.mark.asyncio
async def test_cleanup_schedule_execution_job_drains_all_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_mock = AsyncMock(side_effect=[500, 500, 12])

    class _DummySessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr(
        a2a_schedule_service_module,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )
    monkeypatch.setattr(
        a2a_schedule_service_module.a2a_schedule_service,
        "cleanup_terminal_executions",
        cleanup_mock,
    )

    await a2a_schedule_service_module.cleanup_a2a_schedule_executions_job()

    assert cleanup_mock.await_count == 3
    assert all(
        call.kwargs["batch_size"] == 500 for call in cleanup_mock.await_args_list
    )
