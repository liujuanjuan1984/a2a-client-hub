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
    assert messages[-1].content == ""
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


async def test_list_messages_ignores_agent_header_content_without_chunks(
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
        response_content="should-not-be-read-from-header",
        success=True,
        context_id="ctx-1",
    )
    await async_db_session.flush()

    items, _, _ = await session_hub_service.list_messages(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
        page=1,
        size=20,
    )
    agent_items = [item for item in items if item.get("role") == "agent"]
    assert len(agent_items) == 1
    assert agent_items[0]["content"] == ""


async def test_list_messages_overwrite_chunk_without_text_duplication(
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
    await session_hub_service.append_agent_message_chunk(
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
    await session_hub_service.append_agent_message_chunk(
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

    items, _, _ = await session_hub_service.list_messages(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
        page=1,
        size=20,
    )
    agent_items = [item for item in items if item.get("role") == "agent"]
    assert len(agent_items) == 1
    agent_item = agent_items[0]
    assert agent_item["id"] == str(agent_message_id)
    assert agent_item["content"] == "final content"
    metadata = agent_item["metadata"]
    assert isinstance(metadata, dict)
    assert "message_blocks" not in metadata
    assert metadata.get("chunk_count") == 2

    blocks, meta, _ = await session_hub_service.list_message_blocks(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
        message_id=str(agent_message_id),
    )
    assert meta["conversationId"] == str(thread.id)
    assert meta["messageId"] == str(agent_message_id)
    assert meta["role"] == "agent"
    assert meta["chunkCount"] == 2
    assert meta["hasBlocks"] is True
    text_blocks = [block for block in blocks if block.get("type") == "text"]
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
    await session_hub_service.append_agent_message_chunk(
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
    await session_hub_service.append_agent_message_chunk(
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
    await session_hub_service.append_agent_message_chunk(
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
    await session_hub_service.append_agent_message_chunk(
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

    items, _, _ = await session_hub_service.list_messages(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
        page=1,
        size=20,
    )
    agent_items = [item for item in items if item.get("role") == "agent"]
    assert len(agent_items) == 1
    agent_item = agent_items[0]
    assert agent_item["id"] == str(agent_message_id)
    metadata = agent_item["metadata"]
    assert isinstance(metadata, dict)
    assert "message_blocks" not in metadata
    assert metadata.get("chunk_count") == 4

    blocks, meta, _ = await session_hub_service.list_message_blocks(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
        message_id=str(agent_message_id),
    )
    assert meta["chunkCount"] == 4
    assert meta["hasBlocks"] is True
    text_blocks = [block for block in blocks if block.get("type") == "text"]
    assert len(text_blocks) == 2
    assert text_blocks[0]["content"] == "first final"
    assert text_blocks[1]["content"] == "second final"
    assert agent_item["content"] == "first finalsecond final"


async def test_append_agent_message_chunk_unique_conflict_does_not_rollback_session(
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

        async def scalar(self, _stmt):  # noqa: ANN001
            return object()

        def begin_nested(self) -> _Nested:
            self.begin_nested_called += 1
            return _Nested()

        async def rollback(self) -> None:
            self.rollback_called = True

    async def _find_none(*_args, **_kwargs):  # noqa: ANN001
        return None

    async def _raise_unique_conflict(*_args, **_kwargs):  # noqa: ANN001
        raise IntegrityError(
            "insert uq_agent_message_chunks_message_id_seq",
            {},
            Exception("uq_agent_message_chunks_message_id_seq"),
        )

    monkeypatch.setattr(
        session_hub_module.agent_message_chunk_handler,
        "find_chunk_by_message_and_event_id",
        _find_none,
    )
    monkeypatch.setattr(
        session_hub_module.agent_message_chunk_handler,
        "find_chunk_by_message_and_seq",
        _find_none,
    )
    monkeypatch.setattr(
        session_hub_module.agent_message_chunk_handler,
        "create_chunk",
        _raise_unique_conflict,
    )

    dummy_db = _DummyDB()
    result = await session_hub_service.append_agent_message_chunk(
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

    assert result is None
    assert dummy_db.begin_nested_called == 1
    assert dummy_db.rollback_called is False
