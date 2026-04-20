from __future__ import annotations

from tests.sessions import session_hub_service_support as support
from tests.sessions.session_hub_service_support import (
    AgentMessageBlock,
    ConversationThread,
    IntegrityError,
    _list_message_items,
    create_user,
    pytest,
    select,
    session_history_projection_module,
    session_hub_service,
    utc_now,
    uuid4,
)

pytestmark = support.pytestmark


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


async def test_interleaved_reasoning_final_snapshot_rewrites_primary_text_slot(
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
        idempotency_key="run:interleaved-final-snapshot:scheduled",
    )

    agent_message_id = refs["agent_message_id"]
    await session_hub_service.append_agent_message_block_update(
        async_db_session,
        user_id=user.id,
        agent_message_id=agent_message_id,
        seq=1,
        block_type="text",
        content="draft",
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
        block_type="reasoning",
        content="internal-plan",
        append=False,
        is_finished=True,
        event_id="evt-2",
        source="reasoning_part_update",
    )
    await session_hub_service.append_agent_message_block_update(
        async_db_session,
        user_id=user.id,
        agent_message_id=agent_message_id,
        seq=3,
        block_type="text",
        content="final answer",
        append=False,
        is_finished=True,
        event_id="evt-3",
        source="final_snapshot",
    )
    await async_db_session.flush()

    persisted_blocks = list(
        (
            await async_db_session.scalars(
                select(AgentMessageBlock)
                .where(AgentMessageBlock.message_id == agent_message_id)
                .order_by(AgentMessageBlock.block_seq.asc())
            )
        ).all()
    )
    text_blocks = [
        block for block in persisted_blocks if str(block.block_type or "") == "text"
    ]
    assert len(text_blocks) == 1
    assert text_blocks[0].content == "final answer"

    message_items = await _list_message_items(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
    )
    agent_item = next(item for item in message_items if item.get("role") == "agent")
    assert agent_item["content"] == "final answer"
    assert [block["type"] for block in agent_item["blocks"]] == [
        "text",
        "reasoning",
    ]
    assert agent_item["blocks"][0]["content"] == "final answer"
    assert agent_item["blocks"][1]["content"] == ""
    assert agent_item["blocks"][0]["blockId"] == text_blocks[0].block_id
    assert agent_item["blocks"][0]["laneId"] == "primary_text"
    assert agent_item["blocks"][0]["baseSeq"] == 3


async def test_canonical_block_metadata_persists_and_rejects_stale_replace(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Canonical Block State",
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
        query="hello",
        response_content="",
        success=False,
        context_id="ctx-canonical",
        idempotency_key="run:canonical-block-state:manual",
    )
    agent_message_id = refs["agent_message_id"]

    await session_hub_service.append_agent_message_block_update(
        async_db_session,
        user_id=user.id,
        agent_message_id=agent_message_id,
        seq=1,
        block_type="text",
        content="draft",
        append=True,
        is_finished=False,
        block_id="block-text-main",
        lane_id="primary_text",
        operation="append",
        event_id="evt-1",
    )
    await session_hub_service.append_agent_message_block_update(
        async_db_session,
        user_id=user.id,
        agent_message_id=agent_message_id,
        seq=11,
        block_type="text",
        content="authoritative",
        append=False,
        is_finished=True,
        block_id="block-text-main",
        lane_id="primary_text",
        operation="replace",
        base_seq=10,
        event_id="evt-11",
    )

    stale = await session_hub_service.append_agent_message_block_update(
        async_db_session,
        user_id=user.id,
        agent_message_id=agent_message_id,
        seq=12,
        block_type="text",
        content="stale",
        append=False,
        is_finished=True,
        block_id="block-text-main",
        lane_id="primary_text",
        operation="replace",
        base_seq=8,
        event_id="evt-12",
    )
    assert stale is None

    persisted_blocks = list(
        (
            await async_db_session.scalars(
                select(AgentMessageBlock)
                .where(AgentMessageBlock.message_id == agent_message_id)
                .order_by(AgentMessageBlock.block_seq.asc())
            )
        ).all()
    )
    assert len(persisted_blocks) == 1
    assert persisted_blocks[0].content == "authoritative"
    assert persisted_blocks[0].block_id == "block-text-main"
    assert persisted_blocks[0].lane_id == "primary_text"
    assert persisted_blocks[0].base_seq == 10

    message_items = await _list_message_items(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
    )
    agent_item = next(item for item in message_items if item.get("role") == "agent")
    assert agent_item["content"] == "authoritative"
    assert agent_item["blocks"][0]["blockId"] == "block-text-main"
    assert agent_item["blocks"][0]["laneId"] == "primary_text"
    assert agent_item["blocks"][0]["baseSeq"] == 10


async def test_append_agent_message_block_update_unique_conflict_does_not_rollback_session(
    monkeypatch: pytest.MonkeyPatch,
):
    class _Nested:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, _exc_type, _exc, _tb) -> bool:
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
        session_history_projection_module.block_store,
        "find_block_by_message_and_block_seq",
        _find_existing,
    )
    monkeypatch.setattr(
        session_history_projection_module.block_store,
        "find_block_by_message_and_block_id",
        _find_none,
    )
    monkeypatch.setattr(
        session_history_projection_module.block_store,
        "find_last_block_for_message_and_type",
        _find_none,
    )
    monkeypatch.setattr(
        session_history_projection_module.block_store,
        "find_last_block_for_message",
        _find_none,
    )
    monkeypatch.setattr(
        session_history_projection_module.block_store,
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


async def test_append_agent_message_block_update_block_id_conflict_uses_block_lookup(
    monkeypatch: pytest.MonkeyPatch,
):
    class _Nested:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, _exc_type, _exc, _tb) -> bool:
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
            "block_seq": 2,
            "block_id": "block-text-main",
            "lane_id": "primary_text",
            "content": "draft",
            "is_finished": False,
            "start_event_seq": None,
            "end_event_seq": None,
            "base_seq": None,
            "start_event_id": None,
            "end_event_id": None,
            "source": None,
        },
    )()

    block_id_lookup_calls = 0

    async def _find_by_block_id(*_args, **_kwargs):  # noqa: ANN001
        nonlocal block_id_lookup_calls
        block_id_lookup_calls += 1
        return None if block_id_lookup_calls == 1 else existing_block

    async def _raise_block_id_conflict(*_args, **_kwargs):  # noqa: ANN001
        raise IntegrityError(
            "insert ix_agent_message_blocks_message_id_block_id",
            {},
            Exception("ix_agent_message_blocks_message_id_block_id"),
        )

    monkeypatch.setattr(
        session_history_projection_module.block_store,
        "find_block_by_message_and_block_seq",
        _find_none,
    )
    monkeypatch.setattr(
        session_history_projection_module.block_store,
        "find_block_by_message_and_block_id",
        _find_by_block_id,
    )
    monkeypatch.setattr(
        session_history_projection_module.block_store,
        "find_last_block_for_message_and_type",
        _find_none,
    )
    monkeypatch.setattr(
        session_history_projection_module.block_store,
        "find_last_block_for_message",
        _find_none,
    )
    monkeypatch.setattr(
        session_history_projection_module.block_store,
        "create_block",
        _raise_block_id_conflict,
    )

    dummy_db = _DummyDB()
    result = await session_hub_service.append_agent_message_block_update(
        dummy_db,  # type: ignore[arg-type]
        user_id=uuid4(),
        agent_message_id=uuid4(),
        seq=5,
        block_type="text",
        content="payload",
        append=False,
        is_finished=True,
        block_id="block-text-main",
        lane_id="primary_text",
        operation="replace",
        event_id="evt-5",
        source="final_snapshot",
    )

    assert result is existing_block
    assert block_id_lookup_calls == 2
    assert dummy_db.begin_nested_called == 1
    assert dummy_db.rollback_called is False
