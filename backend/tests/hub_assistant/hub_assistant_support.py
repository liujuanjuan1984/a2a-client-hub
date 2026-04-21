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
    get_hub_assistant_conversation_id,
    get_hub_assistant_interrupt_message,
    get_hub_assistant_interrupt_tool_names,
    get_hub_assistant_operation_ids,
    verify_jwt_token_claims,
)
from app.db.models.agent_message import AgentMessage
from app.db.models.conversation_thread import ConversationThread
from app.features.hub_assistant import router as hub_assistant_agent_router
from app.features.hub_assistant import service as hub_assistant_agent_service_module
from app.features.hub_assistant.service import (
    _WRITE_APPROVAL_SENTINEL,
    HubAssistantUnavailableError,
    hub_assistant_service,
)
from app.features.hub_assistant.shared.task_job import (
    dispatch_due_hub_assistant_tasks,
)
from app.features.hub_assistant.shared.task_service import (
    HubAssistantFollowUpTaskRequest,
)
from app.features.sessions.service import session_hub_service
from tests.support.api_utils import create_test_client
from tests.support.utils import create_user

# ruff: noqa: F401


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _FakeSwivalSession:
    last_init_kwargs: dict[str, object] | None = None
    last_message: str | None = None
    next_answer: str = "Hub Assistant reply"
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
    _FakeSwivalSession.next_answer = "Hub Assistant reply"
    _FakeSwivalSession.next_messages = None
    _FakeSwivalSession.next_error = None
    _FakeSwivalSession.ask_call_count = 0
    _FakeSwivalSession.instance_count = 0
    _FakeSwivalSession.instances = []
    module = ModuleType("swival")
    module.Session = _FakeSwivalSession
    monkeypatch.setitem(sys.modules, "swival", module)


def _reset_hub_assistant_runtime() -> None:
    hub_assistant_service._conversation_registry.clear()


def _configure_swival_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "hub_assistant_swival_provider",
        "openai",
    )
    monkeypatch.setattr(
        settings,
        "hub_assistant_swival_model",
        "gpt-test",
    )
    monkeypatch.setattr(
        settings,
        "hub_assistant_swival_import_paths",
        [],
    )
    monkeypatch.setattr(
        settings,
        "hub_assistant_swival_tool_executable",
        None,
    )
    monkeypatch.setattr(
        settings,
        "hub_assistant_swival_runtime_root",
        None,
    )
    monkeypatch.setattr(
        settings,
        "hub_assistant_swival_base_url",
        "https://example.com/v1",
    )
    monkeypatch.setattr(
        settings,
        "hub_assistant_swival_api_key",
        "test-api-key",
    )
    monkeypatch.setattr(
        settings,
        "hub_assistant_swival_mcp_base_url",
        "http://internal-mcp",
    )
    monkeypatch.setattr(
        settings,
        "hub_assistant_swival_reasoning_effort",
        "medium",
    )
    monkeypatch.setattr(settings, "hub_assistant_swival_max_turns", 6)
    monkeypatch.setattr(settings, "hub_assistant_swival_max_output_tokens", 2048)


def _new_conversation_id() -> str:
    return str(uuid4())


def _approval_answer(message: str, *operation_ids: str) -> str:
    return (
        f"{message}\n"
        f"{_WRITE_APPROVAL_SENTINEL}\n"
        "[[HUB_ASSISTANT_WRITE_OPERATIONS:"
        f"{','.join(operation_ids)}"
        "]]"
    )


__all__ = [
    "AgentMessage",
    "Any",
    "ConversationThread",
    "HubAssistantFollowUpTaskRequest",
    "HubAssistantUnavailableError",
    "ModuleType",
    "Path",
    "SimpleNamespace",
    "UUID",
    "_FakeSwivalSession",
    "_approval_answer",
    "_configure_swival_settings",
    "_install_fake_swival",
    "_new_conversation_id",
    "_reset_hub_assistant_runtime",
    "cast",
    "create_test_client",
    "create_user",
    "dispatch_due_hub_assistant_tasks",
    "get_hub_assistant_conversation_id",
    "get_hub_assistant_interrupt_message",
    "get_hub_assistant_interrupt_tool_names",
    "get_hub_assistant_operation_ids",
    "hub_assistant_agent_router",
    "hub_assistant_agent_service_module",
    "hub_assistant_service",
    "pytest",
    "select",
    "session_hub_service",
    "settings",
    "sys",
    "uuid4",
    "verify_jwt_token_claims",
]
