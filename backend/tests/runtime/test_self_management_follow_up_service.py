from __future__ import annotations

from uuid import UUID

import pytest

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.features.self_management_shared.actor_context import (
    SelfManagementActorType,
    build_self_management_actor_context,
)
from app.features.self_management_shared.follow_up_service import (
    built_in_follow_up_service,
)
from app.features.self_management_shared.tool_gateway import (
    SelfManagementSurface,
    SelfManagementToolGateway,
)
from tests.support.utils import create_conversation_thread, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _build_web_agent_gateway(user, built_in_conversation_id: str):
    actor = build_self_management_actor_context(
        user=user,
        actor_type=SelfManagementActorType.WEB_AGENT,
    )
    return SelfManagementToolGateway(
        actor,
        surface=SelfManagementSurface.WEB_AGENT,
        web_agent_conversation_id=built_in_conversation_id,
    )


def _build_anchor(message: AgentMessage) -> dict[str, str]:
    return {
        "message_id": str(message.id),
        "updated_at": message.updated_at.isoformat(),
        "status": message.status,
    }


async def _create_agent_text_message(
    async_db_session,
    *,
    user_id: UUID,
    conversation_id: UUID,
    content: str,
    status: str = "done",
) -> AgentMessage:
    message = AgentMessage(
        user_id=user_id,
        conversation_id=conversation_id,
        sender="agent",
        status=status,
    )
    async_db_session.add(message)
    await async_db_session.flush()
    async_db_session.add(
        AgentMessageBlock(
            user_id=user_id,
            message_id=message.id,
            block_seq=1,
            block_type="text",
            content=content,
            is_finished=status == "done",
            source="final_snapshot" if status == "done" else "stream",
        )
    )
    await async_db_session.commit()
    await async_db_session.refresh(message)
    return message


async def _append_agent_text_block(
    async_db_session,
    *,
    user_id: UUID,
    message: AgentMessage,
    content: str,
    status: str,
    block_seq: int,
) -> AgentMessage:
    setattr(message, "status", status)
    async_db_session.add(
        AgentMessageBlock(
            user_id=user_id,
            message_id=message.id,
            block_seq=block_seq,
            block_type="text",
            content=content,
            is_finished=status == "done",
            source="final_snapshot" if status == "done" else "stream",
        )
    )
    await async_db_session.commit()
    await async_db_session.refresh(message)
    return message


async def test_follow_up_service_sets_and_gets_tracked_sessions(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    built_in_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Built-in Follow-up Conversation",
    )
    target_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Tracked Target Conversation",
    )
    latest_agent_message = await _create_agent_text_message(
        async_db_session,
        user_id=user.id,
        conversation_id=target_thread.id,
        content="Initial target result",
    )
    gateway = _build_web_agent_gateway(user, str(built_in_thread.id))

    set_payload = await built_in_follow_up_service.set_tracked_sessions(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        conversation_ids=[str(target_thread.id)],
    )
    get_payload = await built_in_follow_up_service.get_follow_up_state(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
    )

    assert set_payload["status"] == "waiting"
    assert set_payload["built_in_conversation_id"] == str(built_in_thread.id)
    assert set_payload["tracked_sessions"] == [
        {
            "conversation_id": str(target_thread.id),
            "title": "Tracked Target Conversation",
            "status": "active",
            "latest_agent_message_id": str(latest_agent_message.id),
        }
    ]
    assert get_payload["tracked_sessions"] == [
        {
            "conversation_id": str(target_thread.id),
            "title": "Tracked Target Conversation",
            "status": "active",
            "latest_agent_message_id": str(latest_agent_message.id),
        }
    ]


async def test_follow_up_service_claims_new_results_without_advancing_anchor(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    built_in_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Built-in Follow-up Conversation",
    )
    target_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Tracked Target Conversation",
    )
    first_agent_message = await _create_agent_text_message(
        async_db_session,
        user_id=user.id,
        conversation_id=target_thread.id,
        content="Initial target result",
    )
    gateway = _build_web_agent_gateway(user, str(built_in_thread.id))
    await built_in_follow_up_service.set_tracked_sessions(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        conversation_ids=[str(target_thread.id)],
    )

    second_agent_message = await _create_agent_text_message(
        async_db_session,
        user_id=user.id,
        conversation_id=target_thread.id,
        content="Updated target result",
    )

    requests = await built_in_follow_up_service.claim_due_follow_up_tasks(
        db=async_db_session,
        batch_size=10,
    )

    assert len(requests) == 1
    request = requests[0]
    assert request.built_in_conversation_id == str(built_in_thread.id)
    assert request.tracked_conversation_ids == (str(target_thread.id),)
    assert request.changed_conversation_ids == (str(target_thread.id),)
    assert request.previous_target_agent_message_anchors == {
        str(target_thread.id): _build_anchor(first_agent_message)
    }
    assert request.observed_target_agent_message_anchors == {
        str(target_thread.id): _build_anchor(second_agent_message)
    }

    running_payload = await built_in_follow_up_service.get_follow_up_state(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
    )
    assert running_payload["status"] == "running"
    assert running_payload["tracked_sessions"] == [
        {
            "conversation_id": str(target_thread.id),
            "title": "Tracked Target Conversation",
            "status": "active",
            "latest_agent_message_id": str(first_agent_message.id),
        }
    ]

    await built_in_follow_up_service.complete_follow_up_run(
        db=async_db_session,
        task_id=request.task_id,
        next_target_agent_message_anchors=request.observed_target_agent_message_anchors,
    )
    completed_payload = await built_in_follow_up_service.get_follow_up_state(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
    )

    assert completed_payload["status"] == "waiting"
    assert completed_payload["tracked_sessions"] == [
        {
            "conversation_id": str(target_thread.id),
            "title": "Tracked Target Conversation",
            "status": "active",
            "latest_agent_message_id": str(second_agent_message.id),
        }
    ]


async def test_follow_up_service_claims_same_message_when_status_or_updated_at_changes(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    built_in_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Built-in Follow-up Conversation",
    )
    target_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Tracked Target Conversation",
    )
    target_message = await _create_agent_text_message(
        async_db_session,
        user_id=user.id,
        conversation_id=target_thread.id,
        content="Initial streamed result",
        status="streaming",
    )
    first_anchor = _build_anchor(target_message)
    gateway = _build_web_agent_gateway(user, str(built_in_thread.id))
    await built_in_follow_up_service.set_tracked_sessions(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        conversation_ids=[str(target_thread.id)],
    )

    updated_message = await _append_agent_text_block(
        async_db_session,
        user_id=user.id,
        message=target_message,
        content="Final target result",
        status="done",
        block_seq=2,
    )
    second_anchor = _build_anchor(updated_message)

    requests = await built_in_follow_up_service.claim_due_follow_up_tasks(
        db=async_db_session,
        batch_size=10,
    )

    assert len(requests) == 1
    request = requests[0]
    assert request.changed_conversation_ids == (str(target_thread.id),)
    assert request.previous_target_agent_message_anchors == {
        str(target_thread.id): first_anchor
    }
    assert request.observed_target_agent_message_anchors == {
        str(target_thread.id): second_anchor
    }
    assert first_anchor["message_id"] == second_anchor["message_id"]
    assert first_anchor["status"] == "streaming"
    assert second_anchor["status"] == "done"

    await built_in_follow_up_service.complete_follow_up_run(
        db=async_db_session,
        task_id=request.task_id,
        next_target_agent_message_anchors=request.observed_target_agent_message_anchors,
    )

    assert (
        await built_in_follow_up_service.claim_due_follow_up_tasks(
            db=async_db_session,
            batch_size=10,
        )
        == []
    )
    completed_payload = await built_in_follow_up_service.get_follow_up_state(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
    )
    assert completed_payload["status"] == "waiting"
    assert completed_payload["tracked_sessions"] == [
        {
            "conversation_id": str(target_thread.id),
            "title": "Tracked Target Conversation",
            "status": "active",
            "latest_agent_message_id": str(updated_message.id),
        }
    ]


async def test_follow_up_service_add_tracked_sessions_merges_existing_targets(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    built_in_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Built-in Follow-up Conversation",
    )
    first_target_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="First Tracked Conversation",
    )
    second_target_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Second Tracked Conversation",
    )
    first_agent_message = await _create_agent_text_message(
        async_db_session,
        user_id=user.id,
        conversation_id=first_target_thread.id,
        content="First target result",
    )
    second_agent_message = await _create_agent_text_message(
        async_db_session,
        user_id=user.id,
        conversation_id=second_target_thread.id,
        content="Second target result",
    )
    gateway = _build_web_agent_gateway(user, str(built_in_thread.id))
    await built_in_follow_up_service.set_tracked_sessions(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        conversation_ids=[str(first_target_thread.id)],
    )

    payload = await built_in_follow_up_service.add_tracked_sessions(
        db=async_db_session,
        current_user=user,
        built_in_conversation_id=str(built_in_thread.id),
        conversation_ids=[str(second_target_thread.id)],
    )

    assert payload["status"] == "waiting"
    assert payload["tracked_sessions"] == [
        {
            "conversation_id": str(first_target_thread.id),
            "title": "First Tracked Conversation",
            "status": "active",
            "latest_agent_message_id": str(first_agent_message.id),
        },
        {
            "conversation_id": str(second_target_thread.id),
            "title": "Second Tracked Conversation",
            "status": "active",
            "latest_agent_message_id": str(second_agent_message.id),
        },
    ]
