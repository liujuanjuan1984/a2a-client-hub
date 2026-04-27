from __future__ import annotations

from tests.schedules import a2a_schedule_job_support as support
from tests.schedules.a2a_schedule_job_support import (
    A2AAgentUnavailableError,
    A2AScheduleConflictError,
    A2AScheduleExecution,
    A2AScheduleTask,
    AgentMessage,
    AgentMessageBlock,
    AsyncMock,
    ConversationThread,
    SimpleNamespace,
    _build_claim,
    _create_agent,
    _create_schedule_task,
    _execute_claimed_task,
    _FailingAsyncContextManager,
    _FailingAsyncIterator,
    _mark_task_claimed,
    _mock_gateway_stream,
    _mock_runtime_builder,
    asynccontextmanager,
    asyncio,
    create_user,
    logging,
    select,
    settings,
    utc_now,
    uuid4,
)

pytestmark = support.pytestmark


def _message_event(
    text: str,
    *,
    message_id: str,
    event_id: str,
    context_id: str | None = None,
    provider: str | None = None,
    external_session_id: str | None = None,
) -> dict[str, object]:
    shared: dict[str, object] = {
        "stream": {
            "messageId": message_id,
            "eventId": event_id,
        }
    }
    if provider or external_session_id:
        shared["session"] = {
            **({"provider": provider} if provider else {}),
            **({"id": external_session_id} if external_session_id else {}),
        }
    message: dict[str, object] = {
        "role": "ROLE_AGENT",
        "messageId": message_id,
        "parts": [{"text": text}],
        "metadata": {"shared": shared},
    }
    if context_id:
        message["contextId"] = context_id
    return {"message": message}


def _completed_status_event() -> dict[str, object]:
    return {"statusUpdate": {"status": {"state": "TASK_STATE_COMPLETED"}}}


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
                    _message_event(
                        "all good",
                        message_id="msg-success-1",
                        event_id="evt-success-1",
                    ),
                    _completed_status_event(),
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
                    _message_event(
                        "should not reach",
                        message_id="msg-timeout-first-1",
                        event_id="evt-timeout-first-1",
                    ),
                    _completed_status_event(),
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
        yield _message_event(
            "partial response",
            message_id="msg-timeout-partial",
            event_id="evt-timeout-partial-1",
        )
        await asyncio.sleep(0.05)
        yield _completed_status_event()

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

    async def _build(_db, user_id, agent_id):
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


async def test_execute_claimed_task_releases_schedule_session_before_invoke(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session,
        user_id=user.id,
        suffix="session-release",
    )
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=utc_now(),
    )

    active_schedule_sessions = 0
    original_session_maker = async_session_maker

    class _TrackedSessionContext:
        def __init__(self) -> None:
            self._context = original_session_maker()

        async def __aenter__(self):
            nonlocal active_schedule_sessions
            active_schedule_sessions += 1
            return await self._context.__aenter__()

        async def __aexit__(self, exc_type, exc, tb):
            nonlocal active_schedule_sessions
            try:
                return await self._context.__aexit__(exc_type, exc, tb)
            finally:
                active_schedule_sessions -= 1

    monkeypatch.setattr(
        "app.features.schedules.job.AsyncSessionLocal",
        lambda: _TrackedSessionContext(),
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_runtime_builder",
        _mock_runtime_builder(),
    )

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

    async def _fake_run_background_invoke(**_kwargs):
        assert active_schedule_sessions == 0
        return {
            "success": True,
            "response_content": "ok",
            "conversation_id": None,
            "message_refs": {},
            "context_id": None,
        }

    monkeypatch.setattr(
        "app.features.schedules.job.get_a2a_service",
        lambda: SimpleNamespace(
            gateway=SimpleNamespace(open_invoke_session=_open_invoke_session)
        ),
    )
    monkeypatch.setattr(
        "app.features.schedules.job.run_background_invoke",
        _fake_run_background_invoke,
    )

    run_id = await _mark_task_claimed(async_db_session, task=task)
    await _execute_claimed_task(claim=_build_claim(task, run_id=run_id))

    assert active_schedule_sessions == 0
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
                    _message_event(
                        "bound",
                        message_id="msg-bind-1",
                        event_id="evt-bind-1",
                        provider="opencode",
                        external_session_id="ses_bind_1",
                    ),
                    _completed_status_event(),
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
                    _message_event(
                        "Readable answer",
                        message_id="msg-readable-1",
                        event_id="evt-readable-1",
                    ),
                    _completed_status_event(),
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
                    _message_event(
                        "ok",
                        message_id="msg-new-conv-1",
                        event_id="evt-new-conv-1",
                    ),
                    _completed_status_event(),
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
