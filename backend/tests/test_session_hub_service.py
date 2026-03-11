from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.agent_message import AgentMessage
from app.db.models.conversation_thread import ConversationThread
from app.services import session_hub as session_hub_module
from app.services.conversation_identity import conversation_identity_service
from app.services.session_hub import session_hub_service
from app.utils.idempotency_key import (
    IDEMPOTENCY_KEY_MAX_LENGTH,
    normalize_idempotency_key,
)
from app.utils.timezone_util import utc_now
from tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _list_message_items(
    async_db_session,
    *,
    user_id,
    conversation_id: str,
    limit: int = 50,
):
    items, _, _ = await session_hub_service.list_messages(
        async_db_session,
        user_id=user_id,
        conversation_id=conversation_id,
        before=None,
        limit=limit,
    )
    return items


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


async def test_preempt_inflight_invoke_cancels_existing_task(async_db_session):
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
        async def cancel_task(
            self, *, resolved, task_id, metadata=None
        ):  # noqa: ANN001
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

    preempted = await session_hub_service.preempt_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        reason="invoke_interrupt",
    )

    assert preempted is True
    assert calls == {
        "task_id": "task-preempt-1",
        "reason": "invoke_interrupt",
    }


async def test_preempt_inflight_invoke_marks_pending_cancel_when_task_not_bound(
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
        async def cancel_task(
            self, *, resolved, task_id, metadata=None
        ):  # noqa: ANN001
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
    preempted = await session_hub_service.preempt_inflight_invoke(
        user_id=user.id,
        conversation_id=thread.id,
        reason="invoke_interrupt",
    )
    assert preempted is True
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
        async def cancel_task(
            self, *, resolved, task_id, metadata=None
        ):  # noqa: ANN001
            old_calls["task_id"] = str(task_id)
            old_calls["reason"] = str((metadata or {}).get("source"))
            return {"success": True}

    class _NewGateway:
        async def cancel_task(
            self, *, resolved, task_id, metadata=None
        ):  # noqa: ANN001, ARG002
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
        async def cancel_task(
            self, *, resolved, task_id, metadata=None
        ):  # noqa: ANN001, ARG002
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
        async def cancel_task(
            self, *, resolved, task_id, metadata=None
        ):  # noqa: ANN001
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
        async def cancel_task(
            self, *, resolved, task_id, metadata=None
        ):  # noqa: ANN001, ARG002
            return {"success": False, "error_code": "timeout"}

    class _OkGateway:
        async def cancel_task(
            self, *, resolved, task_id, metadata=None
        ):  # noqa: ANN001, ARG002
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
        async def cancel_task(
            self, *, resolved, task_id, metadata=None
        ):  # noqa: ANN001, ARG002
            return {"success": False, "error_code": "upstream_error"}

    class _OkGateway:
        async def cancel_task(
            self, *, resolved, task_id, metadata=None
        ):  # noqa: ANN001, ARG002
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
        async def cancel_task(
            self, *, resolved, task_id, metadata=None
        ):  # noqa: ANN001
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
        async def cancel_task(
            self, *, resolved, task_id, metadata=None
        ):  # noqa: ANN001
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


async def test_record_local_invoke_messages_updates_manual_placeholder_title(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Manual Session c81dceba",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    await session_hub_service.record_local_invoke_messages(
        async_db_session,
        session=thread,
        source="manual",
        user_id=user.id,
        agent_id=uuid4(),
        agent_source="personal",
        query="How do I list all invoices?",
        response_content="ok",
        success=True,
        context_id=None,
    )

    assert thread.title == "How do I list all invoices?"


async def test_list_sessions_falls_back_to_session_title_for_placeholder_thread_title(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Manual Session deadbeef",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    items, _, _ = await session_hub_service.list_sessions(
        async_db_session,
        user_id=user.id,
        page=1,
        size=50,
        source="manual",
        agent_id=None,
    )

    assert len(items) == 1
    assert items[0]["title"] == "Session"


async def test_list_sessions_filters_by_agent_id(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    kept_agent_id = uuid4()
    skipped_agent_id = uuid4()
    async_db_session.add(
        ConversationThread(
            user_id=user.id,
            source=ConversationThread.SOURCE_MANUAL,
            agent_id=kept_agent_id,
            title="Session A",
            last_active_at=utc_now(),
            status=ConversationThread.STATUS_ACTIVE,
        )
    )
    async_db_session.add(
        ConversationThread(
            user_id=user.id,
            source=ConversationThread.SOURCE_MANUAL,
            agent_id=skipped_agent_id,
            title="Session B",
            last_active_at=utc_now(),
            status=ConversationThread.STATUS_ACTIVE,
        )
    )
    await async_db_session.flush()

    items, _, _ = await session_hub_service.list_sessions(
        async_db_session,
        user_id=user.id,
        page=1,
        size=50,
        source="manual",
        agent_id=kept_agent_id,
    )

    assert len(items) == 1
    assert items[0]["agent_id"] == kept_agent_id


async def test_bind_external_session_with_state_updates_title_from_invoke_hints(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    existing = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        external_provider="opencode",
        external_session_id="ext-1",
        title="Manual Session b7f2a1",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    new_thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(existing)
    async_db_session.add(new_thread)
    await async_db_session.flush()

    bind_result = await conversation_identity_service.bind_external_session_with_state(
        async_db_session,
        user_id=user.id,
        conversation_id=new_thread.id,
        source="manual",
        provider="opencode",
        external_session_id="ext-1",
        agent_id=uuid4(),
        agent_source="personal",
        context_id="ctx-1",
        title="Upstream Bound Session",
    )

    await async_db_session.flush()

    assert bind_result.conversation_id == existing.id
    assert bind_result.mutated is True
    assert existing.title == "Upstream Bound Session"


async def test_record_local_invoke_messages_writes_canonical_external_session_id_metadata(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    await session_hub_service.record_local_invoke_messages(
        async_db_session,
        session=thread,
        source="manual",
        user_id=user.id,
        agent_id=uuid4(),
        agent_source="personal",
        query="hello",
        response_content="ok",
        success=True,
        context_id="ctx-1",
        invoke_metadata={
            "provider": "opencode",
            "externalSessionId": "ses-upstream-1",
        },
    )
    await async_db_session.flush()

    result = await async_db_session.execute(
        select(AgentMessage).where(AgentMessage.conversation_id == thread.id)
    )
    messages = list(result.scalars().all())
    assert len(messages) == 2
    for msg in messages:
        metadata = msg.message_metadata or {}
        assert metadata.get("externalSessionId") == "ses-upstream-1"
        assert "external_session_id" not in metadata


async def test_record_local_invoke_messages_is_idempotent_with_key(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        user_id=user.id,
        source=ConversationThread.SOURCE_SCHEDULED,
        title="Scheduled Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    first_refs = await session_hub_service.record_local_invoke_messages(
        async_db_session,
        session=thread,
        source="scheduled",
        user_id=user.id,
        agent_id=uuid4(),
        agent_source="personal",
        query="hello",
        response_content="partial",
        success=False,
        context_id="ctx-1",
        idempotency_key="run:abc:scheduled",
        response_metadata={
            "stream": {
                "schema_version": 1,
                "finish_reason": "timeout_total",
                "error": {"message": "timeout", "error_code": "timeout"},
            }
        },
    )
    second_refs = await session_hub_service.record_local_invoke_messages(
        async_db_session,
        session=thread,
        source="scheduled",
        user_id=user.id,
        agent_id=uuid4(),
        agent_source="personal",
        query="hello",
        response_content="partial-updated",
        success=False,
        context_id="ctx-1",
        idempotency_key="run:abc:scheduled",
        response_metadata={
            "stream": {
                "schema_version": 1,
                "finish_reason": "timeout_total",
                "error": {"message": "timeout", "error_code": "timeout"},
            }
        },
    )
    await async_db_session.flush()

    result = await async_db_session.execute(
        select(AgentMessage)
        .where(AgentMessage.conversation_id == thread.id)
        .order_by(AgentMessage.created_at.asc())
    )
    messages = list(result.scalars().all())
    assert len(messages) == 2
    assert first_refs["user_message_id"] == second_refs["user_message_id"]
    assert first_refs["agent_message_id"] == second_refs["agent_message_id"]
    assert messages[0].invoke_idempotency_key == "run:abc:scheduled"
    assert messages[-1].sender == "agent"
    assert messages[-1].invoke_idempotency_key == "run:abc:scheduled"
    message_items = await _list_message_items(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
    )
    assert len(message_items) == 2
    user_item = next(
        item
        for item in message_items
        if item["id"] == str(first_refs["user_message_id"])
    )
    agent_item = next(
        item
        for item in message_items
        if item["id"] == str(first_refs["agent_message_id"])
    )
    assert user_item["role"] == "user"
    assert len(user_item["blocks"]) == 1
    assert user_item["blocks"][0]["content"] == "hello"
    assert agent_item["role"] == "agent"
    assert len(agent_item["blocks"]) == 1
    assert agent_item["blocks"][0]["content"] == "partial-updated"


async def test_record_local_invoke_messages_normalizes_overlong_idempotency_key(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        user_id=user.id,
        source=ConversationThread.SOURCE_SCHEDULED,
        title="Scheduled Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    raw_key = f"run:{'a' * 400}:scheduled"
    expected_key = normalize_idempotency_key(raw_key)
    assert expected_key is not None
    assert len(expected_key) == IDEMPOTENCY_KEY_MAX_LENGTH

    first_refs = await session_hub_service.record_local_invoke_messages(
        async_db_session,
        session=thread,
        source="scheduled",
        user_id=user.id,
        agent_id=uuid4(),
        agent_source="personal",
        query="hello",
        response_content="partial",
        success=False,
        context_id="ctx-1",
        idempotency_key=raw_key,
    )
    second_refs = await session_hub_service.record_local_invoke_messages(
        async_db_session,
        session=thread,
        source="scheduled",
        user_id=user.id,
        agent_id=uuid4(),
        agent_source="personal",
        query="hello",
        response_content="partial-updated",
        success=False,
        context_id="ctx-1",
        idempotency_key=raw_key,
    )
    await async_db_session.flush()

    result = await async_db_session.execute(
        select(AgentMessage)
        .where(AgentMessage.conversation_id == thread.id)
        .order_by(AgentMessage.created_at.asc())
    )
    messages = list(result.scalars().all())
    assert len(messages) == 2
    assert first_refs["user_message_id"] == second_refs["user_message_id"]
    assert first_refs["agent_message_id"] == second_refs["agent_message_id"]
    assert messages[0].invoke_idempotency_key == expected_key
    assert messages[-1].invoke_idempotency_key == expected_key
    message_items = await _list_message_items(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
    )
    assert len(message_items) == 2
    user_item = next(
        item
        for item in message_items
        if item["id"] == str(first_refs["user_message_id"])
    )
    agent_item = next(
        item
        for item in message_items
        if item["id"] == str(first_refs["agent_message_id"])
    )
    assert len(user_item["blocks"]) == 1
    assert user_item["blocks"][0]["content"] == "hello"
    assert len(agent_item["blocks"]) == 1
    assert agent_item["blocks"][0]["content"] == "partial-updated"


async def test_record_local_invoke_messages_uses_requested_message_ids(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    requested_user_message_id = uuid4()
    requested_agent_message_id = uuid4()
    refs = await session_hub_service.record_local_invoke_messages(
        async_db_session,
        session=thread,
        source="manual",
        user_id=user.id,
        agent_id=uuid4(),
        agent_source="personal",
        query="hello",
        response_content="ok",
        success=True,
        context_id="ctx-1",
        idempotency_key="user:msg-canonical:ws",
        user_message_id=requested_user_message_id,
        agent_message_id=requested_agent_message_id,
    )
    await async_db_session.flush()

    assert refs["user_message_id"] == requested_user_message_id
    assert refs["agent_message_id"] == requested_agent_message_id

    user_message = await async_db_session.get(AgentMessage, requested_user_message_id)
    agent_message = await async_db_session.get(AgentMessage, requested_agent_message_id)
    assert user_message is not None
    assert user_message.sender in {"user", "automation"}
    assert user_message.conversation_id == thread.id
    assert agent_message is not None
    assert agent_message.sender == "agent"
    assert agent_message.conversation_id == thread.id


async def test_record_local_invoke_messages_rejects_requested_message_id_conflict(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    await session_hub_service.record_local_invoke_messages(
        async_db_session,
        session=thread,
        source="manual",
        user_id=user.id,
        agent_id=uuid4(),
        agent_source="personal",
        query="hello",
        response_content="ok",
        success=True,
        context_id="ctx-1",
        idempotency_key="user:msg-conflict:ws",
        user_message_id=uuid4(),
        agent_message_id=uuid4(),
    )
    await async_db_session.flush()

    with pytest.raises(ValueError, match="message_id_conflict"):
        await session_hub_service.record_local_invoke_messages(
            async_db_session,
            session=thread,
            source="manual",
            user_id=user.id,
            agent_id=uuid4(),
            agent_source="personal",
            query="hello",
            response_content="ok",
            success=True,
            context_id="ctx-1",
            idempotency_key="user:msg-conflict:ws",
            user_message_id=uuid4(),
            agent_message_id=uuid4(),
        )


async def test_record_local_invoke_messages_rejects_cross_user_message_id_reuse(
    async_db_session,
):
    user_one = await create_user(async_db_session, skip_onboarding_defaults=True)
    user_two = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread_one = ConversationThread(
        user_id=user_one.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    thread_two = ConversationThread(
        user_id=user_two.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread_one)
    async_db_session.add(thread_two)
    await async_db_session.flush()

    shared_user_message_id = uuid4()
    await session_hub_service.record_local_invoke_messages(
        async_db_session,
        session=thread_one,
        source="manual",
        user_id=user_one.id,
        agent_id=uuid4(),
        agent_source="personal",
        query="hello",
        response_content="ok",
        success=True,
        context_id="ctx-1",
        idempotency_key="user:cross-user:ws",
        user_message_id=shared_user_message_id,
        agent_message_id=uuid4(),
    )
    await async_db_session.flush()

    with pytest.raises(ValueError, match="message_id_conflict"):
        await session_hub_service.record_local_invoke_messages(
            async_db_session,
            session=thread_two,
            source="manual",
            user_id=user_two.id,
            agent_id=uuid4(),
            agent_source="personal",
            query="hello",
            response_content="ok",
            success=True,
            context_id="ctx-1",
            idempotency_key="user:cross-user:ws",
            user_message_id=shared_user_message_id,
            agent_message_id=uuid4(),
        )


async def test_record_local_invoke_messages_rejects_idempotency_query_conflict(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    refs = await session_hub_service.record_local_invoke_messages(
        async_db_session,
        session=thread,
        source="manual",
        user_id=user.id,
        agent_id=uuid4(),
        agent_source="personal",
        query="first-query",
        response_content="ok",
        success=True,
        context_id="ctx-1",
        idempotency_key="same-key",
    )
    await async_db_session.flush()

    with pytest.raises(ValueError, match="idempotency_conflict"):
        await session_hub_service.record_local_invoke_messages(
            async_db_session,
            session=thread,
            source="manual",
            user_id=user.id,
            agent_id=uuid4(),
            agent_source="personal",
            query="second-query",
            response_content="ok-2",
            success=True,
            context_id="ctx-1",
            idempotency_key="same-key",
        )

    message_items = await _list_message_items(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
    )
    user_item = next(
        item for item in message_items if item["id"] == str(refs["user_message_id"])
    )
    assert len(user_item["blocks"]) == 1
    assert user_item["blocks"][0]["content"] == "first-query"


async def test_list_messages_returns_blocks_and_before_cursor(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    for index in range(3):
        await session_hub_service.record_local_invoke_messages(
            async_db_session,
            session=thread,
            source="manual",
            user_id=user.id,
            agent_id=uuid4(),
            agent_source="personal",
            query=f"hello-{index}",
            response_content=f"world-{index}",
            success=True,
            context_id="ctx-1",
            idempotency_key=f"timeline-{index}",
        )
    await async_db_session.flush()

    first_items, first_extra, _ = await session_hub_service.list_messages(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
        before=None,
        limit=2,
    )
    assert len(first_items) == 2
    assert first_extra["pageInfo"]["hasMoreBefore"] is True
    first_cursor = first_extra["pageInfo"]["nextBefore"]
    assert isinstance(first_cursor, str)
    assert first_cursor
    assert all("blocks" in item for item in first_items)
    assert all(item["status"] == "done" for item in first_items)

    second_items, second_extra, _ = await session_hub_service.list_messages(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
        before=first_cursor,
        limit=2,
    )
    assert len(second_items) == 2
    assert second_extra["pageInfo"]["nextBefore"] != first_cursor
    assert {item["id"] for item in second_items}.isdisjoint(
        {item["id"] for item in first_items}
    )


async def test_list_messages_rejects_invalid_cursor(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    with pytest.raises(ValueError, match="invalid_before_cursor"):
        await session_hub_service.list_messages(
            async_db_session,
            user_id=user.id,
            conversation_id=str(thread.id),
            before="not-a-valid-cursor",
            limit=8,
        )


async def test_list_messages_overwrite_snapshot_without_text_duplication(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        user_id=user.id,
        source=ConversationThread.SOURCE_SCHEDULED,
        title="Scheduled Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    refs = await session_hub_service.record_local_invoke_messages(
        async_db_session,
        session=thread,
        source="scheduled",
        user_id=user.id,
        agent_id=uuid4(),
        agent_source="personal",
        query="hello",
        response_content="",
        success=False,
        context_id="ctx-1",
        idempotency_key="run:snapshot-test:scheduled",
    )

    agent_message_id = refs["agent_message_id"]
    await session_hub_service.append_agent_message_block_update(
        async_db_session,
        user_id=user.id,
        agent_message_id=agent_message_id,
        seq=1,
        block_type="text",
        content="partial",
        append=True,
        is_finished=False,
        event_id="evt-1",
        source=None,
    )
    await session_hub_service.append_agent_message_block_update(
        async_db_session,
        user_id=user.id,
        agent_message_id=agent_message_id,
        seq=2,
        block_type="text",
        content="final content",
        append=False,
        is_finished=True,
        event_id="evt-2",
        source=None,
    )
    await async_db_session.flush()

    message_items = await _list_message_items(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
    )
    agent_items = [item for item in message_items if item.get("role") == "agent"]
    assert len(agent_items) == 1
    agent_item = agent_items[0]
    assert agent_item["id"] == str(agent_message_id)
    text_blocks = [
        block for block in agent_item["blocks"] if block.get("type") == "text"
    ]
    assert len(text_blocks) == 1
    assert text_blocks[0]["content"] == "final content"


async def test_list_messages_overwrite_preserves_block_boundaries(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        user_id=user.id,
        source=ConversationThread.SOURCE_SCHEDULED,
        title="Scheduled Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    refs = await session_hub_service.record_local_invoke_messages(
        async_db_session,
        session=thread,
        source="scheduled",
        user_id=user.id,
        agent_id=uuid4(),
        agent_source="personal",
        query="hello",
        response_content="",
        success=False,
        context_id="ctx-1",
        idempotency_key="run:snapshot-index:scheduled",
    )

    agent_message_id = refs["agent_message_id"]
    await session_hub_service.append_agent_message_block_update(
        async_db_session,
        user_id=user.id,
        agent_message_id=agent_message_id,
        seq=1,
        block_type="text",
        content="first partial",
        append=True,
        is_finished=False,
        event_id="evt-1",
        source=None,
    )
    await session_hub_service.append_agent_message_block_update(
        async_db_session,
        user_id=user.id,
        agent_message_id=agent_message_id,
        seq=2,
        block_type="text",
        content="first final",
        append=False,
        is_finished=True,
        event_id="evt-2",
        source=None,
    )
    await session_hub_service.append_agent_message_block_update(
        async_db_session,
        user_id=user.id,
        agent_message_id=agent_message_id,
        seq=3,
        block_type="text",
        content="second partial",
        append=True,
        is_finished=False,
        event_id="evt-3",
        source=None,
    )
    await session_hub_service.append_agent_message_block_update(
        async_db_session,
        user_id=user.id,
        agent_message_id=agent_message_id,
        seq=4,
        block_type="text",
        content="second final",
        append=False,
        is_finished=True,
        event_id="evt-4",
        source=None,
    )
    await async_db_session.flush()

    message_items = await _list_message_items(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
    )
    agent_items = [item for item in message_items if item.get("role") == "agent"]
    assert len(agent_items) == 1
    agent_item = agent_items[0]
    assert agent_item["id"] == str(agent_message_id)
    text_blocks = [
        block for block in agent_item["blocks"] if block.get("type") == "text"
    ]
    assert len(text_blocks) == 2
    assert text_blocks[0]["content"] == "first final"
    assert text_blocks[1]["content"] == "second final"


async def test_append_agent_message_block_update_unique_conflict_does_not_rollback_session(
    monkeypatch: pytest.MonkeyPatch,
):
    class _Nested:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
            return False

    class _DummyDB:
        def __init__(self) -> None:
            self.rollback_called = False
            self.begin_nested_called = 0
            self._message = type("Message", (), {"message_metadata": {}})()

        async def scalar(self, _stmt):  # noqa: ANN001
            return self._message

        def begin_nested(self) -> _Nested:
            self.begin_nested_called += 1
            return _Nested()

        async def flush(self) -> None:
            return None

        async def rollback(self) -> None:
            self.rollback_called = True

    async def _find_none(*_args, **_kwargs):  # noqa: ANN001
        return None

    existing_block = type(
        "Block",
        (),
        {
            "block_seq": 1,
            "is_finished": False,
        },
    )()

    async def _find_existing(*_args, **_kwargs):  # noqa: ANN001
        return existing_block

    async def _raise_unique_conflict(*_args, **_kwargs):  # noqa: ANN001
        raise IntegrityError(
            "insert ix_agent_message_blocks_message_id_block_seq",
            {},
            Exception("ix_agent_message_blocks_message_id_block_seq"),
        )

    monkeypatch.setattr(
        session_hub_module.agent_message_block_handler,
        "find_block_by_message_and_block_seq",
        _find_existing,
    )
    monkeypatch.setattr(
        session_hub_module.agent_message_block_handler,
        "find_last_block_for_message",
        _find_none,
    )
    monkeypatch.setattr(
        session_hub_module.agent_message_block_handler,
        "create_block",
        _raise_unique_conflict,
    )

    dummy_db = _DummyDB()
    result = await session_hub_service.append_agent_message_block_update(
        dummy_db,  # type: ignore[arg-type]
        user_id=uuid4(),
        agent_message_id=uuid4(),
        seq=1,
        block_type="text",
        content="payload",
        append=True,
        is_finished=False,
        event_id="evt-1",
        source=None,
    )

    assert result is existing_block
    assert dummy_db.begin_nested_called == 1
    assert dummy_db.rollback_called is False
