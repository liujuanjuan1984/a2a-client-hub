from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY
from uuid import uuid4

import pytest

from app.features.self_management_shared import (
    delegated_conversation_service as delegated_conversation_service_module,
)
from app.features.self_management_shared.actor_context import (
    SelfManagementActorType,
    build_self_management_actor_context,
)
from app.features.self_management_shared.tool_gateway import (
    SelfManagementSurface,
    SelfManagementToolGateway,
)
from tests.support.utils import (
    create_a2a_agent,
    create_conversation_thread,
    create_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _build_gateway(user):
    actor = build_self_management_actor_context(
        user=user,
        actor_type=SelfManagementActorType.HUMAN_API,
    )
    return SelfManagementToolGateway(actor, surface=SelfManagementSurface.REST)


async def test_send_messages_to_sessions_uses_automation_invoke_path(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
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
            "delegated_by": "self_management_built_in_agent",
            "delegated_target_kind": "session",
            "delegated_target_id": str(thread.id),
            "message_kind": "delegated_session_message",
        }
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

    result = await delegated_conversation_service_module.self_management_delegated_conversation_service.send_messages_to_sessions(
        db=async_db_session,
        gateway=_build_gateway(user),
        current_user=user,
        conversation_ids=[thread.id],
        message="ping",
    )

    assert result["summary"] == {"requested": 1, "completed": 1, "failed": 0}
    assert result["items"] == [
        {
            "target_type": "session",
            "conversation_id": str(thread.id),
            "agent_id": str(agent.id),
            "agent_source": "personal",
            "agent_name": "Delegated Session Agent",
            "title": "Delegated Session Thread",
            "status": "completed",
            "response_content": "pong",
            "error": None,
            "error_code": None,
            "user_message_id": ANY,
            "agent_message_id": ANY,
        }
    ]


async def test_start_sessions_for_agents_uses_automation_invoke_path(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="delegated-agent",
        name="Delegated Agent",
    )

    runtime = SimpleNamespace(resolved=SimpleNamespace(name="Delegated Agent"))
    captured_conversation_id: str | None = None

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
            "delegated_by": "self_management_built_in_agent",
            "delegated_target_kind": "agent",
            "delegated_target_id": str(agent.id),
            "message_kind": "delegated_agent_message",
        }
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

    result = await delegated_conversation_service_module.self_management_delegated_conversation_service.start_sessions_for_agents(
        db=async_db_session,
        gateway=_build_gateway(user),
        current_user=user,
        agent_ids=[agent.id],
        message="hello",
    )

    assert result["summary"] == {"requested": 1, "completed": 1, "failed": 0}
    assert captured_conversation_id is not None
    assert result["items"] == [
        {
            "target_type": "agent",
            "agent_id": str(agent.id),
            "agent_source": "personal",
            "agent_name": "Delegated Agent",
            "conversation_id": captured_conversation_id,
            "status": "completed",
            "response_content": "agent pong",
            "error": None,
            "error_code": None,
            "user_message_id": ANY,
            "agent_message_id": ANY,
        }
    ]
