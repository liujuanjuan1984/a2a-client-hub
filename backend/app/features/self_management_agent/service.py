"""Swival-backed built-in agent runtime for self-management entry points."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, cast

from app.core.config import settings
from app.core.security import (
    create_self_management_access_token,
    create_self_management_interrupt_token,
    get_self_management_interrupt_message,
    get_self_management_interrupt_tool_names,
    verify_self_management_interrupt_token_claims,
)
from app.db.models.user import User
from app.features.self_management_shared.self_management_mcp import (
    SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH,
    SELF_MANAGEMENT_MCP_WRITE_MOUNT_PATH,
    list_self_management_mcp_tool_definitions,
)
from app.features.self_management_shared.self_management_tool_contract import (
    SelfManagementToolDefinition,
)
from app.features.self_management_shared.tool_gateway import (
    SelfManagementConfirmationPolicy,
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
_WRITE_APPROVAL_SENTINEL = "[[SELF_MANAGEMENT_WRITE_APPROVAL_REQUIRED]]"
_READ_ONLY_APPENDIX = (
    " This run is read-only. Do not attempt write operations. If the user's latest "
    "request would require a write tool, explain the intended change briefly, do not "
    "claim that any change was applied, and append a final line containing exactly "
    f"{_WRITE_APPROVAL_SENTINEL}."
)
_WRITE_ENABLED_APPENDIX = (
    " This run includes explicitly approved write tools. Only perform a write when "
    "the user's latest request clearly asks for that change."
)


class SelfManagementBuiltInAgentError(RuntimeError):
    """Base error for the built-in self-management agent runtime."""


class SelfManagementBuiltInAgentConfigError(SelfManagementBuiltInAgentError):
    """Raised when the swival-backed built-in agent runtime is not configured."""


class SelfManagementBuiltInAgentUnavailableError(SelfManagementBuiltInAgentError):
    """Raised when the swival runtime cannot be imported or executed."""


class SelfManagementBuiltInAgentRunStatus(str, Enum):
    """High-level outcome for one built-in self-management agent run."""

    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class SelfManagementBuiltInAgentInterrupt:
    """Permission interrupt emitted by a read-only built-in agent run."""

    request_id: str
    permission: str
    patterns: tuple[str, ...]
    display_message: str


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
    """One completed or interrupted swival-backed self-management agent run."""

    status: SelfManagementBuiltInAgentRunStatus
    answer: str | None
    exhausted: bool
    runtime: str
    resources: tuple[str, ...]
    tool_names: tuple[str, ...]
    write_tools_enabled: bool
    interrupt: SelfManagementBuiltInAgentInterrupt | None = None


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
            and (settings.self_management_swival_mcp_base_url or "").strip()
        )

    async def run(
        self,
        *,
        current_user: User,
        message: str,
        allow_write_tools: bool,
    ) -> SelfManagementBuiltInAgentRunResult:
        if not self.is_configured():
            raise SelfManagementBuiltInAgentConfigError(
                "The self-management built-in agent is not configured. "
                "Set SELF_MANAGEMENT_SWIVAL_PROVIDER and SELF_MANAGEMENT_SWIVAL_MODEL."
            )

        profile = self.get_profile()
        tool_definitions = self._select_run_tool_definitions(
            allow_write_tools=allow_write_tools
        )
        token = create_self_management_access_token(
            cast(Any, current_user.id),
            allowed_operations=[
                definition.operation_id for definition in tool_definitions
            ],
            delegated_by="self_management_built_in_agent",
        )
        mcp_url = self._build_mcp_url(allow_write_tools=allow_write_tools)
        result = await asyncio.to_thread(
            self._run_swival_session,
            message=message,
            mcp_url=mcp_url,
            access_token=token,
            system_prompt=self._build_system_prompt(
                allow_write_tools=allow_write_tools
            ),
        )
        answer = cast(str | None, getattr(result, "answer", None))
        exhausted = bool(getattr(result, "exhausted", False))
        if not allow_write_tools and self._answer_requests_write_approval(answer):
            interrupt = self._build_permission_interrupt(
                current_user=current_user,
                message=message,
                answer=answer,
            )
            return SelfManagementBuiltInAgentRunResult(
                status=SelfManagementBuiltInAgentRunStatus.INTERRUPTED,
                answer=self._strip_write_approval_sentinel(answer),
                exhausted=exhausted,
                runtime="swival",
                resources=profile.resources,
                tool_names=tuple(
                    definition.tool_name for definition in tool_definitions
                ),
                write_tools_enabled=False,
                interrupt=interrupt,
            )
        return SelfManagementBuiltInAgentRunResult(
            status=SelfManagementBuiltInAgentRunStatus.COMPLETED,
            answer=answer,
            exhausted=exhausted,
            runtime="swival",
            resources=profile.resources,
            tool_names=tuple(definition.tool_name for definition in tool_definitions),
            write_tools_enabled=allow_write_tools,
        )

    async def reply_permission_interrupt(
        self,
        *,
        current_user: User,
        request_id: str,
        reply: str,
    ) -> SelfManagementBuiltInAgentRunResult:
        claims = verify_self_management_interrupt_token_claims(request_id)
        if claims is None:
            raise SelfManagementBuiltInAgentUnavailableError(
                "The write approval request is invalid or expired."
            )
        if claims.subject != str(current_user.id):
            raise SelfManagementBuiltInAgentUnavailableError(
                "The write approval request does not belong to the current user."
            )

        if reply == "reject":
            return SelfManagementBuiltInAgentRunResult(
                status=SelfManagementBuiltInAgentRunStatus.COMPLETED,
                answer="Write approval was rejected. No changes were made.",
                exhausted=False,
                runtime="swival",
                resources=self.get_profile().resources,
                tool_names=tuple(get_self_management_interrupt_tool_names(claims)),
                write_tools_enabled=False,
            )

        interrupt_message = get_self_management_interrupt_message(claims)
        if interrupt_message is None:
            raise SelfManagementBuiltInAgentUnavailableError(
                "The write approval request is missing the original prompt."
            )

        return await self.run(
            current_user=current_user,
            message=interrupt_message,
            allow_write_tools=True,
        )

    def _build_mcp_url(self, *, allow_write_tools: bool) -> str:
        base = cast(str, settings.self_management_swival_mcp_base_url).rstrip("/")
        mount_path = (
            SELF_MANAGEMENT_MCP_WRITE_MOUNT_PATH
            if allow_write_tools
            else SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH
        )
        return f"{base}{mount_path}/"

    def _build_system_prompt(self, *, allow_write_tools: bool) -> str:
        if allow_write_tools:
            return _DEFAULT_SYSTEM_PROMPT + _WRITE_ENABLED_APPENDIX
        return _DEFAULT_SYSTEM_PROMPT + _READ_ONLY_APPENDIX

    def _answer_requests_write_approval(self, answer: str | None) -> bool:
        if not isinstance(answer, str):
            return False
        return _WRITE_APPROVAL_SENTINEL in answer

    def _strip_write_approval_sentinel(self, answer: str | None) -> str | None:
        if not isinstance(answer, str):
            return answer
        stripped = answer.replace(_WRITE_APPROVAL_SENTINEL, "").strip()
        return stripped or None

    def _build_permission_interrupt(
        self,
        *,
        current_user: User,
        message: str,
        answer: str | None,
    ) -> SelfManagementBuiltInAgentInterrupt:
        write_tool_names = tuple(
            definition.tool_name
            for definition in self._select_run_tool_definitions(allow_write_tools=True)
            if definition.confirmation_policy != SelfManagementConfirmationPolicy.NONE
        )
        request_id = create_self_management_interrupt_token(
            cast(Any, current_user.id),
            message=message,
            tool_names=write_tool_names,
        )
        display_message = self._strip_write_approval_sentinel(answer) or (
            "This change requires explicit write approval before the built-in agent "
            "can continue."
        )
        return SelfManagementBuiltInAgentInterrupt(
            request_id=request_id,
            permission="self-management-write",
            patterns=write_tool_names,
            display_message=display_message,
        )

    def _select_run_tool_definitions(
        self, *, allow_write_tools: bool
    ) -> tuple[SelfManagementToolDefinition, ...]:
        tool_definitions = list_self_management_mcp_tool_definitions()
        if allow_write_tools:
            return tool_definitions
        return tuple(
            definition
            for definition in tool_definitions
            if definition.confirmation_policy == SelfManagementConfirmationPolicy.NONE
        )

    def _run_swival_session(
        self,
        *,
        message: str,
        mcp_url: str,
        access_token: str,
        system_prompt: str,
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
            system_prompt=system_prompt,
            files="none",
            commands="none",
            no_skills=True,
            history=False,
            memory=False,
            continue_here=False,
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
