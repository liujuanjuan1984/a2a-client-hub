from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.db.models.user import User
from app.db.transaction import commit_safely as real_commit_safely
from app.features.schedules.job import (
    _derive_recovery_timeouts,
    _execute_claimed_task,
    _refresh_ops_metrics,
    _schedule_run_heartbeat_loop,
    _try_hold_dispatch_leader_lock,
    dispatch_due_a2a_schedules,
)
from app.features.schedules.service import (
    A2AScheduleConflictError,
    A2AScheduleNotFoundError,
    A2AScheduleServiceBusyError,
    ClaimedA2AScheduleTask,
    a2a_schedule_service,
)
from app.integrations.a2a_client.errors import A2AAgentUnavailableError
from app.runtime.ops_metrics import ops_metrics
from app.utils.timezone_util import utc_now
from tests.support.utils import create_a2a_agent, create_schedule_task, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_create_agent = create_a2a_agent
_create_schedule_task = create_schedule_task


def _mock_runtime_builder():
    async def _build(_db, user_id, agent_id):  # noqa: ARG001
        return SimpleNamespace(
            agent_enabled=True,
            resolved=SimpleNamespace(
                name="Schedule Agent",
                url="https://example.com/schedule-agent",
                headers={},
            ),
        )

    return SimpleNamespace(build=_build)


async def _mark_task_claimed(session, *, task: A2AScheduleTask):
    run_id = uuid4()
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
    await session.refresh(task)
    return run_id


def _build_claim(task: A2AScheduleTask, *, run_id):
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
        run_id=run_id,
    )


def _mock_gateway_stream(*, events, first_event_delay: float = 0.0):
    preflight_client = SimpleNamespace(close=AsyncMock())

    async def _stream(**_kwargs):
        for index, event in enumerate(events):
            if index == 0 and first_event_delay > 0:
                await asyncio.sleep(first_event_delay)
            yield event

    @asynccontextmanager
    async def _open_invoke_session(**_kwargs):
        try:
            yield SimpleNamespace(
                client=preflight_client,
                policy=SimpleNamespace(value="fresh_snapshot"),
                is_shared=False,
            )
        finally:
            await preflight_client.close()

    return SimpleNamespace(
        stream=_stream,
        open_invoke_session=_open_invoke_session,
    )


class _FailingAsyncContextManager:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def __aenter__(self):
        raise self._error

    async def __aexit__(self, _exc_type, _exc, _tb):
        return False


class _FailingAsyncIterator:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise self._error


async def test_claim_next_pending_execution_obeys_agent_concurrency_limit(
    async_db_session,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent_a = await _create_agent(async_db_session, user_id=user.id, suffix="a")
    agent_b = await _create_agent(async_db_session, user_id=user.id, suffix="b")

    now = utc_now()
    task_a1 = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent_a.id,
        next_run_at=now,
    )
    await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent_a.id,
        next_run_at=now,
    )
    existing_run_id = uuid4()
    async_db_session.add(
        A2AScheduleExecution(
            user_id=user.id,
            task_id=task_a1.id,
            run_id=existing_run_id,
            scheduled_for=now - timedelta(minutes=1),
            started_at=now - timedelta(minutes=1),
            last_heartbeat_at=now - timedelta(seconds=30),
            status=A2AScheduleExecution.STATUS_RUNNING,
        )
    )
    task_b = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent_b.id,
        next_run_at=now,
    )
    await async_db_session.commit()

    monkeypatch.setattr(
        settings,
        "a2a_schedule_agent_concurrency_limit",
        1,
        raising=False,
    )

    await a2a_schedule_service.enqueue_due_tasks(async_db_session, now=now)
    claim = await a2a_schedule_service.claim_next_pending_execution(
        async_db_session, now=now
    )
    assert claim is not None
    assert claim.task_id == task_b.id


async def test_claim_next_pending_execution_obeys_global_concurrency_limit(
    async_db_session,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent_a = await _create_agent(async_db_session, user_id=user.id, suffix="global-a")
    agent_b = await _create_agent(async_db_session, user_id=user.id, suffix="global-b")
    now = utc_now()
    task_a = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent_a.id,
        next_run_at=now,
    )
    await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent_b.id,
        next_run_at=now,
    )
    running_run_id = uuid4()
    async_db_session.add(
        A2AScheduleExecution(
            user_id=user.id,
            task_id=task_a.id,
            run_id=running_run_id,
            scheduled_for=now - timedelta(minutes=1),
            started_at=now - timedelta(minutes=1),
            last_heartbeat_at=now - timedelta(seconds=20),
            status=A2AScheduleExecution.STATUS_RUNNING,
        )
    )
    await async_db_session.commit()

    monkeypatch.setattr(
        settings,
        "a2a_schedule_global_concurrency_limit",
        1,
        raising=False,
    )

    await a2a_schedule_service.enqueue_due_tasks(async_db_session, now=now)
    claim = await a2a_schedule_service.claim_next_pending_execution(
        async_db_session, now=now
    )
    assert claim is None


async def test_claim_next_pending_execution_creates_running_execution_immediately(
    async_db_session,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="claim-exec")
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )

    await a2a_schedule_service.enqueue_due_tasks(async_db_session, now=now)
    claim = await a2a_schedule_service.claim_next_pending_execution(
        async_db_session, now=now
    )
    assert claim is not None
    assert claim.task_id == task.id

    execution = await async_db_session.scalar(
        select(A2AScheduleExecution).where(
            A2AScheduleExecution.task_id == task.id,
            A2AScheduleExecution.run_id == claim.run_id,
        )
    )
    assert execution is not None
    assert execution.status == A2AScheduleExecution.STATUS_RUNNING
    assert execution.finished_at is None
    assert execution.scheduled_for == claim.scheduled_for


async def test_claim_next_pending_execution_sequential_holds_next_run_until_finalize(
    async_db_session,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="sequential")
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task.cycle_type = A2AScheduleTask.CYCLE_SEQUENTIAL
    task.time_point = {"minutes": 15}
    await async_db_session.commit()

    await a2a_schedule_service.enqueue_due_tasks(async_db_session, now=now)
    claim = await a2a_schedule_service.claim_next_pending_execution(
        async_db_session, now=now
    )
    assert claim is not None
    assert claim.task_id == task.id
    await async_db_session.refresh(task)
    assert task.last_run_status == A2AScheduleTask.STATUS_IDLE
    assert task.next_run_at is None


async def test_delete_running_task_marks_deferred_delete_and_hides_from_user_queries(
    async_db_session,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="deferred-delete"
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    run_id = await _mark_task_claimed(async_db_session, task=task)

    await a2a_schedule_service.delete_task(
        async_db_session,
        user_id=user.id,
        task_id=task.id,
    )
    await async_db_session.refresh(task)

    assert task.deleted_at is None
    assert task.delete_requested_at is not None
    assert task.enabled is False
    assert task.next_run_at is None
    execution = await async_db_session.scalar(
        select(A2AScheduleExecution).where(
            A2AScheduleExecution.task_id == task.id,
            A2AScheduleExecution.run_id == run_id,
        )
    )
    assert execution is not None
    assert execution.status == A2AScheduleExecution.STATUS_RUNNING

    with pytest.raises(A2AScheduleNotFoundError):
        await a2a_schedule_service.get_task(
            async_db_session,
            user_id=user.id,
            task_id=task.id,
        )


async def test_finalize_task_run_soft_deletes_when_delete_was_requested(
    async_db_session,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="finalize-delete"
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    run_id = await _mark_task_claimed(async_db_session, task=task)
    task.delete_requested_at = utc_now()
    task.enabled = False
    task.next_run_at = None
    await async_db_session.commit()

    finalized = await a2a_schedule_service.finalize_task_run(
        async_db_session,
        task_id=task.id,
        user_id=user.id,
        run_id=run_id,
        final_status=A2AScheduleTask.STATUS_SUCCESS,
        finished_at=utc_now(),
    )
    assert finalized is True
    await real_commit_safely(async_db_session)
    await async_db_session.refresh(task)

    assert task.deleted_at is not None
    assert task.delete_requested_at is None


async def test_delete_task_returns_conflict_when_row_locked(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="delete-lock")
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )

    async with async_session_maker() as lock_db:
        await lock_db.scalar(
            select(A2AScheduleTask)
            .where(A2AScheduleTask.id == task.id)
            .with_for_update(nowait=True)
            .limit(1)
        )
        async with async_session_maker() as actor_db:
            with pytest.raises(A2AScheduleConflictError):
                await a2a_schedule_service.delete_task(
                    actor_db,
                    user_id=user.id,
                    task_id=task.id,
                )
        await lock_db.rollback()


async def test_set_enabled_is_not_blocked_by_user_row_lock(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="set-enabled-user-lock"
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        enabled=False,
        next_run_at=now,
    )

    async with async_session_maker() as lock_db:
        await lock_db.scalar(
            select(User.id)
            .where(User.id == user.id)
            .with_for_update(nowait=True)
            .limit(1)
        )
        async with async_session_maker() as actor_db:
            updated = await a2a_schedule_service.set_enabled(
                actor_db,
                user_id=user.id,
                task_id=task.id,
                enabled=True,
                is_superuser=False,
                timezone_str="UTC",
            )
            assert updated.enabled is True
        await lock_db.rollback()


async def test_create_task_surfaces_service_busy_when_user_fk_check_is_blocked(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="create-user-lock"
    )

    async with async_session_maker() as lock_db:
        await lock_db.scalar(
            select(User.id)
            .where(User.id == user.id)
            .with_for_update(nowait=True)
            .limit(1)
        )
        async with async_session_maker() as actor_db:
            with pytest.raises(A2AScheduleServiceBusyError):
                await a2a_schedule_service.create_task(
                    actor_db,
                    user_id=user.id,
                    is_superuser=False,
                    timezone_str="UTC",
                    name="quota-lock-create",
                    agent_id=agent.id,
                    prompt="hello",
                    cycle_type=A2AScheduleTask.CYCLE_DAILY,
                    time_point={"time": "09:00"},
                    enabled=True,
                )
        await lock_db.rollback()


async def test_schedule_run_heartbeat_loop_classifies_lock_contention(
    monkeypatch,
    caplog,
) -> None:
    claim = ClaimedA2AScheduleTask(
        task_id=uuid4(),
        user_id=uuid4(),
        agent_id=uuid4(),
        conversation_id=None,
        name="heartbeat-lock",
        prompt="hello",
        cycle_type=A2AScheduleTask.CYCLE_DAILY,
        time_point={"time": "09:00"},
        scheduled_for=utc_now(),
        run_id=uuid4(),
    )
    stop_event = asyncio.Event()

    class _LockNotAvailableError(Exception):
        sqlstate = "55P03"

    async def _raise_lock_contention(*_args, **_kwargs):
        stop_event.set()
        raise DBAPIError(
            statement="UPDATE ... FOR UPDATE",
            params={},
            orig=_LockNotAvailableError("could not obtain lock on row"),
        )

    monkeypatch.setattr(
        "app.features.schedules.job._touch_schedule_run_heartbeat",
        _raise_lock_contention,
    )
    monkeypatch.setattr(
        settings,
        "a2a_schedule_run_heartbeat_interval_seconds",
        0.1,
        raising=False,
    )

    with caplog.at_level(logging.WARNING, logger="app.features.schedules.job"):
        await _schedule_run_heartbeat_loop(claim=claim, stop_event=stop_event)

    assert "lock contention" in caplog.text
    assert "Schedule heartbeat update failed" not in caplog.text


async def test_schedule_run_heartbeat_loop_classifies_statement_timeout(
    monkeypatch,
    caplog,
) -> None:
    before = ops_metrics.snapshot().get("schedule_db_query_timeouts", 0)
    claim = ClaimedA2AScheduleTask(
        task_id=uuid4(),
        user_id=uuid4(),
        agent_id=uuid4(),
        conversation_id=None,
        name="heartbeat-timeout",
        prompt="hello",
        cycle_type=A2AScheduleTask.CYCLE_DAILY,
        time_point={"time": "09:00"},
        scheduled_for=utc_now(),
        run_id=uuid4(),
    )
    stop_event = asyncio.Event()

    class _StatementTimeoutError(Exception):
        sqlstate = "57014"

    async def _raise_statement_timeout(*_args, **_kwargs):
        stop_event.set()
        raise DBAPIError(
            statement="UPDATE ...",
            params={},
            orig=_StatementTimeoutError("canceling statement due to statement timeout"),
        )

    monkeypatch.setattr(
        "app.features.schedules.job._touch_schedule_run_heartbeat",
        _raise_statement_timeout,
    )
    monkeypatch.setattr(
        settings,
        "a2a_schedule_run_heartbeat_interval_seconds",
        0.1,
        raising=False,
    )

    with caplog.at_level(logging.WARNING, logger="app.features.schedules.job"):
        await _schedule_run_heartbeat_loop(claim=claim, stop_event=stop_event)

    after = ops_metrics.snapshot().get("schedule_db_query_timeouts", 0)
    assert "database statement timeout" in caplog.text
    assert "Schedule heartbeat update failed" not in caplog.text
    assert int(after) >= int(before) + 1


async def test_execute_claimed_task_resets_consecutive_failures_on_success(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="success")
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id
    task.consecutive_failures = 3
    await async_db_session.commit()

    monkeypatch.setattr(
        "app.features.schedules.job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )
    monkeypatch.setattr(
        "app.features.schedules.job.get_a2a_service",
        lambda: SimpleNamespace(
            gateway=_mock_gateway_stream(
                events=[
                    {
                        "kind": "artifact-update",
                        "artifact": {
                            "parts": [{"kind": "text", "text": "all good"}],
                            "metadata": {
                                "opencode": {
                                    "block_type": "text",
                                    "message_id": "msg-success-1",
                                    "event_id": "evt-success-1",
                                }
                            },
                        },
                    },
                    {"kind": "status-update", "final": True},
                ]
            ),
        ),
    )

    run_id = await _mark_task_claimed(async_db_session, task=task)
    await _execute_claimed_task(claim=_build_claim(task, run_id=run_id))
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
    assert refreshed is not None
    assert refreshed.consecutive_failures == 0
    assert refreshed.last_run_status == A2AScheduleTask.STATUS_SUCCESS

    async with async_session_maker() as check_db:
        last_exec = await check_db.scalar(
            select(A2AScheduleExecution)
            .where(A2AScheduleExecution.task_id == task_id)
            .order_by(A2AScheduleExecution.started_at.desc())
        )

    assert last_exec is not None
    assert last_exec.status == A2AScheduleExecution.STATUS_SUCCESS
    assert last_exec.response_content == "all good"
    assert last_exec.conversation_id is not None
    assert last_exec.user_message_id is not None
    assert last_exec.agent_message_id is not None


async def test_execute_claimed_task_timeout_trips_failure_threshold(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="timeout")
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id

    monkeypatch.setattr(
        settings,
        "a2a_schedule_task_invoke_timeout",
        0.001,
        raising=False,
    )
    monkeypatch.setattr(
        settings,
        "a2a_schedule_task_failure_threshold",
        1,
        raising=False,
    )
    monkeypatch.setattr(
        settings,
        "a2a_schedule_task_stream_idle_timeout",
        5.0,
        raising=False,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )
    monkeypatch.setattr(
        "app.features.schedules.job.get_a2a_service",
        lambda: SimpleNamespace(
            gateway=_mock_gateway_stream(
                events=[
                    {"content": "should not reach"},
                    {"kind": "status-update", "final": True},
                ],
                first_event_delay=0.05,
            ),
        ),
    )

    run_id = await _mark_task_claimed(async_db_session, task=task)
    await _execute_claimed_task(claim=_build_claim(task, run_id=run_id))
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
    assert refreshed is not None
    assert refreshed.last_run_status == A2AScheduleTask.STATUS_FAILED
    assert refreshed.consecutive_failures == 1
    assert refreshed.enabled is False

    async with async_session_maker() as check_db:
        last_exec = await check_db.scalar(
            select(A2AScheduleExecution)
            .where(A2AScheduleExecution.task_id == task_id)
            .order_by(A2AScheduleExecution.started_at.desc())
        )

    assert last_exec is not None
    assert last_exec.conversation_id is not None


async def test_execute_claimed_task_timeout_persists_partial_stream_content(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="timeout-partial"
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id

    monkeypatch.setattr(
        settings,
        "a2a_schedule_task_invoke_timeout",
        0.02,
        raising=False,
    )
    monkeypatch.setattr(
        settings,
        "a2a_schedule_task_stream_idle_timeout",
        5.0,
        raising=False,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )

    async def _stream(**_kwargs):
        yield {
            "kind": "artifact-update",
            "artifact": {
                "parts": [{"kind": "text", "text": "partial response"}],
                "metadata": {
                    "opencode": {
                        "block_type": "text",
                        "message_id": "msg-timeout-partial",
                        "event_id": "evt-timeout-partial-1",
                    }
                },
            },
        }
        await asyncio.sleep(0.05)
        yield {"kind": "status-update", "final": True}

    preflight_client = SimpleNamespace(close=AsyncMock())

    @asynccontextmanager
    async def _open_invoke_session(**_kwargs):
        try:
            yield SimpleNamespace(
                client=preflight_client,
                policy=SimpleNamespace(value="fresh_snapshot"),
                is_shared=False,
            )
        finally:
            await preflight_client.close()

    monkeypatch.setattr(
        "app.features.schedules.job.get_a2a_service",
        lambda: SimpleNamespace(
            gateway=SimpleNamespace(
                stream=_stream,
                open_invoke_session=_open_invoke_session,
            )
        ),
    )

    run_id = await _mark_task_claimed(async_db_session, task=task)
    await _execute_claimed_task(claim=_build_claim(task, run_id=run_id))
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
        execution = await check_db.scalar(
            select(A2AScheduleExecution)
            .where(A2AScheduleExecution.task_id == task_id)
            .order_by(A2AScheduleExecution.started_at.desc())
        )
    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_FAILED
    assert execution is not None
    assert execution.status == A2AScheduleExecution.STATUS_FAILED
    assert execution.error_code == "timeout"
    assert execution.error_message == "A2A stream total timeout after 0.0s"
    assert execution.response_content == "partial response"
    assert execution.agent_message_id is not None

    async with async_session_maker() as check_db:
        agent_message = await check_db.scalar(
            select(AgentMessage).where(AgentMessage.id == execution.agent_message_id)
        )
    assert agent_message is not None
    metadata = agent_message.message_metadata
    assert isinstance(metadata, dict)
    assert metadata["success"] is False
    assert metadata["stream"]["schema_version"] == 1
    assert metadata["stream"]["finish_reason"] == "timeout_total"
    assert metadata["stream"]["error"]["error_code"] == "timeout"
    assert "block_count" not in metadata
    assert "message_blocks" not in metadata

    async with async_session_maker() as check_db:
        blocks = (
            await check_db.scalars(
                select(AgentMessageBlock)
                .where(AgentMessageBlock.message_id == execution.agent_message_id)
                .order_by(AgentMessageBlock.block_seq.asc())
            )
        ).all()
    assert blocks
    assert blocks[0].content == "partial response"


async def test_execute_claimed_task_runtime_failure_does_not_create_conversation(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="runtime-fail"
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id

    async def _build(_db, user_id, agent_id):  # noqa: ARG001
        raise RuntimeError("runtime build failed")

    monkeypatch.setattr(
        "app.features.schedules.job.a2a_runtime_builder",
        SimpleNamespace(build=_build),
    )

    run_id = await _mark_task_claimed(async_db_session, task=task)
    await _execute_claimed_task(claim=_build_claim(task, run_id=run_id))
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
        last_exec = await check_db.scalar(
            select(A2AScheduleExecution)
            .where(A2AScheduleExecution.task_id == task_id)
            .order_by(A2AScheduleExecution.started_at.desc())
        )

    assert refreshed_task is not None
    assert refreshed_task.conversation_id is None
    assert last_exec is not None
    assert last_exec.status == A2AScheduleExecution.STATUS_FAILED
    assert last_exec.conversation_id is None


async def test_execute_claimed_task_persists_structured_agent_unavailable_error(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="down")
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=utc_now(),
    )
    task_id = task.id

    monkeypatch.setattr(
        "app.features.schedules.job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )

    def _stream(**_kwargs):
        return _FailingAsyncIterator(A2AAgentUnavailableError("Agent card unavailable"))

    preflight_client = SimpleNamespace(close=AsyncMock())

    @asynccontextmanager
    async def _open_invoke_session(**_kwargs):
        try:
            yield SimpleNamespace(
                client=preflight_client,
                policy=SimpleNamespace(value="fresh_snapshot"),
                is_shared=False,
            )
        finally:
            await preflight_client.close()

    monkeypatch.setattr(
        "app.features.schedules.job.get_a2a_service",
        lambda: SimpleNamespace(
            gateway=SimpleNamespace(
                stream=_stream,
                open_invoke_session=_open_invoke_session,
            )
        ),
    )

    run_id = await _mark_task_claimed(async_db_session, task=task)
    await _execute_claimed_task(claim=_build_claim(task, run_id=run_id))
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        execution = await check_db.scalar(
            select(A2AScheduleExecution)
            .where(A2AScheduleExecution.task_id == task_id)
            .order_by(A2AScheduleExecution.started_at.desc())
        )

    assert execution is not None
    assert execution.status == A2AScheduleExecution.STATUS_FAILED
    assert execution.error_code == "agent_unavailable"
    assert execution.error_message == "Agent card unavailable"


async def test_execute_claimed_task_fails_fast_when_preflight_card_fetch_fails(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session,
        user_id=user.id,
        suffix="preflight-down",
    )
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=utc_now(),
    )
    task_id = task.id

    monkeypatch.setattr(
        "app.features.schedules.job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )

    def _open_invoke_session(**_kwargs):
        return _FailingAsyncContextManager(
            A2AAgentUnavailableError("Agent card unavailable")
        )

    monkeypatch.setattr(
        "app.features.schedules.job.get_a2a_service",
        lambda: SimpleNamespace(
            gateway=SimpleNamespace(
                open_invoke_session=_open_invoke_session,
            )
        ),
    )
    monkeypatch.setattr(
        "app.features.schedules.job._ensure_task_session",
        AsyncMock(side_effect=AssertionError("session should not be created")),
    )
    run_background_invoke_mock = AsyncMock()
    monkeypatch.setattr(
        "app.features.schedules.job.run_background_invoke",
        run_background_invoke_mock,
    )

    run_id = await _mark_task_claimed(async_db_session, task=task)
    await _execute_claimed_task(claim=_build_claim(task, run_id=run_id))
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        execution = await check_db.scalar(
            select(A2AScheduleExecution)
            .where(A2AScheduleExecution.task_id == task_id)
            .order_by(A2AScheduleExecution.started_at.desc())
        )

    assert execution is not None
    assert execution.status == A2AScheduleExecution.STATUS_FAILED
    assert execution.conversation_id is None
    assert execution.error_code == "agent_unavailable"
    assert execution.error_message == "Agent card unavailable"
    run_background_invoke_mock.assert_not_awaited()


async def test_execute_claimed_task_reuses_preflight_client_for_invoke(
    async_db_session,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session,
        user_id=user.id,
        suffix="preflight-reuse",
    )
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=utc_now(),
    )

    monkeypatch.setattr(
        "app.features.schedules.job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )

    preflight_client = SimpleNamespace(close=AsyncMock())
    run_background_invoke_mock = AsyncMock(
        return_value={
            "success": True,
            "response_content": "ok",
            "conversation_id": None,
            "message_refs": {},
            "context_id": None,
        }
    )

    @asynccontextmanager
    async def _open_invoke_session(**_kwargs):
        try:
            yield SimpleNamespace(
                client=preflight_client,
                policy=SimpleNamespace(value="fresh_snapshot"),
                is_shared=False,
            )
        finally:
            await preflight_client.close()

    gateway = SimpleNamespace(open_invoke_session=_open_invoke_session)
    monkeypatch.setattr(
        "app.features.schedules.job.get_a2a_service",
        lambda: SimpleNamespace(gateway=gateway),
    )
    monkeypatch.setattr(
        "app.features.schedules.job.run_background_invoke",
        run_background_invoke_mock,
    )

    run_id = await _mark_task_claimed(async_db_session, task=task)
    await _execute_claimed_task(claim=_build_claim(task, run_id=run_id))

    run_background_invoke_mock.assert_awaited_once()
    invoke_session = run_background_invoke_mock.await_args.kwargs["invoke_session"]
    assert invoke_session.client is preflight_client
    assert invoke_session.policy.value == "fresh_snapshot"
    preflight_client.close.assert_awaited_once()


async def test_execute_claimed_task_binds_external_session_identity_when_present(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="bind")
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id

    monkeypatch.setattr(
        "app.features.schedules.job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )
    monkeypatch.setattr(
        "app.features.schedules.job.get_a2a_service",
        lambda: SimpleNamespace(
            gateway=_mock_gateway_stream(
                events=[
                    {
                        "content": "bound",
                        "metadata": {
                            "provider": "opencode",
                            "externalSessionId": "ses_bind_1",
                        },
                    },
                    {"kind": "status-update", "final": True},
                ]
            ),
        ),
    )

    run_id = await _mark_task_claimed(async_db_session, task=task)
    await _execute_claimed_task(claim=_build_claim(task, run_id=run_id))
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
        assert refreshed_task is not None
        assert refreshed_task.conversation_id is not None

        thread = await check_db.scalar(
            select(ConversationThread).where(
                ConversationThread.id == refreshed_task.conversation_id
            )
        )
        last_exec = await check_db.scalar(
            select(A2AScheduleExecution)
            .where(A2AScheduleExecution.task_id == task_id)
            .order_by(A2AScheduleExecution.started_at.desc())
        )

    assert thread is not None
    assert thread.external_provider == "opencode"
    assert thread.external_session_id == "ses_bind_1"
    assert last_exec is not None
    assert last_exec.user_message_id is not None
    assert last_exec.agent_message_id is not None


async def test_execute_claimed_task_persists_readable_agent_content(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="readable-content"
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id

    monkeypatch.setattr(
        "app.features.schedules.job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )
    monkeypatch.setattr(
        "app.features.schedules.job.get_a2a_service",
        lambda: SimpleNamespace(
            gateway=_mock_gateway_stream(
                events=[
                    {
                        "kind": "artifact-update",
                        "artifact": {
                            "parts": [{"kind": "text", "text": "Readable answer"}],
                            "metadata": {
                                "opencode": {
                                    "block_type": "text",
                                    "message_id": "msg-readable-1",
                                    "event_id": "evt-readable-1",
                                }
                            },
                        },
                    },
                    {"kind": "status-update", "final": True},
                ]
            ),
        ),
    )

    run_id = await _mark_task_claimed(async_db_session, task=task)
    await _execute_claimed_task(claim=_build_claim(task, run_id=run_id))
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
        assert refreshed_task is not None
        messages = list(
            (
                await check_db.scalars(
                    select(AgentMessage)
                    .where(
                        AgentMessage.conversation_id == refreshed_task.conversation_id
                    )
                    .order_by(AgentMessage.created_at.asc())
                )
            ).all()
        )

    assert len(messages) >= 2
    agent_messages = [message for message in messages if message.sender == "agent"]
    assert agent_messages
    async with async_session_maker() as check_db:
        blocks = (
            await check_db.scalars(
                select(AgentMessageBlock)
                .where(AgentMessageBlock.message_id == agent_messages[-1].id)
                .order_by(AgentMessageBlock.block_seq.asc())
            )
        ).all()
    assert blocks


async def test_execute_claimed_task_creates_new_conversation_each_run(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="new-conv")
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id

    monkeypatch.setattr(
        "app.features.schedules.job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )
    monkeypatch.setattr(
        "app.features.schedules.job.get_a2a_service",
        lambda: SimpleNamespace(
            gateway=_mock_gateway_stream(
                events=[
                    {
                        "kind": "artifact-update",
                        "artifact": {
                            "parts": [{"kind": "text", "text": "ok"}],
                            "metadata": {
                                "opencode": {
                                    "block_type": "text",
                                    "message_id": "msg-new-conv-1",
                                    "event_id": "evt-new-conv-1",
                                }
                            },
                        },
                    },
                    {"kind": "status-update", "final": True},
                ]
            ),
        ),
    )

    first_run_id = await _mark_task_claimed(async_db_session, task=task)
    await _execute_claimed_task(claim=_build_claim(task, run_id=first_run_id))
    second_run_id = await _mark_task_claimed(async_db_session, task=task)
    await _execute_claimed_task(claim=_build_claim(task, run_id=second_run_id))
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        executions = list(
            (
                await check_db.scalars(
                    select(A2AScheduleExecution)
                    .where(A2AScheduleExecution.task_id == task_id)
                    .order_by(A2AScheduleExecution.started_at.desc())
                    .limit(2)
                )
            ).all()
        )
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )

    assert len(executions) == 2
    latest_conversation_id = executions[0].conversation_id
    previous_conversation_id = executions[1].conversation_id
    assert latest_conversation_id is not None
    assert previous_conversation_id is not None
    assert latest_conversation_id != previous_conversation_id
    assert refreshed_task is not None
    assert refreshed_task.conversation_id == latest_conversation_id


async def test_execute_claimed_task_skips_stale_run_id(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="stale-claim")
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id

    stale_claim = _build_claim(task, run_id=uuid4())
    await _execute_claimed_task(claim=stale_claim)
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
        executions = list(
            (
                await check_db.scalars(
                    select(A2AScheduleExecution).where(
                        A2AScheduleExecution.task_id == task_id
                    )
                )
            ).all()
        )

    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_IDLE
    assert executions == []


async def test_execute_claimed_task_does_not_side_write_execution_on_finalize_mismatch(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session,
        user_id=user.id,
        suffix="finalize-mismatch",
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id

    monkeypatch.setattr(
        "app.features.schedules.job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )

    @asynccontextmanager
    async def _open_invoke_session(**_kwargs):
        yield SimpleNamespace(
            client=SimpleNamespace(close=AsyncMock()),
            policy=SimpleNamespace(value="fresh_snapshot"),
            is_shared=False,
        )

    monkeypatch.setattr(
        "app.features.schedules.job.get_a2a_service",
        lambda: SimpleNamespace(
            gateway=SimpleNamespace(
                open_invoke_session=_open_invoke_session,
            )
        ),
    )

    async def _fake_run_background_invoke(**_kwargs):
        return {
            "success": True,
            "response_content": "should-not-persist-success",
            "message_refs": {},
        }

    monkeypatch.setattr(
        "app.features.schedules.job.run_background_invoke",
        _fake_run_background_invoke,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.finalize_task_run",
        AsyncMock(return_value=False),
    )

    run_id = await _mark_task_claimed(async_db_session, task=task)
    await _execute_claimed_task(claim=_build_claim(task, run_id=run_id))
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
        executions = list(
            (
                await check_db.scalars(
                    select(A2AScheduleExecution).where(
                        A2AScheduleExecution.task_id == task_id
                    )
                )
            ).all()
        )

    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_IDLE
    assert len(executions) == 1
    assert executions[0].status == A2AScheduleExecution.STATUS_RUNNING
    assert executions[0].finished_at is None


async def test_execute_claimed_task_does_not_side_write_execution_on_finalize_lock_conflict(
    async_db_session,
    async_session_maker,
    monkeypatch,
    caplog,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session,
        user_id=user.id,
        suffix="finalize-lock-conflict",
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id

    monkeypatch.setattr(
        "app.features.schedules.job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )

    @asynccontextmanager
    async def _open_invoke_session(**_kwargs):
        yield SimpleNamespace(
            client=SimpleNamespace(close=AsyncMock()),
            policy=SimpleNamespace(value="fresh_snapshot"),
            is_shared=False,
        )

    monkeypatch.setattr(
        "app.features.schedules.job.get_a2a_service",
        lambda: SimpleNamespace(
            gateway=SimpleNamespace(
                open_invoke_session=_open_invoke_session,
            )
        ),
    )

    async def _fake_run_background_invoke(**_kwargs):
        return {
            "success": True,
            "response_content": "should-not-persist-success",
            "message_refs": {},
        }

    monkeypatch.setattr(
        "app.features.schedules.job.run_background_invoke",
        _fake_run_background_invoke,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.finalize_task_run",
        AsyncMock(
            side_effect=A2AScheduleConflictError(
                "Task is currently locked by another operation; retry shortly."
            )
        ),
    )

    run_id = await _mark_task_claimed(async_db_session, task=task)
    with caplog.at_level(logging.WARNING, logger="app.features.schedules.job"):
        await _execute_claimed_task(claim=_build_claim(task, run_id=run_id))
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
        executions = list(
            (
                await check_db.scalars(
                    select(A2AScheduleExecution).where(
                        A2AScheduleExecution.task_id == task_id
                    )
                )
            ).all()
        )

    assert "finalize deferred due to lock contention" in caplog.text
    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_IDLE
    assert len(executions) == 1
    assert executions[0].status == A2AScheduleExecution.STATUS_RUNNING
    assert executions[0].finished_at is None


async def test_recover_stale_running_task_finalizes_matching_run(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="recover-run")
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id
    run_id = uuid4()
    stale_started_at = now - timedelta(minutes=30)
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=run_id,
        scheduled_for=stale_started_at,
        started_at=stale_started_at,
        last_heartbeat_at=stale_started_at,
        status=A2AScheduleExecution.STATUS_RUNNING,
    )
    async_db_session.add(execution)
    await async_db_session.commit()
    execution_id = execution.id

    recovered = await a2a_schedule_service.recover_stale_running_tasks(
        async_db_session,
        now=now,
        timeout_seconds=60,
    )
    assert recovered == 1
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
        refreshed_execution = await check_db.scalar(
            select(A2AScheduleExecution).where(A2AScheduleExecution.id == execution_id)
        )

    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_FAILED
    assert refreshed_execution is not None
    assert refreshed_execution.status == A2AScheduleExecution.STATUS_FAILED
    assert refreshed_execution.finished_at is not None


async def test_recover_stale_running_task_soft_deletes_when_delete_was_requested(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session,
        user_id=user.id,
        suffix="recover-soft-delete",
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id
    run_id = uuid4()
    stale_started_at = now - timedelta(minutes=30)
    task.delete_requested_at = now - timedelta(minutes=1)
    task.enabled = False
    task.next_run_at = None
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=run_id,
        scheduled_for=stale_started_at,
        started_at=stale_started_at,
        last_heartbeat_at=stale_started_at,
        status=A2AScheduleExecution.STATUS_RUNNING,
    )
    async_db_session.add(execution)
    await async_db_session.commit()

    recovered = await a2a_schedule_service.recover_stale_running_tasks(
        async_db_session,
        now=now,
        timeout_seconds=60,
    )
    assert recovered == 1
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
        refreshed_execution = await check_db.scalar(
            select(A2AScheduleExecution).where(
                A2AScheduleExecution.task_id == task_id,
                A2AScheduleExecution.run_id == run_id,
            )
        )

    assert refreshed_task is not None
    assert refreshed_task.deleted_at is not None
    assert refreshed_task.delete_requested_at is None
    assert refreshed_execution is not None
    assert refreshed_execution.status == A2AScheduleExecution.STATUS_FAILED


async def test_recover_stale_running_task_skips_when_heartbeat_recent(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="recover-recent-heartbeat"
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id
    run_id = uuid4()
    stale_started_at = now - timedelta(minutes=30)
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=run_id,
        scheduled_for=stale_started_at,
        started_at=stale_started_at,
        last_heartbeat_at=now - timedelta(seconds=30),
        status=A2AScheduleExecution.STATUS_RUNNING,
    )
    async_db_session.add(execution)
    await async_db_session.commit()
    execution_id = execution.id

    recovered = await a2a_schedule_service.recover_stale_running_tasks(
        async_db_session,
        now=now,
        timeout_seconds=60,
        hard_timeout_seconds=3600,
    )
    assert recovered == 0
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
        refreshed_execution = await check_db.scalar(
            select(A2AScheduleExecution).where(A2AScheduleExecution.id == execution_id)
        )

    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_IDLE
    assert refreshed_execution is not None
    assert refreshed_execution.status == A2AScheduleExecution.STATUS_RUNNING
    assert refreshed_execution.finished_at is None


async def test_recover_stale_running_task_hard_timeout_wins_over_recent_heartbeat(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="recover-hard-timeout"
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id
    run_id = uuid4()
    stale_started_at = now - timedelta(minutes=30)
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=run_id,
        scheduled_for=stale_started_at,
        started_at=stale_started_at,
        last_heartbeat_at=now - timedelta(seconds=10),
        status=A2AScheduleExecution.STATUS_RUNNING,
    )
    async_db_session.add(execution)
    await async_db_session.commit()
    execution_id = execution.id

    recovered = await a2a_schedule_service.recover_stale_running_tasks(
        async_db_session,
        now=now,
        timeout_seconds=60,
        hard_timeout_seconds=60,
    )
    assert recovered == 1
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
        refreshed_execution = await check_db.scalar(
            select(A2AScheduleExecution).where(A2AScheduleExecution.id == execution_id)
        )

    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_FAILED
    assert refreshed_execution is not None
    assert refreshed_execution.status == A2AScheduleExecution.STATUS_FAILED
    assert refreshed_execution.finished_at is not None


async def test_recover_stale_running_task_requires_execution_row(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="recover-missing-exec"
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id

    recovered = await a2a_schedule_service.recover_stale_running_tasks(
        async_db_session,
        now=now,
        timeout_seconds=60,
    )
    assert recovered == 0
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )

    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_IDLE


async def test_recover_stale_sequential_task_reschedules_next_run(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session,
        user_id=user.id,
        suffix="recover-sequential",
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id
    run_id = uuid4()
    stale_started_at = now - timedelta(minutes=30)
    task.cycle_type = A2AScheduleTask.CYCLE_SEQUENTIAL
    task.time_point = {"minutes": 60}
    task.next_run_at = None
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=run_id,
        scheduled_for=stale_started_at,
        started_at=stale_started_at,
        last_heartbeat_at=stale_started_at,
        status=A2AScheduleExecution.STATUS_RUNNING,
    )
    async_db_session.add(execution)
    await async_db_session.commit()

    recovered = await a2a_schedule_service.recover_stale_running_tasks(
        async_db_session,
        now=now,
        timeout_seconds=60,
    )
    assert recovered == 1
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )

    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_FAILED
    assert refreshed_task.next_run_at is not None
    assert refreshed_task.next_run_at >= now + timedelta(minutes=59)


async def test_recover_stale_running_tasks_commits_per_recovered_task(
    async_db_session,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    now = utc_now()
    stale_started_at = now - timedelta(minutes=30)

    for suffix in ("recover-commit-a", "recover-commit-b"):
        agent = await _create_agent(async_db_session, user_id=user.id, suffix=suffix)
        task = await _create_schedule_task(
            async_db_session,
            user_id=user.id,
            agent_id=agent.id,
            next_run_at=now,
        )
        run_id = uuid4()
        execution = A2AScheduleExecution(
            user_id=user.id,
            task_id=task.id,
            run_id=run_id,
            scheduled_for=stale_started_at,
            started_at=stale_started_at,
            last_heartbeat_at=stale_started_at,
            status=A2AScheduleExecution.STATUS_RUNNING,
        )
        async_db_session.add(execution)
    await async_db_session.commit()

    commit_call_count = 0
    timeout_apply_call_count = 0

    async def _counting_commit(db):
        nonlocal commit_call_count
        commit_call_count += 1
        await real_commit_safely(db)

    async def _counting_set_timeouts(*_args, **_kwargs):
        nonlocal timeout_apply_call_count
        timeout_apply_call_count += 1

    monkeypatch.setattr(
        "app.features.schedules.dispatch.commit_safely",
        _counting_commit,
    )
    monkeypatch.setattr(
        "app.features.schedules.support.set_postgres_local_timeouts",
        _counting_set_timeouts,
    )

    recovered = await a2a_schedule_service.recover_stale_running_tasks(
        async_db_session,
        now=now,
        timeout_seconds=60,
    )
    assert recovered == 2
    assert commit_call_count >= recovered
    # Two recovered tasks plus one terminating loop iteration (no row found).
    assert timeout_apply_call_count >= recovered + 1


async def test_dispatch_due_a2a_schedules_skips_cycle_when_db_connection_refused(
    async_db_session,  # noqa: ARG001
    monkeypatch,
    caplog,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()

    async def _raise_connection_refused(*_args, **_kwargs):
        raise ConnectionRefusedError("db unavailable")

    monkeypatch.setattr(
        "app.features.schedules.job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        _raise_connection_refused,
    )

    with caplog.at_level(logging.WARNING, logger="app.features.schedules.job"):
        await dispatch_due_a2a_schedules(batch_size=1)

    assert ensure_workers_mock.await_count == 0
    assert refresh_metrics_mock.await_count == 0
    assert "database connectivity issue during stale-task recovery." in caplog.text


async def test_dispatch_due_a2a_schedules_continues_when_recovery_hits_lock_contention(
    async_db_session,  # noqa: ARG001
    monkeypatch,
    caplog,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()
    enqueue_mock = AsyncMock(return_value=0)

    class _LockNotAvailableError(Exception):
        sqlstate = "55P03"

    async def _raise_lock_contention(*_args, **_kwargs):
        raise DBAPIError(
            statement="SELECT ... FOR UPDATE SKIP LOCKED",
            params={},
            orig=_LockNotAvailableError("could not obtain lock on row"),
        )

    monkeypatch.setattr(
        "app.features.schedules.job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        _raise_lock_contention,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.enqueue_due_tasks",
        enqueue_mock,
    )

    with caplog.at_level(logging.WARNING, logger="app.features.schedules.job"):
        await dispatch_due_a2a_schedules(batch_size=1)

    assert ensure_workers_mock.await_count == 1
    assert enqueue_mock.await_count == 1
    assert refresh_metrics_mock.await_count == 1
    assert (
        "Skip stale-task recovery this cycle due to lock contention; continue dispatch."
        in caplog.text
    )


async def test_dispatch_due_a2a_schedules_skips_when_leader_lock_not_acquired(
    async_db_session,  # noqa: ARG001
    monkeypatch,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()
    recover_mock = AsyncMock(return_value=0)
    enqueue_mock = AsyncMock(return_value=0)

    class _NoLeaderLockContext:
        async def __aenter__(self):
            return False

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setattr(
        "app.features.schedules.job._try_hold_dispatch_leader_lock",
        lambda: _NoLeaderLockContext(),
    )
    monkeypatch.setattr(
        "app.features.schedules.job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        recover_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.enqueue_due_tasks",
        enqueue_mock,
    )

    await dispatch_due_a2a_schedules(batch_size=1)

    assert recover_mock.await_count == 0
    assert enqueue_mock.await_count == 0
    assert ensure_workers_mock.await_count == 0
    assert refresh_metrics_mock.await_count == 0


async def test_try_hold_dispatch_leader_lock_rolls_back_open_transaction(
    monkeypatch,
) -> None:
    class _FakeConn:
        def __init__(self) -> None:
            self.scalar_calls = 0
            self.rollback_calls = 0
            self.invalidate_calls = 0
            self.dialect = SimpleNamespace(name="postgresql")

        async def scalar(self, *_args, **_kwargs):
            self.scalar_calls += 1
            return True

        async def rollback(self):
            self.rollback_calls += 1

        async def invalidate(self, *_args, **_kwargs):
            self.invalidate_calls += 1

    fake_conn = _FakeConn()

    class _FakeConnContext:
        async def __aenter__(self):
            return fake_conn

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setattr(
        "app.features.schedules.job.async_engine",
        SimpleNamespace(connect=lambda: _FakeConnContext()),
    )

    async with _try_hold_dispatch_leader_lock() as has_leader_lock:
        assert has_leader_lock is True

    assert fake_conn.scalar_calls == 2
    assert fake_conn.rollback_calls >= 2
    assert fake_conn.invalidate_calls == 0


async def test_try_hold_dispatch_leader_lock_invalidates_connection_on_unlock_failure(
    monkeypatch,
    caplog,
) -> None:
    class _FakeConn:
        def __init__(self) -> None:
            self.scalar_calls = 0
            self.rollback_calls = 0
            self.invalidate_calls = 0
            self.dialect = SimpleNamespace(name="postgresql")

        async def scalar(self, *_args, **_kwargs):
            self.scalar_calls += 1
            if self.scalar_calls == 1:
                return True
            return False

        async def rollback(self):
            self.rollback_calls += 1

        async def invalidate(self, *_args, **_kwargs):
            self.invalidate_calls += 1

    fake_conn = _FakeConn()

    class _FakeConnContext:
        async def __aenter__(self):
            return fake_conn

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setattr(
        "app.features.schedules.job.async_engine",
        SimpleNamespace(connect=lambda: _FakeConnContext()),
    )

    with caplog.at_level(logging.ERROR, logger="app.features.schedules.job"):
        async with _try_hold_dispatch_leader_lock() as has_leader_lock:
            assert has_leader_lock is True

    assert fake_conn.invalidate_calls == 1
    assert (
        "Failed to release A2A schedule advisory leader lock because lock was no longer held."
        in caplog.text
    )


async def test_dispatch_due_a2a_schedules_skips_cycle_when_enqueue_db_connection_refused(
    async_db_session,  # noqa: ARG001
    monkeypatch,
    caplog,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()

    async def _recover_ok(*_args, **_kwargs):
        return 0

    async def _enqueue_raises(*_args, **_kwargs):
        raise ConnectionRefusedError("db unavailable")

    monkeypatch.setattr(
        "app.features.schedules.job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        _recover_ok,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.enqueue_due_tasks",
        _enqueue_raises,
    )

    with caplog.at_level(logging.WARNING, logger="app.features.schedules.job"):
        await dispatch_due_a2a_schedules(batch_size=1)

    assert ensure_workers_mock.await_count == 1
    assert refresh_metrics_mock.await_count == 0
    assert "database connectivity issue while enqueuing due tasks." in caplog.text


async def test_dispatch_due_a2a_schedules_stops_enqueue_when_enqueue_hits_statement_timeout(
    async_db_session,  # noqa: ARG001
    monkeypatch,
    caplog,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()

    async def _recover_ok(*_args, **_kwargs):
        return 0

    class _StatementTimeoutError(Exception):
        sqlstate = "57014"

    async def _enqueue_timeout(*_args, **_kwargs):
        raise DBAPIError(
            statement="SET LOCAL statement_timeout = '5000ms'",
            params={},
            orig=_StatementTimeoutError("canceling statement due to statement timeout"),
        )

    monkeypatch.setattr(
        "app.features.schedules.job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        _recover_ok,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.enqueue_due_tasks",
        _enqueue_timeout,
    )

    with caplog.at_level(logging.WARNING, logger="app.features.schedules.job"):
        await dispatch_due_a2a_schedules(batch_size=2)

    assert ensure_workers_mock.await_count == 1
    assert refresh_metrics_mock.await_count == 1
    assert (
        "Stop enqueuing due tasks this cycle due to database statement timeout."
        in caplog.text
    )


async def test_dispatch_due_a2a_schedules_reraises_non_connectivity_errors(
    async_db_session,  # noqa: ARG001
    monkeypatch,
) -> None:
    async def _raise_unexpected(*_args, **_kwargs):
        raise RuntimeError("unexpected recovery failure")

    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        _raise_unexpected,
    )

    with pytest.raises(RuntimeError, match="unexpected recovery failure"):
        await dispatch_due_a2a_schedules(batch_size=1)


async def test_derive_recovery_timeouts_clamps_heartbeat_stale_to_invoke_timeout(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "a2a_schedule_task_invoke_timeout",
        45.0,
        raising=False,
    )
    monkeypatch.setattr(
        settings,
        "a2a_schedule_run_heartbeat_interval_seconds",
        20.0,
        raising=False,
    )

    heartbeat_timeout_seconds, hard_timeout_seconds = _derive_recovery_timeouts()

    assert heartbeat_timeout_seconds == 45
    assert hard_timeout_seconds == 45


async def test_dispatch_due_a2a_schedules_passes_heartbeat_and_hard_timeout(
    async_db_session,  # noqa: ARG001
    monkeypatch,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()
    recover_mock = AsyncMock(return_value=0)
    enqueue_mock = AsyncMock(return_value=0)

    monkeypatch.setattr(
        settings,
        "a2a_schedule_task_invoke_timeout",
        200.0,
        raising=False,
    )
    monkeypatch.setattr(
        settings,
        "a2a_schedule_run_heartbeat_interval_seconds",
        20.0,
        raising=False,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        recover_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.enqueue_due_tasks",
        enqueue_mock,
    )

    await dispatch_due_a2a_schedules(batch_size=1)

    assert recover_mock.await_count == 1
    call_kwargs = recover_mock.await_args.kwargs
    assert call_kwargs["timeout_seconds"] == 60
    assert call_kwargs["hard_timeout_seconds"] == 200
    assert ensure_workers_mock.await_count == 1
    assert refresh_metrics_mock.await_count == 1


async def test_dispatch_due_a2a_schedules_clamps_stale_timeout_to_invoke_timeout(
    async_db_session,  # noqa: ARG001
    monkeypatch,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()
    recover_mock = AsyncMock(return_value=0)
    enqueue_mock = AsyncMock(return_value=0)

    monkeypatch.setattr(
        settings,
        "a2a_schedule_task_invoke_timeout",
        45.0,
        raising=False,
    )
    monkeypatch.setattr(
        settings,
        "a2a_schedule_run_heartbeat_interval_seconds",
        20.0,
        raising=False,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        recover_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.enqueue_due_tasks",
        enqueue_mock,
    )

    await dispatch_due_a2a_schedules(batch_size=1)

    assert recover_mock.await_count == 1
    call_kwargs = recover_mock.await_args.kwargs
    assert call_kwargs["timeout_seconds"] == 45
    assert call_kwargs["hard_timeout_seconds"] == 45
    assert ensure_workers_mock.await_count == 1
    assert refresh_metrics_mock.await_count == 1


async def test_refresh_ops_metrics_skips_when_db_connection_refused(
    monkeypatch,
    caplog,
) -> None:
    class _RefusedSessionContext:
        async def __aenter__(self):
            raise ConnectionRefusedError("db unavailable")

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setattr(
        "app.features.schedules.job.AsyncSessionLocal",
        lambda: _RefusedSessionContext(),
    )

    with caplog.at_level(logging.WARNING, logger="app.features.schedules.job"):
        await _refresh_ops_metrics()

    assert (
        "Skip schedule ops metrics refresh due to database connectivity issue."
        in caplog.text
    )


async def test_refresh_ops_metrics_refreshes_db_pool_checked_out(
    monkeypatch,
) -> None:
    class _HealthySession:
        async def scalar(self, statement):
            statement_sql = str(statement)
            if "pg_stat_activity" in statement_sql:
                return 1
            return 2

    class _HealthySessionContext:
        async def __aenter__(self):
            return _HealthySession()

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    fake_pool = object()
    refresh_mock = Mock()

    monkeypatch.setattr(
        "app.features.schedules.job.AsyncSessionLocal",
        lambda: _HealthySessionContext(),
    )
    monkeypatch.setattr(
        "app.features.schedules.job.async_engine",
        SimpleNamespace(sync_engine=SimpleNamespace(pool=fake_pool)),
    )
    monkeypatch.setattr(
        "app.features.schedules.job.refresh_db_pool_checked_out",
        refresh_mock,
    )

    await _refresh_ops_metrics()

    assert ops_metrics.snapshot()["schedule_running_task_count"] == 2
    assert ops_metrics.snapshot()["db_idle_in_tx_count"] == 1
    refresh_mock.assert_called_once_with(fake_pool)
