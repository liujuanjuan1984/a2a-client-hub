from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

from app.core.config import settings
from app.core.security import verify_access_token
from app.features.self_management_agent import router as self_management_agent_router
from app.features.self_management_agent.service import (
    self_management_built_in_agent_service,
)
from tests.support.api_utils import create_test_client
from tests.support.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _FakeSwivalSession:
    last_init_kwargs: dict[str, object] | None = None
    last_message: str | None = None

    def __init__(self, **kwargs: object) -> None:
        type(self).last_init_kwargs = dict(kwargs)

    def run(self, message: str) -> object:
        type(self).last_message = message
        return SimpleNamespace(answer="Built-in agent reply", exhausted=False)


def _install_fake_swival(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeSwivalSession.last_init_kwargs = None
    _FakeSwivalSession.last_message = None
    module = ModuleType("swival")
    module.Session = _FakeSwivalSession
    monkeypatch.setitem(sys.modules, "swival", module)


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
        "self_management_swival_reasoning_effort",
        "medium",
    )
    monkeypatch.setattr(settings, "self_management_swival_max_turns", 6)
    monkeypatch.setattr(settings, "self_management_swival_max_output_tokens", 2048)


async def test_built_in_agent_profile_only_exposes_jobs_mcp_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)

    result = await self_management_built_in_agent_service.run(
        current_user=user,
        message="List my jobs",
        request_base_url="http://testserver/",
    )

    assert result.answer == "Built-in agent reply"
    assert result.exhausted is False
    assert result.runtime == "swival"
    assert result.resources == ("agents", "jobs", "sessions")
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
    assert _FakeSwivalSession.last_message == "List my jobs"
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
    mcp_servers = cast(
        dict[str, dict[str, Any]],
        _FakeSwivalSession.last_init_kwargs["mcp_servers"],
    )
    server_config = mcp_servers["a2a-client-hub"]
    assert server_config["url"] == "http://testserver/mcp/"
    auth_header = cast(str, server_config["headers"]["Authorization"])
    assert auth_header.startswith("Bearer ")
    raw_token = auth_header.split("Bearer ", 1)[1]
    assert str(verify_access_token(raw_token)) == str(user.id)


async def test_built_in_agent_profile_route_requires_auth(async_session_maker) -> None:
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
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)

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
            json={"message": "Pause my job"},
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
        "answer": "Built-in agent reply",
        "exhausted": False,
        "runtime": "swival",
        "resources": ["agents", "jobs", "sessions"],
        "tools": [
            "self.agents.get",
            "self.agents.list",
            "self.agents.update_config",
            "self.jobs.get",
            "self.jobs.list",
            "self.jobs.pause",
            "self.sessions.get",
            "self.sessions.list",
        ],
    }
