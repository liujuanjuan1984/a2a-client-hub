from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.services.a2a_schedule_job import (
    _execute_claimed_task,
    _refresh_ops_metrics,
    dispatch_due_a2a_schedules,
)
from app.services.a2a_schedule_service import (
    ClaimedA2AScheduleTask,
    a2a_schedule_service,
)
from app.utils.timezone_util import utc_now
from tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _create_agent(session, *, user_id, suffix: str) -> A2AAgent:
    agent = A2AAgent(
        user_id=user_id,
        name=f"Agent {suffix}",
        card_url=f"https://example.com/{suffix}",
        auth_type="none",
        enabled=True,
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def _create_schedule_task(
    session,
    *,
    user_id,
    agent_id,
    enabled: bool = True,
    next_run_at,
) -> A2AScheduleTask:
    task = A2AScheduleTask(
        user_id=user_id,
        name="Test schedule",
        agent_id=agent_id,
        prompt="hello",
        cycle_type=A2AScheduleTask.CYCLE_DAILY,
        time_point={"time": "09:00"},
        enabled=enabled,
        next_run_at=next_run_at,
        consecutive_failures=0,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


def _mock_runtime_builder():
    async def _build(_db, user_id, agent_id):  # noqa: ARG001
        return SimpleNamespace(
            agent=SimpleNamespace(enabled=True),
            resolved=SimpleNamespace(name="Schedule Agent"),
        )

    return SimpleNamespace(build=_build)


async def _mark_task_claimed(session, *, task: A2AScheduleTask):
    run_id = uuid4()
    task.current_run_id = run_id
    task.running_started_at = utc_now()
    task.last_run_status = A2AScheduleTask.STATUS_RUNNING
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
    async def _stream(**_kwargs):
        for index, event in enumerate(events):
            if index == 0 and first_event_delay > 0:
                await asyncio.sleep(first_event_delay)
            yield event

    return SimpleNamespace(stream=_stream)


async def test_claim_next_due_task_obeys_agent_concurrency_limit(
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
    async_db_session.add(
        A2AScheduleExecution(
            user_id=user.id,
            task_id=task_a1.id,
            run_id=uuid4(),
            scheduled_for=now - timedelta(minutes=1),
            started_at=now - timedelta(minutes=1),
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

    claim = await a2a_schedule_service.claim_next_due_task(async_db_session, now=now)
    assert claim is not None
    assert claim.task_id == task_b.id


async def test_claim_next_due_task_sequential_holds_next_run_until_finalize(
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

    claim = await a2a_schedule_service.claim_next_due_task(async_db_session, now=now)
    assert claim is not None
    assert claim.task_id == task.id
    await async_db_session.refresh(task)
    assert task.last_run_status == A2AScheduleTask.STATUS_RUNNING
    assert task.current_run_id is not None
    assert task.next_run_at is None


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
        "app.services.a2a_schedule_job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )
    monkeypatch.setattr(
        "app.services.a2a_schedule_job.get_a2a_service",
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
        "app.services.a2a_schedule_job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )
    monkeypatch.setattr(
        "app.services.a2a_schedule_job.get_a2a_service",
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
        "app.services.a2a_schedule_job.a2a_runtime_builder",
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

    monkeypatch.setattr(
        "app.services.a2a_schedule_job.get_a2a_service",
        lambda: SimpleNamespace(gateway=SimpleNamespace(stream=_stream)),
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
        "app.services.a2a_schedule_job.a2a_runtime_builder",
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
        "app.services.a2a_schedule_job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )
    monkeypatch.setattr(
        "app.services.a2a_schedule_job.get_a2a_service",
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
        "app.services.a2a_schedule_job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )
    monkeypatch.setattr(
        "app.services.a2a_schedule_job.get_a2a_service",
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
        "app.services.a2a_schedule_job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )
    monkeypatch.setattr(
        "app.services.a2a_schedule_job.get_a2a_service",
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
    task.last_run_status = A2AScheduleTask.STATUS_RUNNING
    task.current_run_id = uuid4()
    task.running_started_at = now
    await async_db_session.commit()

    stale_claim = _build_claim(task, run_id=uuid4())
    await _execute_claimed_task(claim=stale_claim)
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task.id)
        )
        executions = list(
            (
                await check_db.scalars(
                    select(A2AScheduleExecution).where(
                        A2AScheduleExecution.task_id == task.id
                    )
                )
            ).all()
        )

    assert refreshed_task is not None
    assert refreshed_task.current_run_id is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_RUNNING
    assert executions == []


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
    task.last_run_status = A2AScheduleTask.STATUS_RUNNING
    task.current_run_id = run_id
    task.running_started_at = stale_started_at
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=run_id,
        scheduled_for=stale_started_at,
        started_at=stale_started_at,
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
    assert refreshed_task.current_run_id is None
    assert refreshed_task.running_started_at is None
    assert refreshed_execution is not None
    assert refreshed_execution.status == A2AScheduleExecution.STATUS_FAILED
    assert refreshed_execution.finished_at is not None


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
    task.last_run_status = A2AScheduleTask.STATUS_RUNNING
    task.current_run_id = run_id
    task.running_started_at = stale_started_at
    task.last_heartbeat_at = now - timedelta(seconds=30)
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=run_id,
        scheduled_for=stale_started_at,
        started_at=stale_started_at,
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
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_RUNNING
    assert refreshed_task.current_run_id == run_id
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
    task.last_run_status = A2AScheduleTask.STATUS_RUNNING
    task.current_run_id = run_id
    task.running_started_at = stale_started_at
    task.last_heartbeat_at = now - timedelta(seconds=10)
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=run_id,
        scheduled_for=stale_started_at,
        started_at=stale_started_at,
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
    assert refreshed_task.current_run_id is None
    assert refreshed_execution is not None
    assert refreshed_execution.status == A2AScheduleExecution.STATUS_FAILED
    assert refreshed_execution.finished_at is not None


async def test_recover_stale_running_task_backfills_missing_execution(
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
    run_id = uuid4()
    stale_started_at = now - timedelta(minutes=30)
    task.last_run_status = A2AScheduleTask.STATUS_RUNNING
    task.current_run_id = run_id
    task.running_started_at = stale_started_at
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
            select(A2AScheduleTask).where(A2AScheduleTask.id == task.id)
        )
        executions = list(
            (
                await check_db.scalars(
                    select(A2AScheduleExecution).where(
                        A2AScheduleExecution.task_id == task.id,
                        A2AScheduleExecution.run_id == run_id,
                    )
                )
            ).all()
        )

    assert refreshed_task is not None
    assert refreshed_task.current_run_id is None
    assert refreshed_task.running_started_at is None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_FAILED
    assert len(executions) == 1
    assert executions[0].status == A2AScheduleExecution.STATUS_FAILED


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
    run_id = uuid4()
    stale_started_at = now - timedelta(minutes=30)
    task.cycle_type = A2AScheduleTask.CYCLE_SEQUENTIAL
    task.time_point = {"minutes": 60}
    task.last_run_status = A2AScheduleTask.STATUS_RUNNING
    task.current_run_id = run_id
    task.running_started_at = stale_started_at
    task.next_run_at = None
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=run_id,
        scheduled_for=stale_started_at,
        started_at=stale_started_at,
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
            select(A2AScheduleTask).where(A2AScheduleTask.id == task.id)
        )

    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_FAILED
    assert refreshed_task.current_run_id is None
    assert refreshed_task.running_started_at is None
    assert refreshed_task.next_run_at is not None
    assert refreshed_task.next_run_at >= now + timedelta(minutes=59)


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
        "app.services.a2a_schedule_job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.services.a2a_schedule_job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.services.a2a_schedule_job.a2a_schedule_service.recover_stale_running_tasks",
        _raise_connection_refused,
    )

    with caplog.at_level(logging.WARNING, logger="app.services.a2a_schedule_job"):
        await dispatch_due_a2a_schedules(batch_size=1)

    assert ensure_workers_mock.await_count == 0
    assert refresh_metrics_mock.await_count == 0
    assert "database connectivity issue during stale-task recovery." in caplog.text


async def test_dispatch_due_a2a_schedules_skips_cycle_when_claim_db_connection_refused(
    async_db_session,  # noqa: ARG001
    monkeypatch,
    caplog,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()

    async def _recover_ok(*_args, **_kwargs):
        return 0

    async def _claim_raises(*_args, **_kwargs):
        raise ConnectionRefusedError("db unavailable")

    monkeypatch.setattr(
        "app.services.a2a_schedule_job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.services.a2a_schedule_job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.services.a2a_schedule_job.a2a_schedule_service.recover_stale_running_tasks",
        _recover_ok,
    )
    monkeypatch.setattr(
        "app.services.a2a_schedule_job.a2a_schedule_service.claim_next_due_task",
        _claim_raises,
    )

    with caplog.at_level(logging.WARNING, logger="app.services.a2a_schedule_job"):
        await dispatch_due_a2a_schedules(batch_size=1)

    assert ensure_workers_mock.await_count == 1
    assert refresh_metrics_mock.await_count == 0
    assert "database connectivity issue while claiming due tasks." in caplog.text


async def test_dispatch_due_a2a_schedules_reraises_non_connectivity_errors(
    async_db_session,  # noqa: ARG001
    monkeypatch,
) -> None:
    async def _raise_unexpected(*_args, **_kwargs):
        raise RuntimeError("unexpected recovery failure")

    monkeypatch.setattr(
        "app.services.a2a_schedule_job.a2a_schedule_service.recover_stale_running_tasks",
        _raise_unexpected,
    )

    with pytest.raises(RuntimeError, match="unexpected recovery failure"):
        await dispatch_due_a2a_schedules(batch_size=1)


async def test_dispatch_due_a2a_schedules_passes_heartbeat_and_hard_timeout(
    async_db_session,  # noqa: ARG001
    monkeypatch,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()
    recover_mock = AsyncMock(return_value=0)
    claim_mock = AsyncMock(return_value=None)

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
        "app.services.a2a_schedule_job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.services.a2a_schedule_job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.services.a2a_schedule_job.a2a_schedule_service.recover_stale_running_tasks",
        recover_mock,
    )
    monkeypatch.setattr(
        "app.services.a2a_schedule_job.a2a_schedule_service.claim_next_due_task",
        claim_mock,
    )

    await dispatch_due_a2a_schedules(batch_size=1)

    assert recover_mock.await_count == 1
    call_kwargs = recover_mock.await_args.kwargs
    assert call_kwargs["timeout_seconds"] == 60
    assert call_kwargs["hard_timeout_seconds"] == 200
    assert ensure_workers_mock.await_count == 1
    assert refresh_metrics_mock.await_count == 1


async def test_refresh_ops_metrics_skips_when_db_connection_refused(
    monkeypatch,
    caplog,
) -> None:
    class _RefusedSessionContext:
        async def __aenter__(self):
            raise ConnectionRefusedError("db unavailable")

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

    monkeypatch.setattr(
        "app.services.a2a_schedule_job.AsyncSessionLocal",
        lambda: _RefusedSessionContext(),
    )

    with caplog.at_level(logging.WARNING, logger="app.services.a2a_schedule_job"):
        await _refresh_ops_metrics()

    assert (
        "Skip schedule ops metrics refresh due to database connectivity issue."
        in caplog.text
    )
