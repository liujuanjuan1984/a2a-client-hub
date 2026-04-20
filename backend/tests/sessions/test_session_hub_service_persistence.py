from __future__ import annotations

from tests.sessions import session_hub_service_support as support
from tests.sessions.session_hub_service_support import (
    IDEMPOTENCY_KEY_MAX_LENGTH,
    AgentMessage,
    ConversationThread,
    _list_message_items,
    conversation_identity_service,
    create_user,
    normalize_idempotency_key,
    pytest,
    select,
    session_hub_service,
    utc_now,
    uuid4,
)

pytestmark = support.pytestmark


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
    assert items[0]["agent_id"] == str(kept_agent_id)


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


async def test_record_local_invoke_messages_reads_shared_session_binding_metadata(
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
            "shared": {
                "session": {
                    "id": "ses-upstream-shared-1",
                    "provider": "opencode",
                }
            }
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
        assert metadata.get("provider") == "opencode"
        assert metadata.get("externalSessionId") == "ses-upstream-shared-1"


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
        user_sender="automation",
    )
    await async_db_session.flush()

    assert refs["user_message_id"] == requested_user_message_id
    assert refs["agent_message_id"] == requested_agent_message_id

    user_message = await async_db_session.get(AgentMessage, requested_user_message_id)
    agent_message = await async_db_session.get(AgentMessage, requested_agent_message_id)
    assert user_message is not None
    assert user_message.sender == "automation"
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


async def test_record_local_invoke_messages_persists_working_directory_metadata(
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
        context_id=None,
        invoke_metadata={
            "workingDirectory": "  /workspace/demo  ",
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
        assert metadata.get("working_directory") == "/workspace/demo"


async def test_continue_session_returns_latest_working_directory(async_db_session):
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
        context_id=None,
        invoke_metadata={
            "workingDirectory": "/workspace/demo",
        },
    )
    await async_db_session.flush()

    payload, db_mutated = await session_hub_service.continue_session(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
    )

    assert db_mutated is False
    assert payload["conversationId"] == str(thread.id)
    assert payload["workingDirectory"] == "/workspace/demo"
