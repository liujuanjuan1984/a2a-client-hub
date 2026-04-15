"""Swival-backed built-in agent runtime for self-management entry points."""

from __future__ import annotations

import asyncio
import copy
import importlib
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    SELF_MANAGEMENT_INTERRUPT_TOKEN_TYPE,
    create_self_management_access_token,
    create_self_management_interrupt_token,
    get_self_management_allowed_operations,
    get_self_management_interrupt_conversation_id,
    get_self_management_interrupt_message,
    get_self_management_interrupt_tool_names,
    verify_jwt_token_claims,
)
from app.db.models.agent_message import AgentMessage
from app.db.models.user import User
from app.features.self_management_shared.constants import (
    SELF_MANAGEMENT_BUILT_IN_AGENT_INTERNAL_ID,
    SELF_MANAGEMENT_BUILT_IN_AGENT_PUBLIC_ID,
)
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
from app.features.sessions import block_store, message_store
from app.features.sessions.common import (
    SessionSource,
    normalize_interrupt_lifecycle_event,
    parse_conversation_id,
    project_message_blocks,
    sender_to_role,
)
from app.features.sessions.service import session_hub_service
from app.features.sessions.support import SessionHubSupport
from app.utils.timezone_util import utc_now

_DEFAULT_AGENT_ID = SELF_MANAGEMENT_BUILT_IN_AGENT_PUBLIC_ID
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
_WRITE_APPROVAL_OPERATIONS_PREFIX = "[[SELF_MANAGEMENT_WRITE_OPERATIONS:"
_WRITE_APPROVAL_OPERATIONS_SUFFIX = "]]"
_READ_ONLY_APPENDIX = (
    " This run is read-only. Do not attempt write operations. If the user's latest "
    "request would require a write tool, explain the intended change briefly, do not "
    "claim that any change was applied, append a final line containing exactly "
    f"{_WRITE_APPROVAL_SENTINEL}, then append one more final line containing exactly "
    "`[[SELF_MANAGEMENT_WRITE_OPERATIONS:<comma-separated operation ids>]]` using "
    "only the required write operation ids from this catalog: "
    "self.agents.check_health, self.agents.check_health_all, self.agents.create, "
    "self.agents.delete, self.agents.update_config, self.jobs.create, "
    "self.jobs.delete, self.jobs.pause, self.jobs.resume, self.jobs.update, "
    "self.jobs.update_prompt, self.jobs.update_schedule, self.sessions.archive, "
    "self.sessions.unarchive, self.sessions.update."
)
_WRITE_ENABLED_APPENDIX = (
    " This run includes explicitly approved write tools. Only perform a write when "
    "the user's latest request clearly asks for that change. When additional write "
    "operations outside the approved tool set are needed, do not claim that any "
    "change was applied, append the approval sentinel, and append the exact "
    "operation ids that still require approval."
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


@dataclass(frozen=True)
class SelfManagementBuiltInAgentRecoveredInterrupt:
    """One unresolved persisted interrupt recovered from durable session history."""

    request_id: str
    session_id: str
    type: str
    details: dict[str, Any]


@dataclass(frozen=True)
class _ExecutedBuiltInRun:
    """Internal swival execution result together with durable session context."""

    result: SelfManagementBuiltInAgentRunResult
    profile: SelfManagementBuiltInAgentProfile
    local_session: Any
    local_session_id: str
    local_source: SessionSource


@dataclass
class _ConversationRuntimeState:
    """One in-memory swival conversation runtime owned by one user conversation."""

    session: Any | None = None
    delegated_write_operation_ids: frozenset[str] = frozenset()
    auto_approve_write_operation_ids: frozenset[str] = frozenset()
    delegated_token_expires_at_monotonic: float = 0.0
    last_accessed_monotonic: float = 0.0
    lock: asyncio.Lock | None = None

    def get_lock(self) -> asyncio.Lock:
        if self.lock is None:
            self.lock = asyncio.Lock()
        return self.lock


class SelfManagementBuiltInAgentService:
    """High-level facade for the swival-driven built-in self-management agent."""

    def __init__(self) -> None:
        self._conversation_registry: dict[
            tuple[str, str], _ConversationRuntimeState
        ] = {}
        self._registry_lock = threading.Lock()
        self._session_support = SessionHubSupport()

    def _delegated_token_ttl_seconds(self) -> int:
        return min(
            settings.jwt_access_token_ttl_seconds,
            settings.self_management_swival_delegated_token_ttl_seconds,
        )

    def _delegated_token_refresh_skew_seconds(self) -> int:
        ttl_seconds = self._delegated_token_ttl_seconds()
        return max(5, min(30, ttl_seconds // 10 or 1))

    def _runtime_session_needs_refresh(
        self,
        *,
        runtime_state: _ConversationRuntimeState,
        delegated_write_operation_ids: frozenset[str],
    ) -> bool:
        if runtime_state.session is None:
            return True
        if runtime_state.delegated_write_operation_ids != delegated_write_operation_ids:
            return True
        expires_at = runtime_state.delegated_token_expires_at_monotonic
        if expires_at <= 0:
            return False
        refresh_cutoff = expires_at - self._delegated_token_refresh_skew_seconds()
        return time.monotonic() >= refresh_cutoff

    async def _invalidate_runtime_session(
        self,
        runtime_state: _ConversationRuntimeState,
    ) -> None:
        session = runtime_state.session
        runtime_state.session = None
        runtime_state.delegated_token_expires_at_monotonic = 0.0
        runtime_state.delegated_write_operation_ids = frozenset()
        runtime_state.last_accessed_monotonic = time.monotonic()
        if session is not None:
            await asyncio.to_thread(self._close_swival_session, session)

    def _extract_mcp_runtime_error(self, result: Any) -> str | None:
        raw_messages = getattr(result, "messages", None)
        if not isinstance(raw_messages, list):
            return None
        for raw_message in reversed(raw_messages):
            if not isinstance(raw_message, dict):
                continue
            if raw_message.get("role") != "tool":
                continue
            content = raw_message.get("content")
            if not isinstance(content, str):
                continue
            normalized = content.strip()
            if normalized.startswith("error: MCP server "):
                return normalized
        return None

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
        return (
            self._has_required_runtime_configuration() and self._is_swival_importable()
        )

    async def run(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        conversation_id: str,
        message: str,
        allow_write_tools: bool,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
    ) -> SelfManagementBuiltInAgentRunResult:
        executed = await self._execute_run(
            db=db,
            current_user=current_user,
            conversation_id=conversation_id,
            message=message,
            allow_write_tools=allow_write_tools,
        )
        await self._persist_run_turn(
            db=db,
            current_user=current_user,
            local_session=executed.local_session,
            local_session_id=executed.local_session_id,
            local_source=executed.local_source,
            query=message,
            user_message_id=user_message_id,
            agent_message_id=agent_message_id,
            result=executed.result,
        )
        return executed.result

    async def recover_pending_interrupts(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        conversation_id: str,
    ) -> list[SelfManagementBuiltInAgentRecoveredInterrupt]:
        resolved_conversation_id = parse_conversation_id(conversation_id)
        local_session = await self._session_support.get_local_session_by_id(
            db,
            user_id=cast(Any, current_user.id),
            local_session_id=resolved_conversation_id,
        )
        if local_session is None:
            return []

        rows = list(
            (
                await db.scalars(
                    select(AgentMessage)
                    .where(
                        AgentMessage.user_id == cast(Any, current_user.id),
                        AgentMessage.conversation_id == resolved_conversation_id,
                        AgentMessage.sender == "system",
                    )
                    .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
                )
            ).all()
        )

        asked_interrupts: dict[str, dict[str, Any]] = {}
        ordered_request_ids: list[str] = []
        expired_request_ids: list[str] = []
        for message in rows:
            metadata = cast(dict[str, Any], message.message_metadata or {})
            interrupt = normalize_interrupt_lifecycle_event(
                cast(dict[str, Any] | None, metadata.get("interrupt"))
            )
            if interrupt is None:
                continue
            request_id = cast(str | None, interrupt.get("request_id"))
            if not request_id:
                continue
            phase = cast(str | None, interrupt.get("phase"))
            if phase == "asked":
                asked_interrupts[request_id] = interrupt
                if request_id not in ordered_request_ids:
                    ordered_request_ids.append(request_id)
                continue
            if phase == "resolved":
                asked_interrupts.pop(request_id, None)

        recovered: list[SelfManagementBuiltInAgentRecoveredInterrupt] = []
        for request_id in ordered_request_ids:
            interrupt = asked_interrupts.get(request_id)
            if interrupt is None:
                continue
            claims = verify_jwt_token_claims(
                request_id,
                expected_type=SELF_MANAGEMENT_INTERRUPT_TOKEN_TYPE,
            )
            if claims is None:
                expired_request_ids.append(request_id)
                continue
            if claims.subject != str(current_user.id):
                expired_request_ids.append(request_id)
                continue
            if get_self_management_interrupt_conversation_id(claims) != str(
                resolved_conversation_id
            ):
                expired_request_ids.append(request_id)
                continue
            if get_self_management_interrupt_message(claims) is None:
                expired_request_ids.append(request_id)
                continue
            recovered.append(
                SelfManagementBuiltInAgentRecoveredInterrupt(
                    request_id=request_id,
                    session_id=str(resolved_conversation_id),
                    type=cast(str, interrupt["type"]),
                    details=cast(dict[str, Any], interrupt.get("details") or {}),
                )
            )

        for request_id in expired_request_ids:
            await self._persist_interrupt_resolution(
                db=db,
                current_user=current_user,
                conversation_id=str(resolved_conversation_id),
                request_id=request_id,
                resolution="expired",
            )
        return recovered

    async def _execute_run(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        conversation_id: str,
        message: str,
        allow_write_tools: bool,
        allowed_write_operation_ids: frozenset[str] = frozenset(),
    ) -> _ExecutedBuiltInRun:
        if not self.is_configured():
            raise SelfManagementBuiltInAgentConfigError(
                "The self-management built-in agent is not configured. "
                "Set SELF_MANAGEMENT_SWIVAL_PROVIDER and SELF_MANAGEMENT_SWIVAL_MODEL."
            )

        normalized_conversation_id = conversation_id.strip()
        if not normalized_conversation_id:
            raise SelfManagementBuiltInAgentUnavailableError(
                "conversation_id is required for the built-in agent runtime."
            )

        local_session, local_source = await self._ensure_local_builtin_session(
            db=db,
            current_user=current_user,
            conversation_id=normalized_conversation_id,
        )
        local_session_id = str(local_session.id)
        profile = self.get_profile()
        runtime_state = await self._get_conversation_runtime_state(
            current_user_id=str(current_user.id),
            conversation_id=local_session_id,
        )
        tool_definitions: tuple[SelfManagementToolDefinition, ...]
        async with runtime_state.get_lock():
            effective_write_operation_ids = (
                allowed_write_operation_ids
                if allowed_write_operation_ids
                else (
                    frozenset(
                        definition.operation_id
                        for definition in self._list_write_tool_definitions()
                    )
                    if allow_write_tools
                    else runtime_state.auto_approve_write_operation_ids
                )
            )
            effective_write_tools = allow_write_tools or bool(
                effective_write_operation_ids
            )
            tool_definitions = self._select_run_tool_definitions(
                allow_write_tools=effective_write_tools,
                delegated_write_operation_ids=effective_write_operation_ids,
            )
            session = await self._ensure_conversation_session(
                db=db,
                runtime_state=runtime_state,
                current_user=current_user,
                conversation_id=local_session_id,
                delegated_write_operation_ids=effective_write_operation_ids,
            )
            try:
                result = await asyncio.to_thread(session.ask, message)
            except Exception as exc:  # pragma: no cover - exercised with integration
                await self._invalidate_runtime_session(runtime_state)
                raise SelfManagementBuiltInAgentUnavailableError(
                    f"swival built-in agent run failed: {exc}"
                ) from exc
            mcp_runtime_error = self._extract_mcp_runtime_error(result)
            if mcp_runtime_error is not None:
                await self._invalidate_runtime_session(runtime_state)
                raise SelfManagementBuiltInAgentUnavailableError(
                    f"swival built-in agent MCP call failed: {mcp_runtime_error}"
                )
            runtime_state.last_accessed_monotonic = time.monotonic()
        answer = cast(str | None, getattr(result, "answer", None))
        exhausted = bool(getattr(result, "exhausted", False))
        if not effective_write_tools and self._answer_requests_write_approval(answer):
            requested_write_operation_ids = self._extract_requested_write_operation_ids(
                answer
            )
            if not requested_write_operation_ids:
                await self._invalidate_runtime_session(runtime_state)
                raise SelfManagementBuiltInAgentUnavailableError(
                    "swival built-in agent requested write approval without "
                    "declaring any write operations"
                )
            interrupt = self._build_permission_interrupt(
                current_user=current_user,
                conversation_id=local_session_id,
                message=message,
                answer=answer,
                allowed_write_operation_ids=requested_write_operation_ids,
            )
            return _ExecutedBuiltInRun(
                result=SelfManagementBuiltInAgentRunResult(
                    status=SelfManagementBuiltInAgentRunStatus.INTERRUPTED,
                    answer=self._strip_write_approval_metadata(answer),
                    exhausted=exhausted,
                    runtime="swival",
                    resources=profile.resources,
                    tool_names=tuple(
                        definition.tool_name for definition in tool_definitions
                    ),
                    write_tools_enabled=False,
                    interrupt=interrupt,
                ),
                profile=profile,
                local_session=local_session,
                local_session_id=local_session_id,
                local_source=local_source,
            )
        if effective_write_tools and self._answer_requests_write_approval(answer):
            requested_write_operation_ids = self._extract_requested_write_operation_ids(
                answer
            )
            if not requested_write_operation_ids:
                await self._invalidate_runtime_session(runtime_state)
                raise SelfManagementBuiltInAgentUnavailableError(
                    "swival built-in agent requested write approval without "
                    "declaring any write operations"
                )
            missing_write_operation_ids = tuple(
                operation_id
                for operation_id in requested_write_operation_ids
                if operation_id not in effective_write_operation_ids
            )
            if not missing_write_operation_ids:
                await self._invalidate_runtime_session(runtime_state)
                raise SelfManagementBuiltInAgentUnavailableError(
                    "swival built-in agent requested write approval after write "
                    "tools were enabled"
                )
            interrupt = self._build_permission_interrupt(
                current_user=current_user,
                conversation_id=local_session_id,
                message=message,
                answer=answer,
                allowed_write_operation_ids=missing_write_operation_ids,
            )
            return _ExecutedBuiltInRun(
                result=SelfManagementBuiltInAgentRunResult(
                    status=SelfManagementBuiltInAgentRunStatus.INTERRUPTED,
                    answer=self._strip_write_approval_metadata(answer),
                    exhausted=exhausted,
                    runtime="swival",
                    resources=profile.resources,
                    tool_names=tuple(
                        definition.tool_name for definition in tool_definitions
                    ),
                    write_tools_enabled=True,
                    interrupt=interrupt,
                ),
                profile=profile,
                local_session=local_session,
                local_session_id=local_session_id,
                local_source=local_source,
            )
        return _ExecutedBuiltInRun(
            result=SelfManagementBuiltInAgentRunResult(
                status=SelfManagementBuiltInAgentRunStatus.COMPLETED,
                answer=answer,
                exhausted=exhausted,
                runtime="swival",
                resources=profile.resources,
                tool_names=tuple(
                    definition.tool_name for definition in tool_definitions
                ),
                write_tools_enabled=effective_write_tools,
            ),
            profile=profile,
            local_session=local_session,
            local_session_id=local_session_id,
            local_source=local_source,
        )

    async def reply_permission_interrupt(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        request_id: str,
        reply: str,
        agent_message_id: UUID | None = None,
    ) -> SelfManagementBuiltInAgentRunResult:
        claims = verify_jwt_token_claims(
            request_id,
            expected_type=SELF_MANAGEMENT_INTERRUPT_TOKEN_TYPE,
        )
        if claims is None:
            raise SelfManagementBuiltInAgentUnavailableError(
                "The write approval request is invalid or expired."
            )
        if claims.subject != str(current_user.id):
            raise SelfManagementBuiltInAgentUnavailableError(
                "The write approval request does not belong to the current user."
            )

        conversation_id = get_self_management_interrupt_conversation_id(claims)
        if conversation_id is None:
            raise SelfManagementBuiltInAgentUnavailableError(
                "The write approval request is missing the conversation context."
            )
        interrupt_message = get_self_management_interrupt_message(claims)
        if interrupt_message is None:
            raise SelfManagementBuiltInAgentUnavailableError(
                "The write approval request is missing the original prompt."
            )
        approved_operation_ids = get_self_management_allowed_operations(claims)
        if not approved_operation_ids:
            raise SelfManagementBuiltInAgentUnavailableError(
                "The write approval request is missing the approved operations."
            )

        if reply == "reject":
            result = SelfManagementBuiltInAgentRunResult(
                status=SelfManagementBuiltInAgentRunStatus.COMPLETED,
                answer="Write approval was rejected. No changes were made.",
                exhausted=False,
                runtime="swival",
                resources=self.get_profile().resources,
                tool_names=tuple(get_self_management_interrupt_tool_names(claims)),
                write_tools_enabled=False,
            )
            await self._persist_interrupt_resolution(
                db=db,
                current_user=current_user,
                conversation_id=conversation_id,
                request_id=request_id,
                resolution="rejected",
            )
            await self._persist_follow_up_agent_message(
                db=db,
                current_user=current_user,
                conversation_id=conversation_id,
                answer=result.answer,
                agent_message_id=agent_message_id,
                metadata={
                    "built_in_agent": True,
                    "runtime": result.runtime,
                    "reply_resolution": "rejected",
                    "interrupt_request_id": request_id,
                    "tools": list(result.tool_names),
                    "write_tools_enabled": result.write_tools_enabled,
                },
                status="done",
                finish_reason="interrupt_rejected",
            )
            return result

        if reply == "always":
            runtime_state = await self._get_conversation_runtime_state(
                current_user_id=str(current_user.id),
                conversation_id=conversation_id,
            )
            async with runtime_state.get_lock():
                approved_operation_ids = (
                    runtime_state.auto_approve_write_operation_ids
                    | runtime_state.delegated_write_operation_ids
                    | approved_operation_ids
                )
                runtime_state.auto_approve_write_operation_ids = approved_operation_ids
                runtime_state.last_accessed_monotonic = time.monotonic()
        else:
            runtime_state = await self._get_conversation_runtime_state(
                current_user_id=str(current_user.id),
                conversation_id=conversation_id,
            )
            async with runtime_state.get_lock():
                approved_operation_ids = (
                    runtime_state.auto_approve_write_operation_ids
                    | runtime_state.delegated_write_operation_ids
                    | approved_operation_ids
                )
                runtime_state.last_accessed_monotonic = time.monotonic()

        executed = await self._execute_run(
            db=db,
            current_user=current_user,
            conversation_id=conversation_id,
            message=interrupt_message,
            allow_write_tools=True,
            allowed_write_operation_ids=approved_operation_ids,
        )
        await self._persist_interrupt_resolution(
            db=db,
            current_user=current_user,
            conversation_id=conversation_id,
            request_id=request_id,
            resolution="replied",
        )
        await self._persist_follow_up_agent_message(
            db=db,
            current_user=current_user,
            conversation_id=conversation_id,
            answer=executed.result.answer,
            agent_message_id=agent_message_id,
            metadata={
                "built_in_agent": True,
                "runtime": executed.result.runtime,
                "reply_resolution": "replied",
                "interrupt_request_id": request_id,
                "tools": list(executed.result.tool_names),
                "write_tools_enabled": executed.result.write_tools_enabled,
            },
            status=(
                "interrupted"
                if executed.result.status
                == SelfManagementBuiltInAgentRunStatus.INTERRUPTED
                else "done"
            ),
            finish_reason=(
                "interrupt"
                if executed.result.status
                == SelfManagementBuiltInAgentRunStatus.INTERRUPTED
                else "completed"
            ),
        )
        if executed.result.interrupt is not None:
            await self._persist_permission_interrupt(
                db=db,
                current_user=current_user,
                local_session_id=executed.local_session_id,
                interrupt=executed.result.interrupt,
            )
        return executed.result

    def _build_mcp_url(self, *, allow_write_tools: bool) -> str:
        base = cast(str, settings.self_management_swival_mcp_base_url).rstrip("/")
        mount_path = (
            SELF_MANAGEMENT_MCP_WRITE_MOUNT_PATH
            if allow_write_tools
            else SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH
        )
        return f"{base}{mount_path}/"

    def _build_system_prompt(
        self,
        *,
        allow_write_tools: bool,
        delegated_write_operation_ids: frozenset[str] = frozenset(),
    ) -> str:
        if allow_write_tools:
            if delegated_write_operation_ids:
                approved_operations = ", ".join(sorted(delegated_write_operation_ids))
                return (
                    _DEFAULT_SYSTEM_PROMPT
                    + _WRITE_ENABLED_APPENDIX
                    + f" The currently approved write operations are: {approved_operations}."
                )
            return _DEFAULT_SYSTEM_PROMPT + _WRITE_ENABLED_APPENDIX
        return _DEFAULT_SYSTEM_PROMPT + _READ_ONLY_APPENDIX

    def _answer_requests_write_approval(self, answer: str | None) -> bool:
        if not isinstance(answer, str):
            return False
        return _WRITE_APPROVAL_SENTINEL in answer

    def _strip_write_approval_metadata(self, answer: str | None) -> str | None:
        if not isinstance(answer, str):
            return answer
        stripped_lines = [
            line.strip()
            for line in answer.splitlines()
            if line.strip()
            and line.strip() != _WRITE_APPROVAL_SENTINEL
            and not (
                line.strip().startswith(_WRITE_APPROVAL_OPERATIONS_PREFIX)
                and line.strip().endswith(_WRITE_APPROVAL_OPERATIONS_SUFFIX)
            )
        ]
        stripped = "\n".join(stripped_lines).strip()
        return stripped or None

    def _list_write_tool_definitions(self) -> tuple[SelfManagementToolDefinition, ...]:
        return tuple(
            definition
            for definition in list_self_management_mcp_tool_definitions()
            if definition.confirmation_policy != SelfManagementConfirmationPolicy.NONE
        )

    def _extract_requested_write_operation_ids(
        self,
        answer: str | None,
    ) -> tuple[str, ...]:
        if not isinstance(answer, str):
            return ()
        allowed_operation_ids = {
            definition.operation_id
            for definition in self._list_write_tool_definitions()
        }
        requested_operation_ids: list[str] = []
        for raw_line in answer.splitlines():
            line = raw_line.strip()
            if not (
                line.startswith(_WRITE_APPROVAL_OPERATIONS_PREFIX)
                and line.endswith(_WRITE_APPROVAL_OPERATIONS_SUFFIX)
            ):
                continue
            raw_payload = line.removeprefix(
                _WRITE_APPROVAL_OPERATIONS_PREFIX
            ).removesuffix(_WRITE_APPROVAL_OPERATIONS_SUFFIX)
            for raw_operation_id in raw_payload.split(","):
                operation_id = raw_operation_id.strip()
                if (
                    operation_id
                    and operation_id in allowed_operation_ids
                    and operation_id not in requested_operation_ids
                ):
                    requested_operation_ids.append(operation_id)
        return tuple(requested_operation_ids)

    def _build_permission_interrupt(
        self,
        *,
        current_user: User,
        conversation_id: str,
        message: str,
        answer: str | None,
        allowed_write_operation_ids: tuple[str, ...],
    ) -> SelfManagementBuiltInAgentInterrupt:
        write_tool_definitions = tuple(
            definition
            for definition in self._list_write_tool_definitions()
            if definition.operation_id in allowed_write_operation_ids
        )
        request_id = create_self_management_interrupt_token(
            cast(Any, current_user.id),
            conversation_id=conversation_id,
            message=message,
            tool_names=tuple(
                definition.tool_name for definition in write_tool_definitions
            ),
            allowed_operations=allowed_write_operation_ids,
        )
        display_message = self._strip_write_approval_metadata(answer) or (
            "This change requires explicit write approval before the built-in agent "
            "can continue."
        )
        return SelfManagementBuiltInAgentInterrupt(
            request_id=request_id,
            permission="self-management-write",
            patterns=tuple(
                definition.tool_name for definition in write_tool_definitions
            ),
            display_message=display_message,
        )

    def _select_run_tool_definitions(
        self,
        *,
        allow_write_tools: bool,
        delegated_write_operation_ids: frozenset[str] = frozenset(),
    ) -> tuple[SelfManagementToolDefinition, ...]:
        tool_definitions = list_self_management_mcp_tool_definitions()
        if allow_write_tools and not delegated_write_operation_ids:
            return tool_definitions
        allowed_write_operation_ids = (
            delegated_write_operation_ids if allow_write_tools else frozenset()
        )
        return tuple(
            definition
            for definition in tool_definitions
            if definition.confirmation_policy == SelfManagementConfirmationPolicy.NONE
            or definition.operation_id in allowed_write_operation_ids
        )

    async def _ensure_local_builtin_session(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        conversation_id: str,
    ) -> tuple[Any, SessionSource]:
        session, source = await session_hub_service.ensure_local_session_for_invoke(
            db,
            user_id=cast(Any, current_user.id),
            agent_id=SELF_MANAGEMENT_BUILT_IN_AGENT_INTERNAL_ID,
            agent_source="builtin",
            conversation_id=conversation_id,
        )
        if session is None or source is None:
            raise SelfManagementBuiltInAgentUnavailableError(
                "Failed to bind the built-in agent conversation to a durable session."
            )
        return session, source

    async def _persist_run_turn(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        local_session: Any,
        local_session_id: str,
        local_source: SessionSource,
        query: str,
        user_message_id: UUID | None,
        agent_message_id: UUID | None,
        result: SelfManagementBuiltInAgentRunResult,
    ) -> None:
        await session_hub_service.record_local_invoke_messages(
            db,
            session=local_session,
            source=local_source,
            user_id=cast(Any, current_user.id),
            agent_id=SELF_MANAGEMENT_BUILT_IN_AGENT_INTERNAL_ID,
            agent_source="builtin",
            query=query,
            response_content=result.answer or "",
            success=result.status == SelfManagementBuiltInAgentRunStatus.COMPLETED,
            context_id=None,
            extra_metadata={
                "built_in_agent": True,
                "built_in_agent_id": SELF_MANAGEMENT_BUILT_IN_AGENT_PUBLIC_ID,
                "runtime": result.runtime,
                "resources": list(result.resources),
                "write_tools_enabled": result.write_tools_enabled,
            },
            response_metadata={
                "tools": list(result.tool_names),
                "write_tools_enabled": result.write_tools_enabled,
                "built_in_agent": True,
            },
            user_message_id=user_message_id,
            agent_message_id=agent_message_id,
            agent_status=(
                "interrupted"
                if result.status == SelfManagementBuiltInAgentRunStatus.INTERRUPTED
                else "done"
            ),
            finish_reason=(
                "interrupt"
                if result.status == SelfManagementBuiltInAgentRunStatus.INTERRUPTED
                else "completed"
            ),
            error_code=None,
        )
        if result.interrupt is None:
            return
        await self._persist_permission_interrupt(
            db=db,
            current_user=current_user,
            local_session_id=local_session_id,
            interrupt=result.interrupt,
        )

    async def _persist_permission_interrupt(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        local_session_id: str,
        interrupt: SelfManagementBuiltInAgentInterrupt,
    ) -> None:
        await session_hub_service.record_interrupt_lifecycle_event_by_local_session_id(
            db,
            local_session_id=parse_conversation_id(local_session_id),
            user_id=cast(Any, current_user.id),
            event={
                "request_id": interrupt.request_id,
                "type": "permission",
                "phase": "asked",
                "details": {
                    "permission": interrupt.permission,
                    "patterns": list(interrupt.patterns),
                    "displayMessage": interrupt.display_message,
                },
            },
        )

    async def _persist_interrupt_resolution(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        conversation_id: str,
        request_id: str,
        resolution: str,
    ) -> None:
        await session_hub_service.record_interrupt_lifecycle_event_by_local_session_id(
            db,
            local_session_id=parse_conversation_id(conversation_id),
            user_id=cast(Any, current_user.id),
            event={
                "request_id": request_id,
                "type": "permission",
                "phase": "resolved",
                "resolution": resolution,
            },
        )

    async def _persist_follow_up_agent_message(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        conversation_id: str,
        answer: str | None,
        agent_message_id: UUID | None,
        metadata: dict[str, Any],
        status: str,
        finish_reason: str | None,
    ) -> None:
        local_session, _ = await self._ensure_local_builtin_session(
            db=db,
            current_user=current_user,
            conversation_id=conversation_id,
        )
        setattr(local_session, "last_active_at", utc_now())
        create_kwargs: dict[str, Any] = {
            "user_id": cast(Any, current_user.id),
            "sender": "agent",
            "conversation_id": cast(Any, local_session.id),
            "status": status,
            "finish_reason": finish_reason,
            "metadata": metadata,
        }
        if agent_message_id is not None:
            create_kwargs["id"] = agent_message_id
        agent_message = await message_store.create_agent_message(
            db,
            **create_kwargs,
        )
        await self._session_support.upsert_single_text_block(
            db,
            user_id=cast(Any, current_user.id),
            message_id=cast(Any, agent_message.id),
            content=answer or "",
            source="self_management_built_in_reply",
        )

    async def _get_conversation_runtime_state(
        self,
        *,
        current_user_id: str,
        conversation_id: str,
    ) -> _ConversationRuntimeState:
        await self._cleanup_expired_conversations()
        key = (current_user_id, conversation_id)
        with self._registry_lock:
            runtime_state = self._conversation_registry.get(key)
            if runtime_state is None:
                runtime_state = _ConversationRuntimeState(
                    last_accessed_monotonic=time.monotonic()
                )
                self._conversation_registry[key] = runtime_state
            return runtime_state

    async def _cleanup_expired_conversations(self) -> None:
        cutoff = time.monotonic() - settings.self_management_swival_session_ttl_seconds
        expired_sessions: list[Any] = []
        with self._registry_lock:
            expired_keys = [
                key
                for key, runtime_state in self._conversation_registry.items()
                if runtime_state.last_accessed_monotonic
                and runtime_state.last_accessed_monotonic < cutoff
            ]
            for key in expired_keys:
                runtime_state = self._conversation_registry.pop(key)
                if runtime_state.session is not None:
                    expired_sessions.append(runtime_state.session)
        for session in expired_sessions:
            await asyncio.to_thread(self._close_swival_session, session)

    async def _ensure_conversation_session(
        self,
        *,
        db: AsyncSession,
        runtime_state: _ConversationRuntimeState,
        current_user: User,
        conversation_id: str,
        delegated_write_operation_ids: frozenset[str],
    ) -> Any:
        if not self._runtime_session_needs_refresh(
            runtime_state=runtime_state,
            delegated_write_operation_ids=delegated_write_operation_ids,
        ):
            runtime_state.last_accessed_monotonic = time.monotonic()
            return runtime_state.session

        previous_session = runtime_state.session
        new_session = await asyncio.to_thread(
            self._create_swival_session,
            current_user=current_user,
            delegated_write_operation_ids=delegated_write_operation_ids,
        )
        if previous_session is not None:
            await asyncio.to_thread(
                self._transfer_conversation_state, previous_session, new_session
            )
            await asyncio.to_thread(self._close_swival_session, previous_session)
        else:
            await self._best_effort_rehydrate_swival_session(
                db=db,
                current_user=current_user,
                conversation_id=conversation_id,
                session=new_session,
            )

        runtime_state.session = new_session
        runtime_state.delegated_write_operation_ids = delegated_write_operation_ids
        runtime_state.delegated_token_expires_at_monotonic = float(
            getattr(
                new_session,
                "_self_management_delegated_token_expires_at_monotonic",
                0.0,
            )
        )
        runtime_state.last_accessed_monotonic = time.monotonic()
        return new_session

    async def _best_effort_rehydrate_swival_session(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        conversation_id: str,
        session: Any,
    ) -> None:
        persisted_messages = await self._list_persisted_runtime_messages(
            db=db,
            current_user=current_user,
            conversation_id=conversation_id,
        )
        if not persisted_messages:
            return

        setup = getattr(session, "_setup", None)
        if callable(setup):
            try:
                await asyncio.to_thread(setup)
            except Exception:
                return

        existing_state = cast(
            dict[str, Any] | None, getattr(session, "_conv_state", None)
        )
        if isinstance(existing_state, dict):
            existing_messages = existing_state.get("messages")
            if isinstance(existing_messages, list) and any(
                not (isinstance(message, dict) and message.get("role") == "system")
                for message in existing_messages
            ):
                return

        make_state = getattr(session, "_make_per_run_state", None)
        if callable(make_state):
            system_content = None
            system_with_memory = getattr(session, "_system_with_memory", None)
            if callable(system_with_memory):
                try:
                    system_content = system_with_memory("", policy="interactive")
                except TypeError:
                    system_content = system_with_memory("")
            try:
                state = cast(
                    dict[str, Any],
                    make_state(system_content=cast(str | None, system_content)),
                )
            except TypeError:
                state = cast(dict[str, Any], make_state())
        else:
            state = {"messages": []}

        existing_messages = state.get("messages")
        system_messages = (
            [
                copy.deepcopy(message)
                for message in existing_messages
                if isinstance(message, dict) and message.get("role") == "system"
            ]
            if isinstance(existing_messages, list)
            else []
        )
        state["messages"] = system_messages + copy.deepcopy(persisted_messages)
        setattr(session, "_conv_state", state)

    async def _list_persisted_runtime_messages(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        conversation_id: str,
    ) -> list[dict[str, str]]:
        resolved_conversation_id = parse_conversation_id(conversation_id)
        sender_priority = case(
            (AgentMessage.sender.in_(["user", "automation"]), 0),
            else_=1,
        )
        rows = list(
            (
                await db.scalars(
                    select(AgentMessage)
                    .where(
                        AgentMessage.user_id == cast(Any, current_user.id),
                        AgentMessage.conversation_id == resolved_conversation_id,
                        AgentMessage.sender.in_(["user", "automation", "agent"]),
                    )
                    .order_by(
                        AgentMessage.created_at.asc(),
                        sender_priority.asc(),
                        AgentMessage.id.asc(),
                    )
                )
            ).all()
        )
        if not rows:
            return []

        message_ids = [cast(Any, message.id) for message in rows]
        blocks = await block_store.list_blocks_by_message_ids(
            db,
            user_id=cast(Any, current_user.id),
            message_ids=message_ids,
        )
        blocks_by_message_id: dict[Any, list[Any]] = {}
        for block in blocks:
            blocks_by_message_id.setdefault(block.message_id, []).append(block)

        persisted_messages: list[dict[str, str]] = []
        for message in rows:
            role = sender_to_role(cast(str, message.sender))
            if role not in {"user", "agent"}:
                continue
            rendered_blocks, content = project_message_blocks(
                blocks_by_message_id.get(message.id, []),
                message_status=cast(str | None, message.status),
            )
            if not content and not rendered_blocks:
                continue
            if role == "agent" and not content:
                continue
            persisted_messages.append(
                {
                    "role": "assistant" if role == "agent" else role,
                    "content": content,
                }
            )
        return persisted_messages

    def _create_swival_session(
        self,
        *,
        current_user: User,
        delegated_write_operation_ids: frozenset[str],
    ) -> Any:
        write_tools_enabled = bool(delegated_write_operation_ids)
        session_cls = self._load_swival_session_cls()
        tool_definitions = self._select_run_tool_definitions(
            allow_write_tools=write_tools_enabled,
            delegated_write_operation_ids=delegated_write_operation_ids,
        )
        delegated_token_ttl_seconds = self._delegated_token_ttl_seconds()
        token = create_self_management_access_token(
            cast(Any, current_user.id),
            allowed_operations=[
                definition.operation_id for definition in tool_definitions
            ],
            delegated_by="self_management_built_in_agent",
        )
        session = session_cls(
            base_dir=self._resolve_swival_base_dir(current_user),
            provider=cast(str, settings.self_management_swival_provider),
            model=cast(str, settings.self_management_swival_model),
            api_key=settings.self_management_swival_api_key,
            base_url=settings.self_management_swival_base_url,
            max_turns=settings.self_management_swival_max_turns,
            max_output_tokens=settings.self_management_swival_max_output_tokens,
            reasoning_effort=settings.self_management_swival_reasoning_effort,
            system_prompt=self._build_system_prompt(
                allow_write_tools=write_tools_enabled,
                delegated_write_operation_ids=delegated_write_operation_ids,
            ),
            files="none",
            commands="none",
            no_skills=True,
            history=False,
            memory=False,
            continue_here=False,
            yolo=False,
            mcp_servers={
                "a2a-client-hub": {
                    "url": self._build_mcp_url(allow_write_tools=write_tools_enabled),
                    "headers": {"Authorization": f"Bearer {token}"},
                }
            },
        )
        setattr(
            session,
            "_self_management_delegated_token_expires_at_monotonic",
            time.monotonic() + delegated_token_ttl_seconds,
        )
        return session

    def _resolve_swival_base_dir(self, current_user: User) -> str:
        configured_root = (settings.self_management_swival_runtime_root or "").strip()
        if configured_root:
            runtime_root = Path(configured_root).expanduser()
        else:
            runtime_root = Path.home() / ".a2a-client-hub" / "swival-users"

        user_runtime_dir = runtime_root / str(current_user.id)
        user_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        for candidate in (runtime_root, user_runtime_dir):
            try:
                candidate.chmod(0o700)
            except OSError:
                continue
        return str(user_runtime_dir.resolve())

    def _build_session_conversation_state(
        self,
        session: Any,
    ) -> dict[str, Any] | None:
        conv_state = getattr(session, "_conv_state", None)
        if isinstance(conv_state, dict):
            return copy.deepcopy(conv_state)

        setup = getattr(session, "_setup", None)
        if callable(setup):
            try:
                setup()
            except Exception:
                return None
            conv_state = getattr(session, "_conv_state", None)
            if isinstance(conv_state, dict):
                return copy.deepcopy(conv_state)

        make_state = getattr(session, "_make_per_run_state", None)
        if not callable(make_state):
            return None

        system_content = None
        system_with_memory = getattr(session, "_system_with_memory", None)
        if callable(system_with_memory):
            try:
                system_content = system_with_memory("", policy="interactive")
            except TypeError:
                system_content = system_with_memory("")
            except Exception:
                system_content = None
        try:
            return cast(
                dict[str, Any],
                make_state(system_content=cast(str | None, system_content)),
            )
        except TypeError:
            return cast(dict[str, Any], make_state())
        except Exception:
            return None

    def _transfer_conversation_state(
        self,
        previous_session: Any,
        next_session: Any,
    ) -> None:
        previous_state = self._build_session_conversation_state(previous_session)
        if previous_state is not None:
            next_state = self._build_session_conversation_state(next_session)
            previous_messages = previous_state.get("messages")
            next_messages = next_state.get("messages") if next_state else None
            previous_non_system_messages = (
                [
                    copy.deepcopy(message)
                    for message in previous_messages
                    if not (
                        isinstance(message, dict) and message.get("role") == "system"
                    )
                ]
                if isinstance(previous_messages, list)
                else []
            )
            next_system_messages = (
                [
                    copy.deepcopy(message)
                    for message in next_messages
                    if isinstance(message, dict) and message.get("role") == "system"
                ]
                if isinstance(next_messages, list)
                else []
            )
            transferred_state = copy.deepcopy(next_state) if next_state else {}
            transferred_state["messages"] = (
                next_system_messages + previous_non_system_messages
            )
            setattr(next_session, "_conv_state", transferred_state)
        trace_session_id = getattr(previous_session, "_trace_session_id", None)
        if isinstance(trace_session_id, str) and trace_session_id.strip():
            setattr(next_session, "_trace_session_id", trace_session_id)

    def _close_swival_session(self, session: Any) -> None:
        close = getattr(session, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                return

    def _load_swival_session_cls(self) -> type[Any]:
        self._inject_swival_import_paths()

        try:
            module = importlib.import_module("swival")
        except ImportError as exc:
            raise SelfManagementBuiltInAgentUnavailableError(
                "swival is not installed or not importable for the built-in agent runtime."
            ) from exc
        self._apply_swival_compatibility_patches()

        session_cls = getattr(module, "Session", None)
        if session_cls is None:
            raise SelfManagementBuiltInAgentUnavailableError(
                "swival.Session is required for the built-in agent runtime."
            )
        return cast(type[Any], session_cls)

    def _apply_swival_compatibility_patches(self) -> None:
        try:
            module = __import__("swival.mcp_client", fromlist=["_mcp_tool_to_openai"])
        except ImportError:
            return

        converter = getattr(module, "_mcp_tool_to_openai", None)
        if not callable(converter) or getattr(
            converter,
            "_a2a_client_hub_private_field_patch",
            False,
        ):
            return

        def _patched_mcp_tool_to_openai(
            server_name: str, tool: Any
        ) -> tuple[dict, str]:
            schema, original_name = converter(server_name, tool)
            function_schema = schema.get("function")
            if isinstance(function_schema, dict):
                for key in list(function_schema.keys()):
                    if key.startswith("_mcp_"):
                        function_schema.pop(key, None)
            return schema, original_name

        setattr(
            _patched_mcp_tool_to_openai,
            "_a2a_client_hub_private_field_patch",
            True,
        )
        setattr(module, "_mcp_tool_to_openai", _patched_mcp_tool_to_openai)

    def _has_required_runtime_configuration(self) -> bool:
        return bool(
            (settings.self_management_swival_provider or "").strip()
            and (settings.self_management_swival_model or "").strip()
            and (settings.self_management_swival_mcp_base_url or "").strip()
        )

    def _is_swival_importable(self) -> bool:
        loaded_module = sys.modules.get("swival")
        if (
            loaded_module is not None
            and getattr(loaded_module, "Session", None) is not None
        ):
            return True

        try:
            importlib.import_module("swival")
            return True
        except ImportError:
            pass

        for candidate in self._resolve_swival_import_paths():
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
            try:
                importlib.import_module("swival")
                return True
            except ImportError:
                continue

        return False

    def _inject_swival_import_paths(self) -> None:
        for candidate in self._resolve_swival_import_paths():
            if candidate not in sys.path:
                sys.path.insert(0, candidate)

    def _resolve_swival_import_paths(self) -> list[str]:
        resolved_paths: list[str] = []
        seen: set[str] = set()
        for raw_path in settings.self_management_swival_import_paths:
            candidate = raw_path.strip()
            if not candidate:
                continue
            resolved = str(Path(candidate).expanduser().resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            resolved_paths.append(resolved)

        for discovered in self._discover_swival_tool_import_paths():
            if discovered in seen:
                continue
            seen.add(discovered)
            resolved_paths.append(discovered)

        return resolved_paths

    def _discover_swival_tool_import_paths(self) -> list[str]:
        executable_setting = (
            settings.self_management_swival_tool_executable or ""
        ).strip()
        executable_path: str | None = None
        if executable_setting:
            candidate = Path(executable_setting).expanduser()
            if candidate.exists():
                executable_path = str(candidate.resolve())
            else:
                executable_path = shutil.which(executable_setting)
        else:
            executable_path = shutil.which("swival")

        if not executable_path:
            return []

        resolved_executable = Path(executable_path).expanduser().resolve()
        venv_bin_dir = resolved_executable.parent
        if venv_bin_dir.name not in {"bin", "Scripts"}:
            return []

        venv_root = venv_bin_dir.parent
        candidate_paths: list[str] = []
        for site_packages in sorted(venv_root.glob("lib/python*/site-packages")):
            candidate_paths.append(str(site_packages.resolve()))

        windows_site_packages = venv_root / "Lib" / "site-packages"
        if windows_site_packages.exists():
            candidate_paths.append(str(windows_site_packages.resolve()))

        return candidate_paths


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
