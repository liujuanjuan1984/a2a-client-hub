from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.services import a2a_schedule_service as a2a_schedule_service_module
from app.services.a2a_schedule_service import a2a_schedule_service
from app.utils.timezone_util import utc_now
from tests.utils import create_user

pytestmark = pytest.mark.integration


async def _create_agent(async_db_session, *, user_id):
    agent = A2AAgent(
        user_id=user_id,
        name="Cleanup Agent",
        card_url="https://example.com/cleanup-agent",
        auth_type="none",
        enabled=True,
    )
    async_db_session.add(agent)
    await async_db_session.commit()
    await async_db_session.refresh(agent)
    return agent


async def _create_task(async_db_session, *, user_id, agent_id):
    task = A2AScheduleTask(
        user_id=user_id,
        name="Cleanup Task",
        agent_id=agent_id,
        prompt="cleanup",
        cycle_type=A2AScheduleTask.CYCLE_DAILY,
        time_point={"time": "09:00"},
        enabled=True,
        next_run_at=utc_now(),
        consecutive_failures=0,
    )
    async_db_session.add(task)
    await async_db_session.commit()
    await async_db_session.refresh(task)
    return task


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

    deleted_count = await a2a_schedule_service.cleanup_terminal_executions(
        async_db_session,
        now=now,
        retention_days=30,
        batch_size=10,
    )

    assert deleted_count == 2

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
    assert all(
        execution.id not in {old_success.id, old_failed_without_finished_at.id}
        for execution in remaining
    )


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
