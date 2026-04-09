"""Swival-backed built-in agent runtime for self-management entry points."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from app.core.config import settings
from app.core.security import create_user_access_token
from app.db.models.user import User
from app.features.agents_shared.self_management_mcp import (
    SELF_MANAGEMENT_MCP_MOUNT_PATH,
    list_self_management_mcp_tool_definitions,
)
from app.features.agents_shared.self_management_tool_contract import (
    SelfManagementToolDefinition,
)

_DEFAULT_AGENT_ID = "self-management-assistant"
_DEFAULT_AGENT_NAME = "A2A Client Hub Assistant"
_DEFAULT_AGENT_DESCRIPTION = (
    "A built-in assistant powered by swival that can manage the authenticated "
    "user's own a2a-client-hub resources through constrained self-management tools."
)
_DEFAULT_SYSTEM_PROMPT = (
    "You are the built-in a2a-client-hub self-management assistant. "
    "Help the authenticated user inspect or manage their own resources using the "
    "provided MCP tools. Never invent resource ids. For write operations, explain "
    "the intended change briefly before using the tool. If the request is missing "
    "required identifiers, ask one concise follow-up question."
)


class SelfManagementBuiltInAgentError(RuntimeError):
    """Base error for the built-in self-management agent runtime."""


class SelfManagementBuiltInAgentConfigError(SelfManagementBuiltInAgentError):
    """Raised when the swival-backed built-in agent runtime is not configured."""


class SelfManagementBuiltInAgentUnavailableError(SelfManagementBuiltInAgentError):
    """Raised when the swival runtime cannot be imported or executed."""


@dataclass(frozen=True)
class SelfManagementBuiltInAgentProfile:
    """Static metadata for the swival-backed built-in agent."""

    agent_id: str
    name: str
    description: str
    runtime: str
    configured: bool
    resources: tuple[str, ...]
    tool_definitions: tuple[SelfManagementToolDefinition, ...]


@dataclass(frozen=True)
class SelfManagementBuiltInAgentRunResult:
    """One completed swival-backed self-management agent run."""

    answer: str | None
    exhausted: bool
    runtime: str
    resources: tuple[str, ...]
    tool_names: tuple[str, ...]


class SelfManagementBuiltInAgentService:
    """High-level facade for the swival-driven built-in self-management agent."""

    def get_profile(self) -> SelfManagementBuiltInAgentProfile:
        tool_definitions = list_self_management_mcp_tool_definitions()
        resources = tuple(
            sorted(
                {
                    definition.operation_id.split(".")[1]
                    for definition in tool_definitions
                }
            )
        )
        return SelfManagementBuiltInAgentProfile(
            agent_id=_DEFAULT_AGENT_ID,
            name=_DEFAULT_AGENT_NAME,
            description=_DEFAULT_AGENT_DESCRIPTION,
            runtime="swival",
            configured=self.is_configured(),
            resources=resources,
            tool_definitions=tool_definitions,
        )

    def is_configured(self) -> bool:
        return bool(
            (settings.self_management_swival_provider or "").strip()
            and (settings.self_management_swival_model or "").strip()
        )

    async def run(
        self,
        *,
        current_user: User,
        message: str,
        request_base_url: str,
    ) -> SelfManagementBuiltInAgentRunResult:
        if not self.is_configured():
            raise SelfManagementBuiltInAgentConfigError(
                "The self-management built-in agent is not configured. "
                "Set SELF_MANAGEMENT_SWIVAL_PROVIDER and SELF_MANAGEMENT_SWIVAL_MODEL."
            )

        profile = self.get_profile()
        token = create_user_access_token(cast(Any, current_user.id))
        mcp_url = self._build_mcp_url(request_base_url)
        result = await asyncio.to_thread(
            self._run_swival_session,
            message=message,
            mcp_url=mcp_url,
            access_token=token,
        )
        return SelfManagementBuiltInAgentRunResult(
            answer=cast(str | None, getattr(result, "answer", None)),
            exhausted=bool(getattr(result, "exhausted", False)),
            runtime="swival",
            resources=profile.resources,
            tool_names=tuple(
                definition.tool_name for definition in profile.tool_definitions
            ),
        )

    def _build_mcp_url(self, request_base_url: str) -> str:
        base = request_base_url.rstrip("/")
        return f"{base}{SELF_MANAGEMENT_MCP_MOUNT_PATH}/"

    def _run_swival_session(
        self,
        *,
        message: str,
        mcp_url: str,
        access_token: str,
    ) -> Any:
        session_cls = self._load_swival_session_cls()
        session = session_cls(
            base_dir=str(Path(__file__).resolve().parents[3]),
            provider=cast(str, settings.self_management_swival_provider),
            model=cast(str, settings.self_management_swival_model),
            api_key=settings.self_management_swival_api_key,
            base_url=settings.self_management_swival_base_url,
            max_turns=settings.self_management_swival_max_turns,
            max_output_tokens=settings.self_management_swival_max_output_tokens,
            reasoning_effort=settings.self_management_swival_reasoning_effort,
            system_prompt=_DEFAULT_SYSTEM_PROMPT,
            no_skills=True,
            history=False,
            memory=False,
            continue_here=False,
            allowed_commands=[],
            yolo=False,
            mcp_servers={
                "a2a-client-hub": {
                    "url": mcp_url,
                    "headers": {"Authorization": f"Bearer {access_token}"},
                }
            },
        )
        try:
            return session.run(message)
        except Exception as exc:  # pragma: no cover - exercised with integration
            raise SelfManagementBuiltInAgentUnavailableError(
                f"swival built-in agent run failed: {exc}"
            ) from exc

    def _load_swival_session_cls(self) -> type[Any]:
        for raw_path in settings.self_management_swival_import_paths:
            candidate = raw_path.strip()
            if not candidate:
                continue
            resolved = str(Path(candidate).expanduser().resolve())
            if resolved not in sys.path:
                sys.path.insert(0, resolved)

        try:
            module = __import__("swival", fromlist=["Session"])
        except ImportError as exc:
            raise SelfManagementBuiltInAgentUnavailableError(
                "swival is not installed or not importable for the built-in agent runtime."
            ) from exc

        session_cls = getattr(module, "Session", None)
        if session_cls is None:
            raise SelfManagementBuiltInAgentUnavailableError(
                "swival.Session is required for the built-in agent runtime."
            )
        return cast(type[Any], session_cls)


self_management_built_in_agent_service = SelfManagementBuiltInAgentService()


__all__ = [
    "SelfManagementBuiltInAgentConfigError",
    "SelfManagementBuiltInAgentError",
    "SelfManagementBuiltInAgentProfile",
    "SelfManagementBuiltInAgentRunResult",
    "SelfManagementBuiltInAgentService",
    "SelfManagementBuiltInAgentUnavailableError",
    "self_management_built_in_agent_service",
]
