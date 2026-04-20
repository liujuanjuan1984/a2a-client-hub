from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.features.hub_access.actor_context import (
    HubActorType,
    build_hub_actor_context,
)
from app.features.hub_access.operation_gateway import (
    HubOperationGateway,
    HubSurface,
)
from app.features.hub_assistant.shared import (
    delegated_conversation_service as delegated_conversation_service_module,
)
from app.features.hub_assistant.shared.task_job import (
    dispatch_due_hub_assistant_tasks,
)
from tests.support.utils import (
    create_a2a_agent,
    create_conversation_thread,
    create_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _build_gateway(user, hub_assistant_conversation_id: str):
    actor = build_hub_actor_context(
        user=user,
        actor_type=HubActorType.WEB_AGENT,
    )
    return HubOperationGateway(
        actor,
        surface=HubSurface.WEB_AGENT,
        web_agent_conversation_id=hub_assistant_conversation_id,
    )


async def test_send_messages_to_sessions_uses_automation_invoke_path(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    hub_assistant_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Built-in Conversation",
    )
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="delegated-session",
        name="Delegated Session Agent",
    )
    thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        agent_source="personal",
        title="Delegated Session Thread",
    )

    runtime = SimpleNamespace(resolved=SimpleNamespace(name="Delegated Session Agent"))
    release_dispatch = asyncio.Event()

    async def _fake_load_for_external_call(_db, _loader):
        return runtime

    async def _fake_run_background_invoke(**kwargs):
        assert kwargs["runtime"] is runtime
        assert kwargs["user_id"] == user.id
        assert kwargs["agent_id"] == agent.id
        assert kwargs["agent_source"] == "personal"
        assert kwargs["payload"].query == "ping"
        assert kwargs["payload"].conversation_id == str(thread.id)
        assert kwargs["user_sender"] == "automation"
        assert kwargs["extra_persisted_metadata"] == {
            "delegated_by": "hub_assistant",
            "delegated_target_kind": "session",
            "delegated_target_id": str(thread.id),
            "message_kind": "delegated_session_message",
        }
        await release_dispatch.wait()
        return {
            "success": True,
            "response_content": "pong",
            "error": None,
            "error_code": None,
            "conversation_id": thread.id,
            "message_refs": {
                "user_message_id": uuid4(),
                "agent_message_id": uuid4(),
            },
        }

    monkeypatch.setattr(
        delegated_conversation_service_module,
        "load_for_external_call",
        _fake_load_for_external_call,
    )
    monkeypatch.setattr(
        delegated_conversation_service_module,
        "run_background_invoke",
        _fake_run_background_invoke,
    )
    monkeypatch.setattr(
        delegated_conversation_service_module,
        "get_a2a_service",
        lambda: SimpleNamespace(gateway=object()),
    )

    result = await asyncio.wait_for(
        delegated_conversation_service_module.hub_assistant_delegated_conversation_service.send_messages_to_sessions(
            db=async_db_session,
            gateway=_build_gateway(user, str(hub_assistant_thread.id)),
            current_user=user,
            conversation_ids=[thread.id],
            message="ping",
        ),
        timeout=1.0,
    )

    assert result["summary"] == {"requested": 1, "accepted": 1, "failed": 0}
    assert result["items"] == [
        {
            "target_type": "session",
            "conversation_id": str(thread.id),
            "agent_id": str(agent.id),
            "agent_source": "personal",
            "agent_name": "Delegated Session Agent",
            "title": "Delegated Session Thread",
            "status": "accepted",
        }
    ]
    await async_db_session.commit()
    release_dispatch.set()
    await dispatch_due_hub_assistant_tasks()


async def test_start_sessions_for_agents_uses_automation_invoke_path(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    hub_assistant_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Built-in Conversation",
    )
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="delegated-agent",
        name="Delegated Agent",
    )

    runtime = SimpleNamespace(resolved=SimpleNamespace(name="Delegated Agent"))
    captured_conversation_id: str | None = None
    release_dispatch = asyncio.Event()

    async def _fake_load_for_external_call(_db, _loader):
        return runtime

    async def _fake_run_background_invoke(**kwargs):
        nonlocal captured_conversation_id
        assert kwargs["runtime"] is runtime
        assert kwargs["user_id"] == user.id
        assert kwargs["agent_id"] == agent.id
        assert kwargs["agent_source"] == "personal"
        assert kwargs["payload"].query == "hello"
        assert isinstance(kwargs["payload"].conversation_id, str)
        assert kwargs["payload"].conversation_id
        captured_conversation_id = kwargs["payload"].conversation_id
        assert kwargs["user_sender"] == "automation"
        assert kwargs["extra_persisted_metadata"] == {
            "delegated_by": "hub_assistant",
            "delegated_target_kind": "agent",
            "delegated_target_id": str(agent.id),
            "message_kind": "delegated_agent_message",
        }
        await release_dispatch.wait()
        return {
            "success": True,
            "response_content": "agent pong",
            "error": None,
            "error_code": None,
            "conversation_id": captured_conversation_id,
            "message_refs": {
                "user_message_id": uuid4(),
                "agent_message_id": uuid4(),
            },
        }

    monkeypatch.setattr(
        delegated_conversation_service_module,
        "load_for_external_call",
        _fake_load_for_external_call,
    )
    monkeypatch.setattr(
        delegated_conversation_service_module,
        "run_background_invoke",
        _fake_run_background_invoke,
    )
    monkeypatch.setattr(
        delegated_conversation_service_module,
        "get_a2a_service",
        lambda: SimpleNamespace(gateway=object()),
    )

    result = await asyncio.wait_for(
        delegated_conversation_service_module.hub_assistant_delegated_conversation_service.start_sessions_for_agents(
            db=async_db_session,
            gateway=_build_gateway(user, str(hub_assistant_thread.id)),
            current_user=user,
            agent_ids=[agent.id],
            message="hello",
        ),
        timeout=1.0,
    )

    assert result["summary"] == {"requested": 1, "accepted": 1, "failed": 0}
    returned_conversation_id = result["items"][0]["conversation_id"]
    assert isinstance(returned_conversation_id, str)
    assert returned_conversation_id
    assert result["items"] == [
        {
            "target_type": "agent",
            "agent_id": str(agent.id),
            "agent_source": "personal",
            "agent_name": "Delegated Agent",
            "conversation_id": returned_conversation_id,
            "status": "accepted",
        }
    ]
    await async_db_session.commit()
    release_dispatch.set()
    await dispatch_due_hub_assistant_tasks()
    assert captured_conversation_id == returned_conversation_id
