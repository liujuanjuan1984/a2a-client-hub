from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import (
    get_self_management_allowed_operations,
    get_self_management_interrupt_message,
    get_self_management_interrupt_tool_names,
    verify_jwt_token_claims,
)
from app.db.models.agent_message import AgentMessage
from app.features.self_management_agent import router as self_management_agent_router
from app.features.self_management_agent.service import (
    _WRITE_APPROVAL_SENTINEL,
    self_management_built_in_agent_service,
)
from app.features.sessions.service import session_hub_service
from tests.support.api_utils import create_test_client
from tests.support.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _FakeSwivalSession:
    last_init_kwargs: dict[str, object] | None = None
    last_message: str | None = None
    next_answer: str = "Built-in agent reply"
    ask_call_count: int = 0
    instance_count: int = 0
    instances: list["_FakeSwivalSession"] = []

    def __init__(self, **kwargs: object) -> None:
        type(self).last_init_kwargs = dict(kwargs)
        type(self).instance_count += 1
        type(self).instances.append(self)
        self._conv_state: dict[str, object] | None = None
        self.closed = False

    def ask(self, message: str) -> object:
        type(self).last_message = message
        type(self).ask_call_count += 1
        if self._conv_state is None:
            self._conv_state = {"messages": []}
        messages = cast(list[dict[str, str]], self._conv_state["messages"])
        messages.append({"role": "user", "content": message})
        messages.append({"role": "assistant", "content": type(self).next_answer})
        return SimpleNamespace(answer=type(self).next_answer, exhausted=False)

    def close(self) -> None:
        self.closed = True


def _install_fake_swival(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeSwivalSession.last_init_kwargs = None
    _FakeSwivalSession.last_message = None
    _FakeSwivalSession.next_answer = "Built-in agent reply"
    _FakeSwivalSession.ask_call_count = 0
    _FakeSwivalSession.instance_count = 0
    _FakeSwivalSession.instances = []
    module = ModuleType("swival")
    module.Session = _FakeSwivalSession
    monkeypatch.setitem(sys.modules, "swival", module)


def _reset_built_in_agent_runtime() -> None:
    self_management_built_in_agent_service._conversation_registry.clear()


def _configure_swival_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "self_management_swival_provider",
        "openai",
    )
    monkeypatch.setattr(
        settings,
        "self_management_swival_model",
        "gpt-test",
    )
    monkeypatch.setattr(
        settings,
        "self_management_swival_import_paths",
        [],
    )
    monkeypatch.setattr(
        settings,
        "self_management_swival_base_url",
        "https://example.com/v1",
    )
    monkeypatch.setattr(
        settings,
        "self_management_swival_api_key",
        "test-api-key",
    )
    monkeypatch.setattr(
        settings,
        "self_management_swival_mcp_base_url",
        "http://internal-mcp",
    )
    monkeypatch.setattr(
        settings,
        "self_management_swival_reasoning_effort",
        "medium",
    )
    monkeypatch.setattr(settings, "self_management_swival_max_turns", 6)
    monkeypatch.setattr(settings, "self_management_swival_max_output_tokens", 2048)


def _new_conversation_id() -> str:
    return str(uuid4())


async def test_built_in_agent_profile_exposes_full_available_tool_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)

    profile = self_management_built_in_agent_service.get_profile()

    assert profile.configured is True
    assert profile.resources == ("agents", "jobs", "sessions")
    assert [item.operation_id for item in profile.tool_definitions] == [
        "self.agents.get",
        "self.agents.list",
        "self.agents.update_config",
        "self.jobs.get",
        "self.jobs.list",
        "self.jobs.pause",
        "self.sessions.get",
        "self.sessions.list",
    ]


async def test_built_in_agent_run_uses_swival_with_authenticated_mcp_server(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="List my jobs",
        allow_write_tools=False,
    )

    assert result.answer == "Built-in agent reply"
    assert result.status == "completed"
    assert result.exhausted is False
    assert result.runtime == "swival"
    assert result.resources == ("agents", "jobs", "sessions")
    assert result.tool_names == (
        "self.agents.get",
        "self.agents.list",
        "self.jobs.get",
        "self.jobs.list",
        "self.sessions.get",
        "self.sessions.list",
    )
    assert result.write_tools_enabled is False
    assert result.interrupt is None
    assert _FakeSwivalSession.last_message == "List my jobs"
    assert _FakeSwivalSession.ask_call_count == 1
    assert _FakeSwivalSession.last_init_kwargs is not None
    assert _FakeSwivalSession.last_init_kwargs["provider"] == "openai"
    assert _FakeSwivalSession.last_init_kwargs["model"] == "gpt-test"
    assert _FakeSwivalSession.last_init_kwargs["base_url"] == "https://example.com/v1"
    assert (
        _FakeSwivalSession.last_init_kwargs["api_key"]
        == "test-api-key"  # pragma: allowlist secret
    )
    assert _FakeSwivalSession.last_init_kwargs["reasoning_effort"] == "medium"
    assert _FakeSwivalSession.last_init_kwargs["max_turns"] == 6
    assert _FakeSwivalSession.last_init_kwargs["max_output_tokens"] == 2048
    assert _FakeSwivalSession.last_init_kwargs["files"] == "none"
    assert _FakeSwivalSession.last_init_kwargs["commands"] == "none"
    assert _FakeSwivalSession.last_init_kwargs["no_skills"] is True
    assert _FakeSwivalSession.last_init_kwargs["history"] is False
    assert _FakeSwivalSession.last_init_kwargs["memory"] is False
    assert _FakeSwivalSession.last_init_kwargs["base_dir"].endswith("/backend")
    assert "built-in a2a-client-hub self-management assistant" in cast(
        str,
        _FakeSwivalSession.last_init_kwargs["system_prompt"],
    )
    assert "This run is read-only." in cast(
        str,
        _FakeSwivalSession.last_init_kwargs["system_prompt"],
    )
    mcp_servers = cast(
        dict[str, dict[str, Any]],
        _FakeSwivalSession.last_init_kwargs["mcp_servers"],
    )
    server_config = mcp_servers["a2a-client-hub"]
    assert server_config["url"] == "http://internal-mcp/mcp/"
    auth_header = cast(str, server_config["headers"]["Authorization"])
    assert auth_header.startswith("Bearer ")
    raw_token = auth_header.split("Bearer ", 1)[1]
    claims = verify_jwt_token_claims(raw_token, expected_type="access")
    assert claims is not None
    assert claims.subject == str(user.id)
    assert get_self_management_allowed_operations(claims) == frozenset(
        result.tool_names
    )


async def test_built_in_agent_write_approved_run_uses_write_enabled_mcp_surface(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=True,
    )

    assert result.tool_names == (
        "self.agents.get",
        "self.agents.list",
        "self.agents.update_config",
        "self.jobs.get",
        "self.jobs.list",
        "self.jobs.pause",
        "self.sessions.get",
        "self.sessions.list",
    )
    assert result.status == "completed"
    assert result.write_tools_enabled is True
    assert _FakeSwivalSession.last_init_kwargs is not None
    assert _FakeSwivalSession.last_init_kwargs["mcp_servers"]["a2a-client-hub"][
        "url"
    ] == ("http://internal-mcp/mcp-write/")
    assert "explicitly approved write tools" in cast(
        str,
        _FakeSwivalSession.last_init_kwargs["system_prompt"],
    )


async def test_built_in_agent_profile_route_requires_auth(async_session_maker) -> None:
    _reset_built_in_agent_runtime()
    async with create_test_client(
        self_management_agent_router.router,
        async_session_maker=async_session_maker,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.get(
            f"{settings.api_v1_prefix}/me/self-management/agent"
        )

    assert response.status_code == 401


async def test_built_in_agent_run_route_returns_swival_result(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    async with create_test_client(
        self_management_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        profile_response = await client.get(
            f"{settings.api_v1_prefix}/me/self-management/agent"
        )
        run_response = await client.post(
            f"{settings.api_v1_prefix}/me/self-management/agent:run",
            json={"conversationId": conversation_id, "message": "Pause my job"},
        )

    assert profile_response.status_code == 200
    assert profile_response.json()["resources"] == ["agents", "jobs", "sessions"]
    assert [item["operation_id"] for item in profile_response.json()["tools"]] == [
        "self.agents.get",
        "self.agents.list",
        "self.agents.update_config",
        "self.jobs.get",
        "self.jobs.list",
        "self.jobs.pause",
        "self.sessions.get",
        "self.sessions.list",
    ]
    assert run_response.status_code == 200
    assert run_response.json() == {
        "status": "completed",
        "answer": "Built-in agent reply",
        "exhausted": False,
        "runtime": "swival",
        "resources": ["agents", "jobs", "sessions"],
        "tools": [
            "self.agents.get",
            "self.agents.list",
            "self.jobs.get",
            "self.jobs.list",
            "self.sessions.get",
            "self.sessions.list",
        ],
        "write_tools_enabled": False,
        "interrupt": None,
    }


async def test_built_in_agent_run_persists_session_thread_and_messages(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="List my jobs",
        allow_write_tools=False,
    )

    assert result.status == "completed"

    session_item, _db_mutated = await session_hub_service.get_session(
        async_db_session,
        user_id=cast(Any, user.id),
        conversation_id=conversation_id,
    )
    assert session_item["conversationId"] == conversation_id
    assert session_item["agent_id"] == "self-management-assistant"
    assert session_item["agent_source"] == "builtin"

    messages, _extra, _db_mutated = await session_hub_service.list_messages(
        async_db_session,
        user_id=cast(Any, user.id),
        conversation_id=conversation_id,
        before=None,
        limit=20,
    )
    assert [item["role"] for item in messages] == ["user", "agent"]
    assert messages[0]["content"] == "List my jobs"
    assert messages[1]["content"] == "Built-in agent reply"


async def test_built_in_agent_interrupt_and_resolution_are_persisted(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = (
        "I can pause the requested job after you approve write access.\n"
        f"{_WRITE_APPROVAL_SENTINEL}"
    )

    interrupt_result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    assert interrupt_result.interrupt is not None

    reject_result = (
        await self_management_built_in_agent_service.reply_permission_interrupt(
            db=async_db_session,
            current_user=user,
            request_id=interrupt_result.interrupt.request_id,
            reply="reject",
        )
    )
    assert reject_result.answer == "Write approval was rejected. No changes were made."

    messages, _extra, _db_mutated = await session_hub_service.list_messages(
        async_db_session,
        user_id=cast(Any, user.id),
        conversation_id=conversation_id,
        before=None,
        limit=20,
    )
    assert [item["role"] for item in messages] == ["user", "agent", "agent"]

    system_messages = list(
        (
            await async_db_session.scalars(
                select(AgentMessage)
                .where(
                    AgentMessage.user_id == cast(Any, user.id),
                    AgentMessage.conversation_id == UUID(conversation_id),
                    AgentMessage.sender == "system",
                )
                .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
            )
        ).all()
    )
    assert len(system_messages) == 2
    asked_interrupt = cast(dict[str, Any], system_messages[0].message_metadata)[
        "interrupt"
    ]
    resolved_interrupt = cast(dict[str, Any], system_messages[1].message_metadata)[
        "interrupt"
    ]
    assert asked_interrupt["phase"] == "asked"
    assert asked_interrupt["type"] == "permission"
    assert resolved_interrupt["phase"] == "resolved"
    assert resolved_interrupt["resolution"] == "rejected"


async def test_built_in_agent_can_recover_unresolved_permission_interrupts(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = (
        "I can pause the requested job after you approve write access.\n"
        f"{_WRITE_APPROVAL_SENTINEL}"
    )

    interrupt_result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )

    recovered = await self_management_built_in_agent_service.recover_pending_interrupts(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
    )

    assert interrupt_result.interrupt is not None
    assert len(recovered) == 1
    assert recovered[0].request_id == interrupt_result.interrupt.request_id
    assert recovered[0].session_id == conversation_id
    assert recovered[0].type == "permission"
    assert recovered[0].details["permission"] == "self-management-write"
    assert recovered[0].details["patterns"] == [
        "self.agents.update_config",
        "self.jobs.pause",
    ]


async def test_built_in_agent_recovery_ignores_resolved_interrupts(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = (
        "I can pause the requested job after you approve write access.\n"
        f"{_WRITE_APPROVAL_SENTINEL}"
    )

    interrupt_result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    assert interrupt_result.interrupt is not None

    await self_management_built_in_agent_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt_result.interrupt.request_id,
        reply="reject",
    )

    recovered = await self_management_built_in_agent_service.recover_pending_interrupts(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
    )

    assert recovered == []


async def test_built_in_agent_run_route_allows_write_tools_only_when_explicitly_enabled(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    async with create_test_client(
        self_management_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        run_response = await client.post(
            f"{settings.api_v1_prefix}/me/self-management/agent:run",
            json={
                "conversationId": conversation_id,
                "message": "Pause my job",
                "allow_write_tools": True,
            },
        )

    assert run_response.status_code == 200
    assert run_response.json()["status"] == "completed"
    assert run_response.json()["write_tools_enabled"] is True
    assert "self.jobs.pause" in run_response.json()["tools"]


async def test_built_in_agent_read_only_run_can_raise_permission_interrupt(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    _FakeSwivalSession.next_answer = (
        "I can pause the requested job after you approve write access.\n"
        f"{_WRITE_APPROVAL_SENTINEL}"
    )
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )

    assert result.status == "interrupted"
    assert (
        result.answer == "I can pause the requested job after you approve write access."
    )
    assert result.write_tools_enabled is False
    assert result.interrupt is not None
    assert result.interrupt.permission == "self-management-write"
    assert result.interrupt.patterns == (
        "self.agents.update_config",
        "self.jobs.pause",
    )
    claims = verify_jwt_token_claims(
        result.interrupt.request_id,
        expected_type="self_management_interrupt",
    )
    assert claims is not None
    assert claims.subject == str(user.id)
    assert get_self_management_interrupt_message(claims) == "Pause my job"
    assert get_self_management_interrupt_tool_names(claims) == (
        "self.agents.update_config",
        "self.jobs.pause",
    )


async def test_built_in_agent_permission_reply_once_resumes_with_write_tools(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    interrupt = self_management_built_in_agent_service._build_permission_interrupt(
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        answer="Need approval",
    )

    result = await self_management_built_in_agent_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt.request_id,
        reply="once",
    )

    assert result.status == "completed"
    assert result.write_tools_enabled is True
    assert "self.jobs.pause" in result.tool_names
    assert _FakeSwivalSession.ask_call_count == 1
    assert _FakeSwivalSession.last_message == "Pause my job"
    assert _FakeSwivalSession.last_init_kwargs is not None
    assert _FakeSwivalSession.last_init_kwargs["mcp_servers"]["a2a-client-hub"][
        "url"
    ] == ("http://internal-mcp/mcp-write/")
    assert _FakeSwivalSession.instance_count == 1


async def test_built_in_agent_permission_reply_reject_returns_no_change_result(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    interrupt = self_management_built_in_agent_service._build_permission_interrupt(
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        answer="Need approval",
    )

    result = await self_management_built_in_agent_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt.request_id,
        reply="reject",
    )

    assert result.status == "completed"
    assert result.answer == "Write approval was rejected. No changes were made."
    assert result.write_tools_enabled is False
    assert result.exhausted is False
    assert _FakeSwivalSession.ask_call_count == 0


async def test_built_in_agent_permission_reply_route_resumes_or_rejects(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = (
        "I can pause the requested job after you approve write access.\n"
        f"{_WRITE_APPROVAL_SENTINEL}"
    )

    async with create_test_client(
        self_management_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        interrupt_response = await client.post(
            f"{settings.api_v1_prefix}/me/self-management/agent:run",
            json={"conversationId": conversation_id, "message": "Pause my job"},
        )
        assert interrupt_response.status_code == 200
        interrupt_payload = interrupt_response.json()
        assert interrupt_payload["status"] == "interrupted"
        request_id = interrupt_payload["interrupt"]["requestId"]

        _FakeSwivalSession.next_answer = "Paused the requested job."
        approve_response = await client.post(
            f"{settings.api_v1_prefix}/me/self-management/agent/interrupts/permission:reply",
            json={"requestId": request_id, "reply": "once"},
        )

    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "completed"
    assert approve_response.json()["write_tools_enabled"] is True
    assert approve_response.json()["interrupt"] is None


async def test_built_in_agent_interrupt_recovery_route_returns_unresolved_interrupts(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = (
        "I can pause the requested job after you approve write access.\n"
        f"{_WRITE_APPROVAL_SENTINEL}"
    )

    await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    await async_db_session.commit()

    async with create_test_client(
        self_management_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/self-management/agent/interrupts:recover",
            json={"conversationId": conversation_id},
        )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "requestId": response.json()["items"][0]["requestId"],
            "sessionId": conversation_id,
            "type": "permission",
            "phase": "asked",
            "details": {
                "permission": "self-management-write",
                "patterns": [
                    "self.agents.update_config",
                    "self.jobs.pause",
                ],
                "displayMessage": "I can pause the requested job after you approve write access.",
            },
        }
    ]


async def test_built_in_agent_permission_reply_route_rejects_other_user_interrupt(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    owner = await create_user(async_db_session)
    other_user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    interrupt = self_management_built_in_agent_service._build_permission_interrupt(
        current_user=owner,
        conversation_id=conversation_id,
        message="Pause my job",
        answer="Need approval",
    )

    async with create_test_client(
        self_management_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=other_user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/self-management/agent/interrupts/permission:reply",
            json={"requestId": interrupt.request_id, "reply": "once"},
        )

    assert response.status_code == 400
    assert "does not belong to the current user" in response.json()["detail"]


async def test_built_in_agent_reuses_conversation_session_for_follow_up_turns(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="List my jobs",
        allow_write_tools=False,
    )
    await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Now list my agents",
        allow_write_tools=False,
    )

    assert _FakeSwivalSession.instance_count == 1
    assert _FakeSwivalSession.ask_call_count == 2
    assert _FakeSwivalSession.instances[0]._conv_state is not None
    assert len(_FakeSwivalSession.instances[0]._conv_state["messages"]) == 4


async def test_built_in_agent_rehydrates_runtime_from_durable_history_after_registry_loss(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="List my jobs",
        allow_write_tools=False,
    )
    _reset_built_in_agent_runtime()

    await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Now list my agents",
        allow_write_tools=False,
    )

    assert _FakeSwivalSession.instance_count == 2
    assert _FakeSwivalSession.ask_call_count == 2
    assert _FakeSwivalSession.instances[1]._conv_state is not None
    assert len(_FakeSwivalSession.instances[1]._conv_state["messages"]) == 4
    assert _FakeSwivalSession.instances[1]._conv_state["messages"][0] == {
        "role": "user",
        "content": "List my jobs",
    }
    assert _FakeSwivalSession.instances[1]._conv_state["messages"][1] == {
        "role": "assistant",
        "content": "Built-in agent reply",
    }


async def test_built_in_agent_permission_reply_always_enables_session_scoped_write_tools(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    interrupt = self_management_built_in_agent_service._build_permission_interrupt(
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        answer="Need approval",
    )

    always_result = (
        await self_management_built_in_agent_service.reply_permission_interrupt(
            db=async_db_session,
            current_user=user,
            request_id=interrupt.request_id,
            reply="always",
        )
    )
    follow_up_result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause it now",
        allow_write_tools=False,
    )

    assert always_result.write_tools_enabled is True
    assert follow_up_result.write_tools_enabled is True
    assert "self.jobs.pause" in follow_up_result.tool_names
    assert _FakeSwivalSession.instance_count == 1
    assert _FakeSwivalSession.ask_call_count == 2
    assert _FakeSwivalSession.last_init_kwargs is not None
    assert _FakeSwivalSession.last_init_kwargs["mcp_servers"]["a2a-client-hub"][
        "url"
    ] == ("http://internal-mcp/mcp-write/")


async def test_built_in_agent_runtime_patches_private_swival_mcp_tool_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)

    swival_module = ModuleType("swival")
    swival_module.Session = _FakeSwivalSession
    mcp_module = ModuleType("swival.mcp_client")

    def _fake_converter(
        _server_name: str, tool: object
    ) -> tuple[dict[str, object], str]:
        return (
            {
                "type": "function",
                "function": {
                    "name": "mcp__demo__tool",
                    "_mcp_original_name": getattr(tool, "name", "demo.tool"),
                },
            },
            getattr(tool, "name", "demo.tool"),
        )

    mcp_module._mcp_tool_to_openai = _fake_converter
    monkeypatch.setitem(sys.modules, "swival", swival_module)
    monkeypatch.setitem(sys.modules, "swival.mcp_client", mcp_module)

    session_cls = self_management_built_in_agent_service._load_swival_session_cls()

    assert session_cls is _FakeSwivalSession
    schema, _original_name = mcp_module._mcp_tool_to_openai(
        "demo", SimpleNamespace(name="demo.tool")
    )
    assert schema["function"]["name"] == "mcp__demo__tool"
    assert "_mcp_original_name" not in schema["function"]
