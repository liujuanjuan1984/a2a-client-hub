from __future__ import annotations

from typing import cast
from uuid import UUID

import pytest

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.features.hub_assistant_shared import task_job as task_job_module
from app.features.hub_assistant_shared.actor_context import (
    HubAssistantActorType,
    build_hub_assistant_actor_context,
)
from app.features.hub_assistant_shared.task_service import (
    HubAssistantFollowUpTaskRequest,
    hub_assistant_task_service,
)
from app.features.hub_assistant_shared.tool_gateway import (
    HubAssistantSurface,
    HubAssistantToolGateway,
)
from tests.support.utils import create_conversation_thread, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _build_web_agent_gateway(user, hub_assistant_conversation_id: str):
    actor = build_hub_assistant_actor_context(
        user=user,
        actor_type=HubAssistantActorType.WEB_AGENT,
    )
    return HubAssistantToolGateway(
        actor,
        surface=HubAssistantSurface.WEB_AGENT,
        web_agent_conversation_id=hub_assistant_conversation_id,
    )


def _build_anchor(message: AgentMessage) -> dict[str, str]:
    return {
        "message_id": str(message.id),
        "updated_at": message.updated_at.isoformat(),
        "status": message.status,
    }


async def _append_agent_text_message(
    async_db_session,
    *,
    user_id: UUID,
    conversation_id: UUID,
    content: str,
) -> AgentMessage:
    message = AgentMessage(
        user_id=user_id,
        conversation_id=conversation_id,
        sender="agent",
        status="done",
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
            is_finished=True,
            source="final_snapshot",
        )
    )
    await async_db_session.commit()
    await async_db_session.refresh(message)
    return message


async def test_hub_assistant_task_job_wakes_and_rearms_follow_up_task(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    user_id = cast(UUID, user.id)
    hub_assistant_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Built-in Follow-up Conversation",
    )
    target_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Tracked Target Conversation",
    )
    first_agent_message = await _append_agent_text_message(
        async_db_session,
        user_id=user_id,
        conversation_id=target_thread.id,
        content="Initial target result",
    )
    gateway = _build_web_agent_gateway(user, str(hub_assistant_thread.id))
    await hub_assistant_task_service.set_tracked_sessions(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        conversation_ids=[str(target_thread.id)],
    )
    second_agent_message = await _append_agent_text_message(
        async_db_session,
        user_id=user_id,
        conversation_id=target_thread.id,
        content="Updated target result",
    )
    second_agent_message_id = str(second_agent_message.id)

    recorded_requests: list[HubAssistantFollowUpTaskRequest] = []

    async def _fake_run_durable_follow_up(**kwargs):
        recorded_requests.append(kwargs["request"])
        return type(
            "_FakeResult",
            (),
            {
                "status": "completed",
                "answer": "summarized",
                "exhausted": False,
                "runtime": "swival",
                "resources": ("agents", "followups", "jobs", "sessions"),
                "tool_names": ("self.followups.get",),
                "write_tools_enabled": False,
                "interrupt": None,
                "continuation": None,
            },
        )()

    monkeypatch.setattr(
        task_job_module.hub_assistant_service,
        "run_durable_follow_up",
        _fake_run_durable_follow_up,
    )

    await task_job_module.dispatch_due_hub_assistant_tasks(batch_size=10)

    assert len(recorded_requests) == 1
    request = recorded_requests[0]
    assert request.previous_target_agent_message_anchors == {
        str(target_thread.id): _build_anchor(first_agent_message)
    }
    assert request.observed_target_agent_message_anchors == {
        str(target_thread.id): _build_anchor(second_agent_message)
    }

    async_db_session.expire_all()
    await async_db_session.refresh(user)
    payload = await hub_assistant_task_service.get_follow_up_state(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
    )
    assert payload["status"] == "waiting"
    assert payload["tracked_sessions"] == [
        {
            "conversation_id": str(target_thread.id),
            "title": "Tracked Target Conversation",
            "status": "active",
            "latest_agent_message_id": second_agent_message_id,
        }
    ]
