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
from app.features.schedules.common import (
    A2AScheduleConflictError,
    A2AScheduleNotFoundError,
    A2AScheduleServiceBusyError,
    ClaimedA2AScheduleTask,
)
from app.features.schedules.job import (
    _derive_recovery_timeouts,
    _execute_claimed_task,
    _refresh_ops_metrics,
    _schedule_run_heartbeat_loop,
    _try_hold_dispatch_leader_lock,
    dispatch_due_a2a_schedules,
)
from app.features.schedules.service import a2a_schedule_service
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


__all__ = [
    "A2AAgentUnavailableError",
    "A2AScheduleConflictError",
    "A2AScheduleExecution",
    "A2AScheduleNotFoundError",
    "A2AScheduleServiceBusyError",
    "A2AScheduleTask",
    "AgentMessage",
    "AgentMessageBlock",
    "AsyncMock",
    "ClaimedA2AScheduleTask",
    "ConversationThread",
    "DBAPIError",
    "Mock",
    "SimpleNamespace",
    "User",
    "_FailingAsyncContextManager",
    "_FailingAsyncIterator",
    "_build_claim",
    "_create_agent",
    "_create_schedule_task",
    "_derive_recovery_timeouts",
    "_execute_claimed_task",
    "_mark_task_claimed",
    "_mock_gateway_stream",
    "_mock_runtime_builder",
    "_refresh_ops_metrics",
    "_schedule_run_heartbeat_loop",
    "_try_hold_dispatch_leader_lock",
    "a2a_schedule_service",
    "asynccontextmanager",
    "asyncio",
    "create_user",
    "dispatch_due_a2a_schedules",
    "logging",
    "ops_metrics",
    "pytest",
    "real_commit_safely",
    "select",
    "settings",
    "timedelta",
    "utc_now",
    "uuid4",
]
