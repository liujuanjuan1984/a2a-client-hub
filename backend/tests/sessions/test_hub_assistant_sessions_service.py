from __future__ import annotations

import pytest

from app.features.hub_assistant_shared.actor_context import (
    HubAssistantActorType,
    build_hub_assistant_actor_context,
)
from app.features.hub_assistant_shared.tool_gateway import (
    HubAssistantSurface,
    HubAssistantToolGateway,
)
from app.features.sessions import (
    hub_assistant_sessions_service as hub_assistant_sessions_service_module,
)
from app.features.sessions.hub_assistant_sessions_service import (
    hub_assistant_sessions_service,
)
from tests.support.utils import create_conversation_thread, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _build_gateway(user):
    actor = build_hub_assistant_actor_context(
        user=user,
        actor_type=HubAssistantActorType.HUMAN_API,
    )
    return HubAssistantToolGateway(actor, surface=HubAssistantSurface.REST)


async def test_hub_assistant_sessions_service_list_and_get_sessions(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    manual_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Manual Thread",
    )
    scheduled_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        source="scheduled",
        title="Scheduled Thread",
    )
    gateway = _build_gateway(user)

    items, extra, db_mutated = await hub_assistant_sessions_service.list_sessions(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        page=1,
        size=20,
    )
    fetched = await hub_assistant_sessions_service.get_session(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        conversation_id=str(manual_thread.id),
    )

    assert db_mutated is False
    assert extra["pagination"]["total"] >= 2
    returned_ids = {item["conversationId"] for item in items}
    assert str(manual_thread.id) in returned_ids
    assert str(scheduled_thread.id) in returned_ids
    assert fetched["conversationId"] == str(manual_thread.id)
    assert fetched["title"] == "Manual Thread"


async def test_hub_assistant_sessions_service_list_respects_filters(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    kept_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        source="scheduled",
        title="Keep Me",
    )
    await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Skip Me",
    )
    gateway = _build_gateway(user)

    items, extra, db_mutated = await hub_assistant_sessions_service.list_sessions(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        page=1,
        size=20,
        source="scheduled",
    )

    assert db_mutated is False
    assert extra["pagination"]["total"] == 1
    assert len(items) == 1
    assert items[0]["conversationId"] == str(kept_thread.id)
    assert items[0]["source"] == "scheduled"


async def test_hub_assistant_sessions_service_update_archive_and_unarchive(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Rename Me",
    )
    gateway = _build_gateway(user)

    updated = await hub_assistant_sessions_service.update_session(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        conversation_id=str(thread.id),
        title="Renamed Session",
    )
    archived = await hub_assistant_sessions_service.archive_session(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        conversation_id=str(thread.id),
    )
    active_items, active_extra, _ = await hub_assistant_sessions_service.list_sessions(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        page=1,
        size=20,
    )
    archived_items, archived_extra, _ = (
        await hub_assistant_sessions_service.list_sessions(
            db=async_db_session,
            gateway=gateway,
            current_user=user,
            page=1,
            size=20,
            status="archived",
        )
    )
    restored = await hub_assistant_sessions_service.unarchive_session(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        conversation_id=str(thread.id),
    )

    assert updated["title"] == "Renamed Session"
    assert updated["status"] == "active"
    assert archived["status"] == "archived"
    assert active_extra["pagination"]["total"] == 0
    assert active_items == []
    assert archived_extra["pagination"]["total"] == 1
    assert archived_items[0]["conversationId"] == str(thread.id)
    assert restored["status"] == "active"


async def test_hub_assistant_sessions_service_observes_new_agent_text_result(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Observed Session",
    )
    gateway = _build_gateway(user)
    snapshots = [
        [
            {
                "message_id": "user-msg-1",
                "role": "user",
                "content": "Please keep following up",
                "created_at": thread.created_at,
                "status": "done",
            },
            {
                "message_id": "agent-msg-1",
                "role": "agent",
                "content": "Initial target answer",
                "created_at": thread.created_at,
                "status": "done",
            },
        ],
        [
            {
                "message_id": "user-msg-2",
                "role": "user",
                "content": "Follow-up question sent",
                "created_at": thread.created_at,
                "status": "done",
            },
            {
                "message_id": "agent-msg-1",
                "role": "agent",
                "content": "Initial target answer",
                "created_at": thread.created_at,
                "status": "done",
            },
        ],
        [
            {
                "message_id": "user-msg-2",
                "role": "user",
                "content": "Follow-up question sent",
                "created_at": thread.created_at,
                "status": "done",
            },
            {
                "message_id": "agent-msg-2",
                "role": "agent",
                "content": "No public exposure detected",
                "created_at": thread.created_at,
                "status": "done",
            },
        ],
    ]
    sleep_calls: list[float] = []

    async def _fake_list_latest_text_messages(**_kwargs):
        if len(snapshots) > 1:
            return snapshots.pop(0)
        return snapshots[0]

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(
        hub_assistant_sessions_service_module.hub_assistant_sessions_service,
        "_list_latest_text_messages",
        _fake_list_latest_text_messages,
    )
    monkeypatch.setattr(
        hub_assistant_sessions_service_module.asyncio,
        "sleep",
        _fake_sleep,
    )

    result = await hub_assistant_sessions_service.get_latest_messages(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        conversation_ids=[str(thread.id)],
        limit_per_session=2,
        after_agent_message_id_by_conversation={str(thread.id): "agent-msg-1"},
        wait_up_to_seconds=4,
        poll_interval_seconds=1,
    )

    item = result["items"][0]
    assert item["status"] == "available"
    assert item["observation_status"] == "updated"
    assert item["after_agent_message_id"] == "agent-msg-1"
    assert item["latest_agent_message_id"] == "agent-msg-2"
    assert [message["content"] for message in item["messages"]] == [
        "Follow-up question sent",
        "No public exposure detected",
    ]
    assert sleep_calls == [1, 1]


async def test_hub_assistant_sessions_service_does_not_treat_new_user_text_as_new_result(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Unchanged Session",
    )
    gateway = _build_gateway(user)
    snapshot = [
        {
            "message_id": "user-msg-2",
            "role": "user",
            "content": "Another follow-up question sent",
            "created_at": thread.created_at,
            "status": "done",
        },
        {
            "message_id": "agent-msg-1",
            "role": "agent",
            "content": "Initial target answer",
            "created_at": thread.created_at,
            "status": "done",
        },
    ]

    async def _fake_list_latest_text_messages(**_kwargs):
        return snapshot

    monkeypatch.setattr(
        hub_assistant_sessions_service_module.hub_assistant_sessions_service,
        "_list_latest_text_messages",
        _fake_list_latest_text_messages,
    )

    result = await hub_assistant_sessions_service.get_latest_messages(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        conversation_ids=[str(thread.id)],
        limit_per_session=2,
        after_agent_message_id_by_conversation={str(thread.id): "agent-msg-1"},
        wait_up_to_seconds=0,
        poll_interval_seconds=1,
    )

    item = result["items"][0]
    assert item["status"] == "available"
    assert item["observation_status"] == "unchanged"
    assert item["after_agent_message_id"] == "agent-msg-1"
    assert item["latest_agent_message_id"] == "agent-msg-1"
    assert [message["content"] for message in item["messages"]] == [
        "Another follow-up question sent",
        "Initial target answer",
    ]
