from __future__ import annotations

from tests.sessions import session_hub_service_support as support
from tests.sessions.session_hub_service_support import (
    AgentMessage,
    AgentMessageBlock,
    ConversationThread,
    create_user,
    pytest,
    select,
    serialize_interrupt_event_block_content,
    session_hub_service,
    utc_now,
    uuid4,
)

pytestmark = support.pytestmark


async def test_append_agent_message_block_update_preserves_interrupt_request_content_on_resolve(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=uuid4(),
        agent_source="personal",
        title="Interrupt Preserve Content",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    agent_message = AgentMessage(
        user_id=user.id,
        sender="agent",
        conversation_id=thread.id,
        status="streaming",
    )
    async_db_session.add(agent_message)
    await async_db_session.flush()

    block_id = "msg-1:interrupt:perm-1"
    asked_content = serialize_interrupt_event_block_content(
        {
            "request_id": "perm-1",
            "type": "permission",
            "phase": "asked",
            "details": {
                "permission": "write",
                "patterns": ["/repo/config.yml"],
            },
        }
    )
    resolved_content = serialize_interrupt_event_block_content(
        {
            "request_id": "perm-1",
            "type": "permission",
            "phase": "resolved",
            "resolution": "replied",
        }
    )

    await session_hub_service.append_agent_message_block_update(
        async_db_session,
        user_id=user.id,
        agent_message_id=agent_message.id,
        seq=1,
        block_type="interrupt_event",
        content=asked_content,
        append=False,
        is_finished=True,
        block_id=block_id,
        lane_id="interrupt_event",
        operation="replace",
        source="interrupt_lifecycle",
    )
    await session_hub_service.append_agent_message_block_update(
        async_db_session,
        user_id=user.id,
        agent_message_id=agent_message.id,
        seq=2,
        block_type="interrupt_event",
        content=resolved_content,
        append=False,
        is_finished=True,
        block_id=block_id,
        lane_id="interrupt_event",
        operation="replace",
        source="interrupt_lifecycle",
    )
    await async_db_session.flush()

    persisted_blocks = list(
        (
            await async_db_session.scalars(
                select(AgentMessageBlock)
                .where(AgentMessageBlock.message_id == agent_message.id)
                .order_by(AgentMessageBlock.block_seq.asc())
            )
        ).all()
    )

    assert len(persisted_blocks) == 1
    assert persisted_blocks[0].content == asked_content


async def test_cancel_session_returns_no_inflight_when_no_active_task(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    payload, db_mutated = await session_hub_service.cancel_session(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
    )

    assert db_mutated is False
    assert payload["conversationId"] == str(thread.id)
    assert payload["taskId"] is None
    assert payload["cancelled"] is False
    assert payload["status"] == "no_inflight"


async def test_cancel_session_returns_no_inflight_when_session_not_found(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    payload, db_mutated = await session_hub_service.cancel_session(
        async_db_session,
        user_id=user.id,
        conversation_id=str(uuid4()),
    )

    assert db_mutated is False
    assert payload["taskId"] is None
    assert payload["cancelled"] is False
    assert payload["status"] == "no_inflight"


async def test_preempt_inflight_invoke_report_marks_completed_when_task_cancelled(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    calls: dict[str, str] = {}

    class _Gateway:
        async def cancel_task(self, *, resolved, task_id, metadata=None):
            calls["task_id"] = str(task_id)
            calls["reason"] = str((metadata or {}).get("source"))
            return {"success": True}

    token = await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        gateway=_Gateway(),
        resolved=object(),
    )
    await session_hub_service.bind_inflight_task_id(
        user_id=user.id,
        conversation_id=thread.id,
        token=token,
        task_id="task-preempt-1",
    )

    report = await session_hub_service.preempt_inflight_invoke_report(
        user_id=user.id,
        conversation_id=thread.id,
        reason="invoke_interrupt",
    )

    assert report.attempted is True
    assert report.status == "completed"
    assert report.target_task_ids == ["task-preempt-1"]
    assert report.failed_error_codes == []
    assert calls == {
        "task_id": "task-preempt-1",
        "reason": "invoke_interrupt",
    }


async def test_preempt_inflight_invoke_report_marks_accepted_when_task_not_bound(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    class _Gateway:
        async def cancel_task(self, *, resolved, task_id, metadata=None):
            calls["task_id"] = str(task_id)
            calls["reason"] = str((metadata or {}).get("source"))
            return {"success": True}

    calls: dict[str, str] = {}
    token = await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        gateway=_Gateway(),
        resolved=object(),
    )
    report = await session_hub_service.preempt_inflight_invoke_report(
        user_id=user.id,
        conversation_id=thread.id,
        reason="invoke_interrupt",
    )
    assert report.attempted is True
    assert report.status == "accepted"
    assert report.pending_requested is True
    assert report.target_task_ids == []
    assert report.failed_error_codes == []
    assert calls == {}

    bound = await session_hub_service.bind_inflight_task_id(
        user_id=user.id,
        conversation_id=thread.id,
        token=token,
        task_id="task-late-bound",
    )
    assert bound is True
    assert calls == {
        "task_id": "task-late-bound",
        "reason": "invoke_interrupt",
    }


async def test_bind_inflight_task_id_report_finalizes_pending_preempt_event(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    class _Gateway:
        async def cancel_task(self, *, resolved, task_id, metadata=None):
            return {"success": True}

    token = await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        gateway=_Gateway(),
        resolved=object(),
    )
    pending_event = {
        "reason": "invoke_interrupt",
        "source": "user",
        "target_message_id": str(uuid4()),
        "replacement_user_message_id": str(uuid4()),
        "replacement_agent_message_id": str(uuid4()),
    }
    report = await session_hub_service.preempt_inflight_invoke_report(
        user_id=user.id,
        conversation_id=thread.id,
        reason="invoke_interrupt",
        pending_event=pending_event,
    )
    assert report.status == "accepted"
    assert report.pending_tokens == [token]

    bind_report = await session_hub_service.bind_inflight_task_id_report(
        user_id=user.id,
        conversation_id=thread.id,
        token=token,
        task_id="task-late-bound",
    )

    assert bind_report.bound is True
    assert bind_report.preempt_event == {
        **pending_event,
        "status": "completed",
        "target_task_ids": ["task-late-bound"],
        "failed_error_codes": [],
    }


async def test_bind_inflight_task_id_report_marks_pending_preempt_failed(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    class _Gateway:
        async def cancel_task(self, *, resolved, task_id, metadata=None):
            return {"success": False, "error_code": "timeout"}

    token = await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        gateway=_Gateway(),
        resolved=object(),
    )
    pending_event = {
        "reason": "invoke_interrupt",
        "source": "user",
        "target_message_id": str(uuid4()),
        "replacement_user_message_id": str(uuid4()),
        "replacement_agent_message_id": str(uuid4()),
    }
    await session_hub_service.preempt_inflight_invoke_report(
        user_id=user.id,
        conversation_id=thread.id,
        reason="invoke_interrupt",
        pending_event=pending_event,
    )

    bind_report = await session_hub_service.bind_inflight_task_id_report(
        user_id=user.id,
        conversation_id=thread.id,
        token=token,
        task_id="task-late-bound",
    )

    assert bind_report.bound is True
    assert bind_report.preempt_event == {
        **pending_event,
        "status": "failed",
        "target_task_ids": ["task-late-bound"],
        "failed_error_codes": ["timeout"],
    }


async def test_preempt_inflight_invoke_keeps_old_token_when_new_inflight_registered(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    old_calls: dict[str, str] = {}

    class _OldGateway:
        async def cancel_task(self, *, resolved, task_id, metadata=None):
            old_calls["task_id"] = str(task_id)
            old_calls["reason"] = str((metadata or {}).get("source"))
            return {"success": True}

    class _NewGateway:
        async def cancel_task(self, *, resolved, task_id, metadata=None):
            return {"success": True}

    old_token = await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        gateway=_OldGateway(),
        resolved=object(),
    )

    preempted = await session_hub_service.preempt_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        reason="invoke_interrupt",
    )
    assert preempted is True

    # New invoke registers after preempt; the old token must remain cancellable.
    await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        gateway=_NewGateway(),
        resolved=object(),
    )

    bound = await session_hub_service.bind_inflight_task_id(
        user_id=user.id,
        conversation_id=thread.id,
        token=old_token,
        task_id="task-old-late",
    )
    assert bound is True
    assert old_calls == {
        "task_id": "task-old-late",
        "reason": "invoke_interrupt",
    }


async def test_cancel_session_accepts_pending_cancel_when_task_not_bound(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    class _Gateway:
        async def cancel_task(self, *, resolved, task_id, metadata=None):
            return {"success": True}

    await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        gateway=_Gateway(),
        resolved=object(),
    )

    payload, db_mutated = await session_hub_service.cancel_session(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
    )

    assert db_mutated is False
    assert payload["conversationId"] == str(thread.id)
    assert payload["taskId"] is None
    assert payload["cancelled"] is True
    assert payload["status"] == "pending"


async def test_cancel_session_accepts_and_unregisters_inflight_task(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    captured: dict[str, str] = {}

    class _Gateway:
        async def cancel_task(self, *, resolved, task_id, metadata=None):
            captured["task_id"] = str(task_id)
            captured["resolved_name"] = str(getattr(resolved, "name", ""))
            return {"success": True}

    token = await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        gateway=_Gateway(),
        resolved=type("Resolved", (), {"name": "Demo Agent"})(),
    )
    bound = await session_hub_service.bind_inflight_task_id(
        user_id=user.id,
        conversation_id=thread.id,
        token=token,
        task_id="task-123",
    )
    assert bound is True

    payload, db_mutated = await session_hub_service.cancel_session(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
    )

    assert db_mutated is False
    assert payload["cancelled"] is True
    assert payload["status"] == "accepted"
    assert payload["taskId"] == "task-123"
    assert captured == {
        "task_id": "task-123",
        "resolved_name": "Demo Agent",
    }

    no_task_payload, _ = await session_hub_service.cancel_session(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
    )
    assert no_task_payload["status"] == "no_inflight"


async def test_cancel_session_returns_accepted_when_partial_upstream_failures_exist(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    class _FailGateway:
        async def cancel_task(self, *, resolved, task_id, metadata=None):
            return {"success": False, "error_code": "timeout"}

    class _OkGateway:
        async def cancel_task(self, *, resolved, task_id, metadata=None):
            return {"success": True}

    failed_token = await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        gateway=_FailGateway(),
        resolved=object(),
    )
    await session_hub_service.bind_inflight_task_id(
        user_id=user.id,
        conversation_id=thread.id,
        token=failed_token,
        task_id="task-fail",
    )

    accepted_token = await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        gateway=_OkGateway(),
        resolved=object(),
    )
    await session_hub_service.bind_inflight_task_id(
        user_id=user.id,
        conversation_id=thread.id,
        token=accepted_token,
        task_id="task-success",
    )

    payload, db_mutated = await session_hub_service.cancel_session(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
    )

    assert db_mutated is False
    assert payload["cancelled"] is True
    assert payload["status"] == "accepted"
    assert payload["taskId"] == "task-success"


async def test_preempt_inflight_invoke_returns_true_when_partial_failures_exist(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    class _FailGateway:
        async def cancel_task(self, *, resolved, task_id, metadata=None):
            return {"success": False, "error_code": "upstream_error"}

    class _OkGateway:
        async def cancel_task(self, *, resolved, task_id, metadata=None):
            return {"success": True}

    failed_token = await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        gateway=_FailGateway(),
        resolved=object(),
    )
    await session_hub_service.bind_inflight_task_id(
        user_id=user.id,
        conversation_id=thread.id,
        token=failed_token,
        task_id="task-preempt-fail",
    )

    accepted_token = await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        gateway=_OkGateway(),
        resolved=object(),
    )
    await session_hub_service.bind_inflight_task_id(
        user_id=user.id,
        conversation_id=thread.id,
        token=accepted_token,
        task_id="task-preempt-ok",
    )

    preempted = await session_hub_service.preempt_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        reason="invoke_interrupt",
    )
    assert preempted is True


async def test_cancel_session_treats_terminal_upstream_task_as_idempotent(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    class _Gateway:
        async def cancel_task(self, *, resolved, task_id, metadata=None):
            return {"success": False, "error_code": "task_not_cancelable"}

    token = await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        gateway=_Gateway(),
        resolved=object(),
    )
    await session_hub_service.bind_inflight_task_id(
        user_id=user.id,
        conversation_id=thread.id,
        token=token,
        task_id="task-terminal",
    )

    payload, db_mutated = await session_hub_service.cancel_session(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
    )

    assert db_mutated is False
    assert payload["cancelled"] is False
    assert payload["status"] == "already_terminal"
    assert payload["taskId"] == "task-terminal"


async def test_cancel_session_raises_upstream_error_for_retryable_failures(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    class _Gateway:
        async def cancel_task(self, *, resolved, task_id, metadata=None):
            return {"success": False, "error_code": "timeout"}

    token = await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        gateway=_Gateway(),
        resolved=object(),
    )
    await session_hub_service.bind_inflight_task_id(
        user_id=user.id,
        conversation_id=thread.id,
        token=token,
        task_id="task-timeout",
    )

    with pytest.raises(ValueError, match="upstream_unreachable"):
        await session_hub_service.cancel_session(
            async_db_session,
            user_id=user.id,
            conversation_id=str(thread.id),
        )
