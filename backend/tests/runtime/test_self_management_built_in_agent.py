from __future__ import annotations

import copy
import sys
from pathlib import Path
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
from app.features.self_management_agent import (
    service as self_management_agent_service_module,
)
from app.features.self_management_agent.service import (
    _WRITE_APPROVAL_SENTINEL,
    SelfManagementBuiltInAgentUnavailableError,
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
    next_messages: list[dict[str, object]] | None = None
    next_error: Exception | None = None
    ask_call_count: int = 0
    instance_count: int = 0
    instances: list["_FakeSwivalSession"] = []

    def __init__(self, **kwargs: object) -> None:
        type(self).last_init_kwargs = dict(kwargs)
        type(self).instance_count += 1
        type(self).instances.append(self)
        self._system_prompt = cast(str, kwargs.get("system_prompt", ""))
        self._conv_state: dict[str, object] | None = None
        self.closed = False

    def _setup(self) -> None:
        if self._conv_state is None:
            self._conv_state = self._make_per_run_state(
                system_content=self._system_with_memory("", policy="interactive")
            )

    def _system_with_memory(
        self,
        _question: str,
        report: object | None = None,
        policy: str = "autonomous",
    ) -> str:
        del report, policy
        return self._system_prompt

    def _make_per_run_state(
        self,
        system_content: str | None = None,
    ) -> dict[str, object]:
        messages: list[dict[str, str]] = []
        if isinstance(system_content, str) and system_content.strip():
            messages.append({"role": "system", "content": system_content})
        return {"messages": messages}

    def ask(self, message: str) -> object:
        if type(self).next_error is not None:
            exc = type(self).next_error
            type(self).next_error = None
            raise exc
        type(self).last_message = message
        type(self).ask_call_count += 1
        if self._conv_state is None:
            self._setup()
        messages = cast(list[dict[str, str]], self._conv_state["messages"])
        messages.append({"role": "user", "content": message})
        messages.append({"role": "assistant", "content": type(self).next_answer})
        result_messages = (
            copy.deepcopy(type(self).next_messages)
            if type(self).next_messages is not None
            else copy.deepcopy(messages)
        )
        type(self).next_messages = None
        return SimpleNamespace(
            answer=type(self).next_answer,
            exhausted=False,
            messages=result_messages,
        )

    def close(self) -> None:
        self.closed = True


def _install_fake_swival(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeSwivalSession.last_init_kwargs = None
    _FakeSwivalSession.last_message = None
    _FakeSwivalSession.next_answer = "Built-in agent reply"
    _FakeSwivalSession.next_messages = None
    _FakeSwivalSession.next_error = None
    _FakeSwivalSession.ask_call_count = 0
    _FakeSwivalSession.instance_count = 0
    _FakeSwivalSession.instances = []
    module = ModuleType("swival")
    module.Session = _FakeSwivalSession
    monkeypatch.setitem(sys.modules, "swival", module)


def _reset_built_in_agent_runtime() -> None:
    for task in list(self_management_built_in_agent_service._continuation_tasks):
        task.cancel()
    self_management_built_in_agent_service._continuation_tasks.clear()
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
        "self_management_swival_tool_executable",
        None,
    )
    monkeypatch.setattr(
        settings,
        "self_management_swival_runtime_root",
        None,
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


def _approval_answer(message: str, *operation_ids: str) -> str:
    return (
        f"{message}\n"
        f"{_WRITE_APPROVAL_SENTINEL}\n"
        "[[SELF_MANAGEMENT_WRITE_OPERATIONS:"
        f"{','.join(operation_ids)}"
        "]]"
    )


async def test_built_in_agent_profile_exposes_full_available_tool_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)

    profile = self_management_built_in_agent_service.get_profile()

    assert profile.configured is True
    assert profile.resources == ("agents", "jobs", "sessions")
    assert [item.operation_id for item in profile.tool_definitions] == [
        "self.agents.check_health",
        "self.agents.check_health_all",
        "self.agents.create",
        "self.agents.delete",
        "self.agents.get",
        "self.agents.list",
        "self.agents.start_sessions",
        "self.agents.update_config",
        "self.jobs.create",
        "self.jobs.delete",
        "self.jobs.get",
        "self.jobs.list",
        "self.jobs.pause",
        "self.jobs.resume",
        "self.jobs.update",
        "self.jobs.update_prompt",
        "self.jobs.update_schedule",
        "self.sessions.archive",
        "self.sessions.get",
        "self.sessions.get_latest_messages",
        "self.sessions.list",
        "self.sessions.send_message",
        "self.sessions.unarchive",
        "self.sessions.update",
    ]


async def test_built_in_agent_profile_reports_unconfigured_without_importable_swival(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    monkeypatch.setattr(
        self_management_built_in_agent_service,
        "_is_swival_importable",
        lambda: False,
    )

    profile = self_management_built_in_agent_service.get_profile()

    assert profile.configured is False


async def test_built_in_agent_loads_swival_from_tool_installed_site_packages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)

    tool_root = tmp_path / "tool-runtime"
    executable = tool_root / "bin" / "swival"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    executable.chmod(0o755)

    site_packages = tool_root / "lib" / "python3.13" / "site-packages"
    package_dir = site_packages / "swival"
    package_dir.mkdir(parents=True)
    package_dir.joinpath("__init__.py").write_text(
        "class Session:\n"
        "    def __init__(self, **kwargs):\n"
        "        self.kwargs = kwargs\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        settings,
        "self_management_swival_tool_executable",
        str(executable),
    )
    monkeypatch.delitem(sys.modules, "swival", raising=False)

    session_cls = self_management_built_in_agent_service._load_swival_session_cls()

    assert session_cls.__name__ == "Session"
    assert str(site_packages.resolve()) in sys.path


async def test_built_in_agent_run_uses_swival_with_authenticated_mcp_server(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    monkeypatch.setattr(
        settings,
        "self_management_swival_runtime_root",
        str(tmp_path / "swival-runtime"),
    )
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
        "self.sessions.get_latest_messages",
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
    assert _FakeSwivalSession.last_init_kwargs["api_key"] == "test-api-key"
    assert _FakeSwivalSession.last_init_kwargs["reasoning_effort"] == "medium"
    assert _FakeSwivalSession.last_init_kwargs["max_turns"] == 6
    assert _FakeSwivalSession.last_init_kwargs["max_output_tokens"] == 2048
    assert _FakeSwivalSession.last_init_kwargs["files"] == "none"
    assert _FakeSwivalSession.last_init_kwargs["commands"] == "none"
    assert _FakeSwivalSession.last_init_kwargs["no_skills"] is True
    assert _FakeSwivalSession.last_init_kwargs["history"] is False
    assert _FakeSwivalSession.last_init_kwargs["memory"] is False
    assert _FakeSwivalSession.last_init_kwargs["base_dir"] == str(
        (tmp_path / "swival-runtime" / str(user.id)).resolve()
    )
    assert "built-in a2a-client-hub self-management assistant" in cast(
        str,
        _FakeSwivalSession.last_init_kwargs["system_prompt"],
    )
    assert "This run is read-only." in cast(
        str,
        _FakeSwivalSession.last_init_kwargs["system_prompt"],
    )
    assert "treat them as handoff operations" in cast(
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


async def test_built_in_agent_rebuilds_session_when_delegated_token_expires(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    monkeypatch.setattr(settings, "jwt_access_token_ttl_seconds", 5)
    monkeypatch.setattr(
        settings, "self_management_swival_delegated_token_ttl_seconds", 5
    )
    monotonic_time = {"value": 100.0}
    monkeypatch.setattr(
        self_management_agent_service_module.time,
        "monotonic",
        lambda: monotonic_time["value"],
    )
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    first = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="List my jobs",
        allow_write_tools=False,
    )
    assert first.answer == "Built-in agent reply"
    assert _FakeSwivalSession.instance_count == 1

    monotonic_time["value"] += 10.0
    _FakeSwivalSession.next_answer = "Second built-in agent reply"
    second = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="List my agents",
        allow_write_tools=False,
    )

    assert second.answer == "Second built-in agent reply"
    assert _FakeSwivalSession.instance_count == 2
    assert _FakeSwivalSession.instances[0].closed is True
    assert _FakeSwivalSession.instances[1]._conv_state is not None
    transferred_messages = cast(
        list[dict[str, str]], _FakeSwivalSession.instances[1]._conv_state["messages"]
    )
    assert transferred_messages[0]["role"] == "system"
    assert cast(
        list[dict[str, str]], _FakeSwivalSession.instances[1]._conv_state["messages"]
    )[1:3] == [
        {"role": "user", "content": "List my jobs"},
        {"role": "assistant", "content": "Built-in agent reply"},
    ]


async def test_built_in_agent_raises_when_mcp_runtime_returns_transport_error(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)

    _FakeSwivalSession.next_answer = "Backend appears unavailable."
    _FakeSwivalSession.next_messages = [
        {"role": "user", "content": "List my agents"},
        {
            "role": "tool",
            "content": (
                "error: MCP server 'a2a-client-hub' failed: "
                "Client error '401 Unauthorized'"
            ),
        },
        {"role": "assistant", "content": "Backend appears unavailable."},
    ]

    with pytest.raises(SelfManagementBuiltInAgentUnavailableError) as excinfo:
        await self_management_built_in_agent_service.run(
            db=async_db_session,
            current_user=user,
            conversation_id=_new_conversation_id(),
            message="List my agents",
            allow_write_tools=False,
        )

    assert "MCP call failed" in str(excinfo.value)
    assert "401 Unauthorized" in str(excinfo.value)


async def test_built_in_agent_reuses_same_swival_base_dir_for_same_user(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    monkeypatch.setattr(
        settings,
        "self_management_swival_runtime_root",
        str(tmp_path / "swival-runtime"),
    )
    user = await create_user(async_db_session)

    first_dir = self_management_built_in_agent_service._resolve_swival_base_dir(user)
    second_dir = self_management_built_in_agent_service._resolve_swival_base_dir(user)

    assert first_dir == second_dir
    assert first_dir == str((tmp_path / "swival-runtime" / str(user.id)).resolve())


async def test_built_in_agent_uses_distinct_swival_base_dirs_per_user(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    monkeypatch.setattr(
        settings,
        "self_management_swival_runtime_root",
        str(tmp_path / "swival-runtime"),
    )
    first_user = await create_user(async_db_session)
    second_user = await create_user(async_db_session)

    first_dir = self_management_built_in_agent_service._resolve_swival_base_dir(
        first_user
    )
    second_dir = self_management_built_in_agent_service._resolve_swival_base_dir(
        second_user
    )

    assert first_dir != second_dir
    assert first_dir.endswith(str(first_user.id))
    assert second_dir.endswith(str(second_user.id))


async def test_built_in_agent_write_approved_run_uses_write_enabled_mcp_surface(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    monkeypatch.setattr(
        settings,
        "self_management_swival_runtime_root",
        str(tmp_path / "swival-runtime"),
    )
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
        "self.agents.check_health",
        "self.agents.check_health_all",
        "self.agents.create",
        "self.agents.delete",
        "self.agents.get",
        "self.agents.list",
        "self.agents.start_sessions",
        "self.agents.update_config",
        "self.jobs.create",
        "self.jobs.delete",
        "self.jobs.get",
        "self.jobs.list",
        "self.jobs.pause",
        "self.jobs.resume",
        "self.jobs.update",
        "self.jobs.update_prompt",
        "self.jobs.update_schedule",
        "self.sessions.archive",
        "self.sessions.get",
        "self.sessions.get_latest_messages",
        "self.sessions.list",
        "self.sessions.send_message",
        "self.sessions.unarchive",
        "self.sessions.update",
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
        "self.agents.check_health",
        "self.agents.check_health_all",
        "self.agents.create",
        "self.agents.delete",
        "self.agents.get",
        "self.agents.list",
        "self.agents.start_sessions",
        "self.agents.update_config",
        "self.jobs.create",
        "self.jobs.delete",
        "self.jobs.get",
        "self.jobs.list",
        "self.jobs.pause",
        "self.jobs.resume",
        "self.jobs.update",
        "self.jobs.update_prompt",
        "self.jobs.update_schedule",
        "self.sessions.archive",
        "self.sessions.get",
        "self.sessions.get_latest_messages",
        "self.sessions.list",
        "self.sessions.send_message",
        "self.sessions.unarchive",
        "self.sessions.update",
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
            "self.sessions.get_latest_messages",
            "self.sessions.list",
        ],
        "write_tools_enabled": False,
        "interrupt": None,
        "continuation": None,
    }


async def test_built_in_agent_run_route_logs_traceback_for_unavailable_error(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    user = await create_user(async_db_session)
    logged: list[dict[str, Any]] = []

    async def _raise_unavailable(**_kwargs: Any) -> Any:
        raise self_management_agent_router.SelfManagementBuiltInAgentUnavailableError(
            "swival failed"
        )

    def _capture(message: str, *args: Any, **kwargs: Any) -> None:
        logged.append({"message": message, **kwargs})

    monkeypatch.setattr(
        self_management_agent_router.self_management_built_in_agent_service,
        "run",
        _raise_unavailable,
    )
    monkeypatch.setattr(self_management_agent_router.logger, "exception", _capture)

    async with create_test_client(
        self_management_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/self-management/agent:run",
            json={"conversationId": _new_conversation_id(), "message": "List my jobs"},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "swival failed"
    assert len(logged) == 1
    assert logged[0]["message"] == "Built-in self-management agent run failed"
    assert logged[0]["extra"]["user_id"] == str(user.id)
    assert isinstance(logged[0]["extra"]["conversation_id"], str)


async def test_built_in_agent_run_route_invalid_conversation_id_returns_400(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)

    async with create_test_client(
        self_management_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/self-management/agent:run",
            json={"conversationId": "test-1", "message": "List my jobs"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_conversation_id"


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


async def test_built_in_agent_run_persists_supplied_message_ids(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    user_message_id = uuid4()
    agent_message_id = uuid4()

    result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="List my jobs",
        user_message_id=user_message_id,
        agent_message_id=agent_message_id,
        allow_write_tools=False,
    )

    assert result.status == "completed"

    messages, _extra, _db_mutated = await session_hub_service.list_messages(
        async_db_session,
        user_id=cast(Any, user.id),
        conversation_id=conversation_id,
        before=None,
        limit=20,
    )
    assert messages[0]["id"] == str(user_message_id)
    assert messages[1]["id"] == str(agent_message_id)


async def test_built_in_agent_interrupt_and_resolution_are_persisted(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "self.jobs.pause",
    )

    interrupt_result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    assert interrupt_result.interrupt is not None

    reject_outcome = (
        await self_management_built_in_agent_service.reply_permission_interrupt(
            db=async_db_session,
            current_user=user,
            request_id=interrupt_result.interrupt.request_id,
            reply="reject",
        )
    )
    assert (
        reject_outcome.result.answer
        == "Write approval was rejected. No changes were made."
    )

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


async def test_built_in_agent_permission_reply_persists_supplied_agent_message_id(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "self.jobs.pause",
    )

    interrupt_result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    assert interrupt_result.interrupt is not None

    _FakeSwivalSession.next_answer = "Paused the requested job."
    follow_up_agent_message_id = uuid4()
    outcome = await self_management_built_in_agent_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt_result.interrupt.request_id,
        reply="once",
        agent_message_id=follow_up_agent_message_id,
    )
    assert outcome.result.status == "accepted"
    assert outcome.continuation_request is not None
    await async_db_session.commit()
    self_management_built_in_agent_service.schedule_permission_reply_continuation(
        outcome.continuation_request
    )
    await self_management_built_in_agent_service.drain_pending_tasks()

    messages, _extra, _db_mutated = await session_hub_service.list_messages(
        async_db_session,
        user_id=cast(Any, user.id),
        conversation_id=conversation_id,
        before=None,
        limit=20,
    )
    assert [item["role"] for item in messages] == ["user", "agent", "agent"]
    matching_reply = next(
        item for item in messages if item["content"] == "Paused the requested job."
    )
    assert matching_reply["id"] == str(follow_up_agent_message_id)


async def test_built_in_agent_permission_reply_background_failure_persists_error(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "self.jobs.pause",
    )

    interrupt_result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    assert interrupt_result.interrupt is not None

    _FakeSwivalSession.next_error = RuntimeError("write tool failed")
    follow_up_agent_message_id = uuid4()
    outcome = await self_management_built_in_agent_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt_result.interrupt.request_id,
        reply="once",
        agent_message_id=follow_up_agent_message_id,
    )
    assert outcome.continuation_request is not None
    await async_db_session.commit()

    self_management_built_in_agent_service.schedule_permission_reply_continuation(
        outcome.continuation_request
    )
    await self_management_built_in_agent_service.drain_pending_tasks()

    messages, _extra, _db_mutated = await session_hub_service.list_messages(
        async_db_session,
        user_id=cast(Any, user.id),
        conversation_id=conversation_id,
        before=None,
        limit=20,
    )
    matching_reply = next(
        item for item in messages if item["id"] == str(follow_up_agent_message_id)
    )
    assert matching_reply["role"] == "agent"
    assert matching_reply["status"] == "error"
    assert "write tool failed" in matching_reply["content"]


async def test_built_in_agent_permission_reply_background_interrupt_persists_new_interrupt(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "self.jobs.pause",
    )

    interrupt_result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    assert interrupt_result.interrupt is not None

    _FakeSwivalSession.next_answer = _approval_answer(
        "Deleting that agent requires additional approval.",
        "self.agents.delete",
    )
    outcome = await self_management_built_in_agent_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt_result.interrupt.request_id,
        reply="once",
    )
    assert outcome.continuation_request is not None
    await async_db_session.commit()

    self_management_built_in_agent_service.schedule_permission_reply_continuation(
        outcome.continuation_request
    )
    await self_management_built_in_agent_service.drain_pending_tasks()

    messages, _extra, _db_mutated = await session_hub_service.list_messages(
        async_db_session,
        user_id=cast(Any, user.id),
        conversation_id=conversation_id,
        before=None,
        limit=20,
    )
    interrupted_reply = next(
        item
        for item in messages
        if item["id"] == str(outcome.result.continuation.agent_message_id)
    )
    assert interrupted_reply["role"] == "agent"
    assert interrupted_reply["status"] == "interrupted"

    recovered = await self_management_built_in_agent_service.recover_pending_interrupts(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
    )
    assert len(recovered) == 1
    assert recovered[0].details["patterns"] == ["self.agents.delete"]


async def test_built_in_agent_can_recover_unresolved_permission_interrupts(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "self.jobs.pause",
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
    assert recovered[0].details["patterns"] == ["self.jobs.pause"]


async def test_built_in_agent_recovery_ignores_resolved_interrupts(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "self.jobs.pause",
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
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "self.jobs.pause",
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
    assert result.interrupt.patterns == ("self.jobs.pause",)
    claims = verify_jwt_token_claims(
        result.interrupt.request_id,
        expected_type="self_management_interrupt",
    )
    assert claims is not None
    assert claims.subject == str(user.id)
    assert get_self_management_interrupt_message(claims) == "Pause my job"
    assert get_self_management_interrupt_tool_names(claims) == ("self.jobs.pause",)
    assert get_self_management_allowed_operations(claims) == frozenset(
        {"self.jobs.pause"}
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
        allowed_write_operation_ids=("self.jobs.pause",),
    )

    outcome = await self_management_built_in_agent_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt.request_id,
        reply="once",
    )
    assert outcome.result.status == "accepted"
    assert outcome.result.write_tools_enabled is True
    assert "self.jobs.pause" in outcome.result.tool_names
    assert "self.sessions.update" not in outcome.result.tool_names
    assert outcome.continuation_request is not None
    assert _FakeSwivalSession.ask_call_count == 0
    await async_db_session.commit()
    self_management_built_in_agent_service.schedule_permission_reply_continuation(
        outcome.continuation_request
    )
    await self_management_built_in_agent_service.drain_pending_tasks()
    assert _FakeSwivalSession.ask_call_count == 1
    assert _FakeSwivalSession.last_message == "Pause my job"
    assert _FakeSwivalSession.last_init_kwargs is not None
    assert _FakeSwivalSession.last_init_kwargs["mcp_servers"]["a2a-client-hub"][
        "url"
    ] == ("http://internal-mcp/mcp-write/")
    assert _FakeSwivalSession.instance_count == 1


async def test_built_in_agent_session_refresh_preserves_new_system_prompt(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "self.jobs.pause",
    )

    interrupt_result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    assert interrupt_result.interrupt is not None

    _FakeSwivalSession.next_answer = "Paused the requested job."

    outcome = await self_management_built_in_agent_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt_result.interrupt.request_id,
        reply="once",
    )
    assert outcome.result.status == "accepted"
    assert outcome.continuation_request is not None
    await async_db_session.commit()
    self_management_built_in_agent_service.schedule_permission_reply_continuation(
        outcome.continuation_request
    )
    await self_management_built_in_agent_service.drain_pending_tasks()
    assert _FakeSwivalSession.instance_count == 2
    assert _FakeSwivalSession.instances[1]._conv_state is not None
    next_messages = cast(
        list[dict[str, str]], _FakeSwivalSession.instances[1]._conv_state["messages"]
    )
    assert next_messages[0]["role"] == "system"
    assert (
        "This run includes explicitly approved write tools."
        in next_messages[0]["content"]
    )
    assert "The currently approved write operations are: self.jobs.pause." in (
        next_messages[0]["content"]
    )
    assert next_messages[1:3] == [
        {"role": "user", "content": "Pause my job"},
        {
            "role": "assistant",
            "content": "I can pause the requested job after you approve write access.\n"
            "[[SELF_MANAGEMENT_WRITE_APPROVAL_REQUIRED]]\n"
            "[[SELF_MANAGEMENT_WRITE_OPERATIONS:self.jobs.pause]]",
        },
    ]


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
        allowed_write_operation_ids=("self.jobs.pause",),
    )

    outcome = await self_management_built_in_agent_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt.request_id,
        reply="reject",
    )
    assert outcome.result.status == "completed"
    assert outcome.result.answer == "Write approval was rejected. No changes were made."
    assert outcome.result.write_tools_enabled is False
    assert outcome.result.exhausted is False
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
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "self.jobs.pause",
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
    assert approve_response.json()["status"] == "accepted"
    assert approve_response.json()["write_tools_enabled"] is True
    assert approve_response.json()["interrupt"] is None
    assert approve_response.json()["continuation"]["phase"] == "running"
    await self_management_built_in_agent_service.drain_pending_tasks()


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
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "self.jobs.pause",
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
                "patterns": ["self.jobs.pause"],
                "displayMessage": "I can pause the requested job after you approve write access.",
            },
        }
    ]


async def test_built_in_agent_interrupt_recovery_route_persists_expired_interrupts(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    persisted_user_id = cast(Any, user.id)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "self.jobs.pause",
    )

    interrupt_result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    assert interrupt_result.interrupt is not None
    await async_db_session.commit()

    original_verify = self_management_agent_service_module.verify_jwt_token_claims
    invalid_request_id = interrupt_result.interrupt.request_id
    monkeypatch.setattr(
        self_management_agent_service_module,
        "verify_jwt_token_claims",
        lambda token, *, expected_type: (
            None
            if token == invalid_request_id
            else original_verify(token, expected_type=expected_type)
        ),
    )

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
    assert response.json()["items"] == []

    await async_db_session.rollback()
    system_messages = list(
        (
            await async_db_session.scalars(
                select(AgentMessage)
                .where(
                    AgentMessage.user_id == persisted_user_id,
                    AgentMessage.conversation_id == UUID(conversation_id),
                    AgentMessage.sender == "system",
                )
                .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
            )
        ).all()
    )
    assert len(system_messages) == 2
    resolved_interrupt = cast(dict[str, Any], system_messages[1].message_metadata)[
        "interrupt"
    ]
    assert resolved_interrupt["phase"] == "resolved"
    assert resolved_interrupt["resolution"] == "expired"


async def test_built_in_agent_recovery_skips_invalid_interrupt_requests(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "self.jobs.pause",
    )

    interrupt_result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    assert interrupt_result.interrupt is not None

    original_verify = self_management_agent_service_module.verify_jwt_token_claims
    invalid_request_id = interrupt_result.interrupt.request_id
    monkeypatch.setattr(
        self_management_agent_service_module,
        "verify_jwt_token_claims",
        lambda token, *, expected_type: (
            None
            if token == invalid_request_id
            else original_verify(token, expected_type=expected_type)
        ),
    )

    recovered = await self_management_built_in_agent_service.recover_pending_interrupts(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
    )

    assert recovered == []

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
    resolved_interrupt = cast(dict[str, Any], system_messages[1].message_metadata)[
        "interrupt"
    ]
    assert resolved_interrupt["phase"] == "resolved"
    assert resolved_interrupt["resolution"] == "expired"


async def test_built_in_agent_recovery_skips_interrupts_for_other_conversations(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "self.jobs.pause",
    )

    interrupt_result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    assert interrupt_result.interrupt is not None

    monkeypatch.setattr(
        self_management_agent_service_module,
        "get_self_management_interrupt_conversation_id",
        lambda _claims: str(uuid4()),
    )

    recovered = await self_management_built_in_agent_service.recover_pending_interrupts(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
    )

    assert recovered == []


async def test_built_in_agent_permission_reply_route_returns_terminal_error_code_for_expired_request(
    async_session_maker,
    async_db_session,
) -> None:
    _reset_built_in_agent_runtime()
    user = await create_user(async_db_session)

    async with create_test_client(
        self_management_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/self-management/agent/interrupts/permission:reply",
            json={"requestId": "expired-request", "reply": "always"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "message": "The write approval request is invalid or expired.",
        "error_code": "interrupt_request_expired",
    }


async def test_built_in_agent_permission_reply_route_logs_traceback_for_unavailable_error(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_built_in_agent_runtime()
    user = await create_user(async_db_session)
    logged: list[dict[str, Any]] = []

    async def _raise_unavailable(**_kwargs: Any) -> Any:
        raise self_management_agent_router.SelfManagementBuiltInAgentUnavailableError(
            "invalid approval request"
        )

    def _capture(message: str, *args: Any, **kwargs: Any) -> None:
        logged.append({"message": message, **kwargs})

    monkeypatch.setattr(
        self_management_agent_router.self_management_built_in_agent_service,
        "reply_permission_interrupt",
        _raise_unavailable,
    )
    monkeypatch.setattr(self_management_agent_router.logger, "exception", _capture)

    async with create_test_client(
        self_management_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/self-management/agent/interrupts/permission:reply",
            json={"requestId": "req-1", "reply": "once"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid approval request"
    assert logged == [
        {
            "message": "Built-in self-management agent permission reply failed",
            "extra": {
                "user_id": str(user.id),
                "request_id": "req-1",
                "reply": "once",
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
        allowed_write_operation_ids=("self.jobs.pause",),
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
    assert len(_FakeSwivalSession.instances[0]._conv_state["messages"]) == 5


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
    assert len(_FakeSwivalSession.instances[1]._conv_state["messages"]) == 5
    assert _FakeSwivalSession.instances[1]._conv_state["messages"][0] == {
        "role": "system",
        "content": cast(str, _FakeSwivalSession.instances[1]._system_prompt),
    }
    assert _FakeSwivalSession.instances[1]._conv_state["messages"][1] == {
        "role": "user",
        "content": "List my jobs",
    }
    assert _FakeSwivalSession.instances[1]._conv_state["messages"][2] == {
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
        allowed_write_operation_ids=("self.jobs.pause",),
    )

    always_outcome = (
        await self_management_built_in_agent_service.reply_permission_interrupt(
            db=async_db_session,
            current_user=user,
            request_id=interrupt.request_id,
            reply="always",
        )
    )
    assert always_outcome.result.status == "accepted"
    assert always_outcome.continuation_request is not None
    await async_db_session.commit()
    self_management_built_in_agent_service.schedule_permission_reply_continuation(
        always_outcome.continuation_request
    )
    await self_management_built_in_agent_service.drain_pending_tasks()
    follow_up_result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause it now",
        allow_write_tools=False,
    )

    assert always_outcome.result.write_tools_enabled is True
    assert follow_up_result.write_tools_enabled is True
    assert "self.jobs.pause" in follow_up_result.tool_names
    assert "self.sessions.update" not in follow_up_result.tool_names
    assert _FakeSwivalSession.instance_count == 1
    assert _FakeSwivalSession.ask_call_count == 2
    assert _FakeSwivalSession.last_init_kwargs is not None
    assert _FakeSwivalSession.last_init_kwargs["mcp_servers"]["a2a-client-hub"][
        "url"
    ] == ("http://internal-mcp/mcp-write/")


async def test_built_in_agent_requests_additional_approval_for_new_write_operations(
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
        allowed_write_operation_ids=("self.jobs.pause",),
    )

    always_outcome = (
        await self_management_built_in_agent_service.reply_permission_interrupt(
            db=async_db_session,
            current_user=user,
            request_id=interrupt.request_id,
            reply="always",
        )
    )
    assert always_outcome.continuation_request is not None
    await async_db_session.commit()
    self_management_built_in_agent_service.schedule_permission_reply_continuation(
        always_outcome.continuation_request
    )
    await self_management_built_in_agent_service.drain_pending_tasks()

    _FakeSwivalSession.next_answer = _approval_answer(
        "Deleting that agent requires additional approval.",
        "self.agents.delete",
    )
    follow_up_result = await self_management_built_in_agent_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Delete my agent",
        allow_write_tools=False,
    )

    assert follow_up_result.status == "interrupted"
    assert follow_up_result.write_tools_enabled is True
    assert follow_up_result.interrupt is not None
    assert follow_up_result.interrupt.patterns == ("self.agents.delete",)

    _FakeSwivalSession.next_answer = "Deleted the requested agent."
    resumed_outcome = (
        await self_management_built_in_agent_service.reply_permission_interrupt(
            db=async_db_session,
            current_user=user,
            request_id=follow_up_result.interrupt.request_id,
            reply="once",
        )
    )
    assert resumed_outcome.result.status == "accepted"
    assert resumed_outcome.continuation_request is not None
    await async_db_session.commit()
    self_management_built_in_agent_service.schedule_permission_reply_continuation(
        resumed_outcome.continuation_request
    )
    await self_management_built_in_agent_service.drain_pending_tasks()
    assert resumed_outcome.result.write_tools_enabled is True
    assert resumed_outcome.result.tool_names == ("self.agents.delete",)
    assert "self.sessions.update" not in resumed_outcome.result.tool_names


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
