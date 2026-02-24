from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models.agent_message import AgentMessage
from app.db.models.conversation_thread import ConversationThread
from app.services.conversation_identity import conversation_identity_service
from app.services.session_hub import session_hub_service
from app.utils.idempotency_key import (
    IDEMPOTENCY_KEY_MAX_LENGTH,
    normalize_idempotency_key,
)
from app.utils.timezone_util import utc_now
from tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


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
    )

    assert len(items) == 1
    assert items[0]["title"] == "Session"


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
    assert messages[-1].content == "partial-updated"
    assert messages[-1].invoke_idempotency_key == "run:abc:scheduled"


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
