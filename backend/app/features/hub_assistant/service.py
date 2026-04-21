"""Swival-backed Hub Assistant runtime entry points."""

from __future__ import annotations

import asyncio
import time
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import (
    HUB_ASSISTANT_INTERRUPT_TOKEN_TYPE,
    get_hub_assistant_interrupt_conversation_id,
    get_hub_assistant_interrupt_message,
    get_hub_assistant_interrupt_requested_operations,
    get_hub_assistant_interrupt_tool_names,
    verify_jwt_token_claims,
)
from app.db.models.agent_message import AgentMessage
from app.db.models.conversation_thread import ConversationThread
from app.db.transaction import commit_safely
from app.features.hub_assistant.models import (
    DEFAULT_AGENT_DESCRIPTION,
    DEFAULT_AGENT_ID,
    DEFAULT_AGENT_NAME,
    FOLLOW_UP_RESUME_MESSAGE_TEMPLATE,
    ExecutedHubAssistantRun,
    HubAssistantConfigError,
    HubAssistantContinuation,
    HubAssistantPermissionInterrupt,
    HubAssistantProfile,
    HubAssistantRecoveredPermissionInterrupt,
    HubAssistantRunResult,
    HubAssistantRunStatus,
    HubAssistantUnavailableError,
)
from app.features.hub_assistant.persistence import HubAssistantPersistenceService
from app.features.hub_assistant.shared.hub_assistant_mcp import (
    list_hub_assistant_mcp_tool_definitions,
)
from app.features.hub_assistant.shared.hub_assistant_tool_contract import (
    HubAssistantToolDefinition,
)
from app.features.hub_assistant.shared.task_service import (
    HubAssistantFollowUpTaskRequest,
    PermissionReplyContinuationTaskRequest,
    hub_assistant_task_service,
)
from app.features.hub_assistant.swival_runtime import (
    WRITE_APPROVAL_SENTINEL,
    HubAssistantSwivalRuntime,
)
from app.features.sessions.common import (
    normalize_interrupt_lifecycle_event,
    parse_conversation_id,
)
from app.features.sessions.support import SessionHubSupport

logger = get_logger(__name__)
_WRITE_APPROVAL_SENTINEL = WRITE_APPROVAL_SENTINEL


class HubAssistantService:
    """High-level facade for the Hub Assistant."""

    def __init__(self) -> None:
        self._session_support = SessionHubSupport()
        self._persistence = HubAssistantPersistenceService(
            session_support=self._session_support
        )
        self._runtime = HubAssistantSwivalRuntime(
            persisted_messages_loader=self._persistence.list_persisted_runtime_messages,
            time_module=time,
        )
        self._conversation_registry = self._runtime._conversation_registry

    def get_profile(self) -> HubAssistantProfile:
        tool_definitions = list_hub_assistant_mcp_tool_definitions()
        resources = tuple(
            sorted(
                {
                    definition.operation_id.split(".")[1]
                    for definition in tool_definitions
                }
            )
        )
        return HubAssistantProfile(
            agent_id=DEFAULT_AGENT_ID,
            name=DEFAULT_AGENT_NAME,
            description=DEFAULT_AGENT_DESCRIPTION,
            runtime="swival",
            configured=self.is_configured(),
            resources=resources,
            tool_definitions=tool_definitions,
        )

    def is_configured(self) -> bool:
        return (
            self._runtime.has_required_runtime_configuration()
            and self._is_swival_importable()
        )

    async def run(
        self,
        *,
        db: AsyncSession,
        current_user: Any,
        conversation_id: str,
        message: str,
        allow_write_tools: bool,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
    ) -> HubAssistantRunResult:
        executed = await self._execute_run(
            db=db,
            current_user=current_user,
            conversation_id=conversation_id,
            message=message,
            allow_write_tools=allow_write_tools,
        )
        await self._persistence.persist_run_turn(
            db=db,
            current_user=current_user,
            local_session=executed.local_session,
            local_session_id=executed.local_session_id,
            local_source=cast(Any, executed.local_source),
            query=message,
            user_message_id=user_message_id,
            agent_message_id=agent_message_id,
            result=executed.result,
        )
        return executed.result

    async def recover_pending_permission_interrupts(
        self,
        *,
        db: AsyncSession,
        current_user: Any,
        conversation_id: str,
    ) -> list[HubAssistantRecoveredPermissionInterrupt]:
        resolved_conversation_id = parse_conversation_id(conversation_id)
        recoverable_conversation = cast(
            ConversationThread | None,
            await db.scalar(
                select(ConversationThread).where(
                    ConversationThread.id == resolved_conversation_id,
                    ConversationThread.user_id == cast(Any, current_user.id),
                    ConversationThread.status.in_(
                        [
                            ConversationThread.STATUS_ACTIVE,
                            ConversationThread.STATUS_ARCHIVED,
                        ]
                    ),
                    ConversationThread.source.in_(
                        [
                            ConversationThread.SOURCE_MANUAL,
                            ConversationThread.SOURCE_SCHEDULED,
                        ]
                    ),
                )
            ),
        )
        if recoverable_conversation is None:
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

        recovered: list[HubAssistantRecoveredPermissionInterrupt] = []
        for request_id in ordered_request_ids:
            interrupt = asked_interrupts.get(request_id)
            if interrupt is None:
                continue
            if interrupt.get("type") != "permission":
                continue
            claims = verify_jwt_token_claims(
                request_id,
                expected_type=HUB_ASSISTANT_INTERRUPT_TOKEN_TYPE,
            )
            if claims is None:
                expired_request_ids.append(request_id)
                continue
            if claims.subject != str(current_user.id):
                expired_request_ids.append(request_id)
                continue
            if get_hub_assistant_interrupt_conversation_id(claims) != str(
                resolved_conversation_id
            ):
                expired_request_ids.append(request_id)
                continue
            if get_hub_assistant_interrupt_message(claims) is None:
                expired_request_ids.append(request_id)
                continue
            recovered.append(
                HubAssistantRecoveredPermissionInterrupt(
                    request_id=request_id,
                    session_id=str(resolved_conversation_id),
                    type="permission",
                    details=cast(dict[str, Any], interrupt.get("details") or {}),
                )
            )

        for request_id in expired_request_ids:
            await self._persistence.persist_interrupt_resolution(
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
        current_user: Any,
        conversation_id: str,
        message: str,
        allow_write_tools: bool,
        approved_write_operation_ids: frozenset[str] = frozenset(),
    ) -> ExecutedHubAssistantRun:
        if not self.is_configured():
            raise HubAssistantConfigError(
                "The Hub Assistant is not configured. "
                "Set HUB_ASSISTANT_SWIVAL_PROVIDER and HUB_ASSISTANT_SWIVAL_MODEL."
            )

        normalized_conversation_id = conversation_id.strip()
        if not normalized_conversation_id:
            raise HubAssistantUnavailableError(
                "conversation_id is required for the Hub Assistant runtime."
            )

        try:
            local_session, local_source = (
                await self._persistence.ensure_local_hub_assistant_session(
                    db=db,
                    current_user=current_user,
                    conversation_id=normalized_conversation_id,
                )
            )
        except RuntimeError as exc:
            raise HubAssistantUnavailableError(str(exc)) from exc

        local_session_id = str(local_session.id)
        profile = self.get_profile()
        runtime_state = await self._runtime.get_conversation_runtime_state(
            current_user_id=str(current_user.id),
            conversation_id=local_session_id,
        )

        tool_definitions = cast(tuple[HubAssistantToolDefinition, ...], ())
        async with runtime_state.get_lock():
            runtime_allowed_write_operation_ids = (
                approved_write_operation_ids
                if approved_write_operation_ids
                else (
                    frozenset(
                        definition.operation_id
                        for definition in self._list_write_tool_definitions()
                    )
                    if allow_write_tools
                    else runtime_state.auto_approve_write_operation_ids
                )
            )
            runtime_write_tools_enabled = allow_write_tools or bool(
                runtime_allowed_write_operation_ids
            )
            tool_definitions = self._select_run_tool_definitions(
                allow_write_tools=runtime_write_tools_enabled,
                delegated_write_operation_ids=runtime_allowed_write_operation_ids,
            )
            session = await self._runtime.ensure_conversation_session(
                db=db,
                runtime_state=runtime_state,
                current_user=current_user,
                conversation_id=local_session_id,
                delegated_write_operation_ids=runtime_allowed_write_operation_ids,
            )
            try:
                result = await asyncio.to_thread(session.ask, message)
            except Exception as exc:  # pragma: no cover - integration exercised
                await self._runtime.invalidate_runtime_session(runtime_state)
                raise HubAssistantUnavailableError(
                    f"swival Hub Assistant run failed: {exc}"
                ) from exc
            mcp_runtime_error = self._runtime.extract_mcp_runtime_error(result)
            if mcp_runtime_error is not None:
                await self._runtime.invalidate_runtime_session(runtime_state)
                raise HubAssistantUnavailableError(
                    f"swival Hub Assistant MCP call failed: {mcp_runtime_error}"
                )
            runtime_state.last_accessed_monotonic = time.monotonic()

        answer = cast(str | None, getattr(result, "answer", None))
        exhausted = bool(getattr(result, "exhausted", False))
        if not runtime_write_tools_enabled and self._answer_requests_write_approval(
            answer
        ):
            requested_write_operation_ids = self._extract_requested_write_operation_ids(
                answer
            )
            if not requested_write_operation_ids:
                await self._runtime.invalidate_runtime_session(runtime_state)
                raise HubAssistantUnavailableError(
                    "swival Hub Assistant requested write approval without "
                    "declaring any write operations"
                )
            interrupt = self._build_permission_interrupt(
                current_user=current_user,
                conversation_id=local_session_id,
                message=message,
                answer=answer,
                requested_write_operation_ids=requested_write_operation_ids,
            )
            return ExecutedHubAssistantRun(
                result=HubAssistantRunResult(
                    status=HubAssistantRunStatus.INTERRUPTED,
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
        if runtime_write_tools_enabled and self._answer_requests_write_approval(answer):
            requested_write_operation_ids = self._extract_requested_write_operation_ids(
                answer
            )
            if not requested_write_operation_ids:
                await self._runtime.invalidate_runtime_session(runtime_state)
                raise HubAssistantUnavailableError(
                    "swival Hub Assistant requested write approval without "
                    "declaring any write operations"
                )
            additional_requested_write_operation_ids = tuple(
                operation_id
                for operation_id in requested_write_operation_ids
                if operation_id not in runtime_allowed_write_operation_ids
            )
            if not additional_requested_write_operation_ids:
                await self._runtime.invalidate_runtime_session(runtime_state)
                raise HubAssistantUnavailableError(
                    "swival Hub Assistant requested write approval after write "
                    "tools were enabled"
                )
            interrupt = self._build_permission_interrupt(
                current_user=current_user,
                conversation_id=local_session_id,
                message=message,
                answer=answer,
                requested_write_operation_ids=additional_requested_write_operation_ids,
            )
            return ExecutedHubAssistantRun(
                result=HubAssistantRunResult(
                    status=HubAssistantRunStatus.INTERRUPTED,
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
        return ExecutedHubAssistantRun(
            result=HubAssistantRunResult(
                status=HubAssistantRunStatus.COMPLETED,
                answer=answer,
                exhausted=exhausted,
                runtime="swival",
                resources=profile.resources,
                tool_names=tuple(
                    definition.tool_name for definition in tool_definitions
                ),
                write_tools_enabled=runtime_write_tools_enabled,
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
        current_user: Any,
        request_id: str,
        reply: str,
        agent_message_id: UUID | None = None,
    ) -> HubAssistantRunResult:
        claims = verify_jwt_token_claims(
            request_id,
            expected_type=HUB_ASSISTANT_INTERRUPT_TOKEN_TYPE,
        )
        if claims is None:
            raise HubAssistantUnavailableError(
                "The write approval request is invalid or expired."
            )
        if claims.subject != str(current_user.id):
            raise HubAssistantUnavailableError(
                "The write approval request does not belong to the current user."
            )

        conversation_id = get_hub_assistant_interrupt_conversation_id(claims)
        if conversation_id is None:
            raise HubAssistantUnavailableError(
                "The write approval request is missing the conversation context."
            )
        interrupt_message = get_hub_assistant_interrupt_message(claims)
        if interrupt_message is None:
            raise HubAssistantUnavailableError(
                "The write approval request is missing the original prompt."
            )
        requested_operation_ids = get_hub_assistant_interrupt_requested_operations(
            claims
        )
        if not requested_operation_ids:
            raise HubAssistantUnavailableError(
                "The write approval request is missing the requested operations."
            )

        if reply == "reject":
            result = HubAssistantRunResult(
                status=HubAssistantRunStatus.COMPLETED,
                answer="Write approval was rejected. No changes were made.",
                exhausted=False,
                runtime="swival",
                resources=self.get_profile().resources,
                tool_names=tuple(get_hub_assistant_interrupt_tool_names(claims)),
                write_tools_enabled=False,
            )
            await self._persistence.persist_interrupt_resolution(
                db=db,
                current_user=current_user,
                conversation_id=conversation_id,
                request_id=request_id,
                resolution="rejected",
            )
            await self._persistence.persist_follow_up_agent_message(
                db=db,
                current_user=current_user,
                conversation_id=conversation_id,
                answer=result.answer,
                agent_message_id=agent_message_id,
                metadata={
                    "hub_assistant": True,
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

        runtime_state = await self._runtime.get_conversation_runtime_state(
            current_user_id=str(current_user.id),
            conversation_id=conversation_id,
        )
        async with runtime_state.get_lock():
            approved_operation_ids = (
                runtime_state.auto_approve_write_operation_ids
                | runtime_state.delegated_write_operation_ids
                | requested_operation_ids
            )
            if reply == "always":
                runtime_state.auto_approve_write_operation_ids = approved_operation_ids
            runtime_state.last_accessed_monotonic = time.monotonic()

        await self._persistence.persist_interrupt_resolution(
            db=db,
            current_user=current_user,
            conversation_id=conversation_id,
            request_id=request_id,
            resolution="replied",
        )
        continuation_agent_message_id = agent_message_id or uuid4()
        await self._persistence.persist_follow_up_agent_message(
            db=db,
            current_user=current_user,
            conversation_id=conversation_id,
            answer=None,
            agent_message_id=continuation_agent_message_id,
            metadata={
                "hub_assistant": True,
                "runtime": "swival",
                "reply_resolution": "replied",
                "interrupt_request_id": request_id,
                "tools": list(get_hub_assistant_interrupt_tool_names(claims)),
                "write_tools_enabled": True,
                "continuation_phase": "running",
            },
            status="streaming",
            finish_reason=None,
        )
        result = HubAssistantRunResult(
            status=HubAssistantRunStatus.ACCEPTED,
            answer=None,
            exhausted=False,
            runtime="swival",
            resources=self.get_profile().resources,
            tool_names=tuple(get_hub_assistant_interrupt_tool_names(claims)),
            write_tools_enabled=True,
            continuation=HubAssistantContinuation(
                phase="running",
                agent_message_id=continuation_agent_message_id,
            ),
        )
        await hub_assistant_task_service.enqueue_permission_reply_continuation(
            db=db,
            request=PermissionReplyContinuationTaskRequest(
                current_user_id=cast(Any, current_user.id),
                hub_assistant_conversation_id=conversation_id,
                message=interrupt_message,
                request_id=request_id,
                agent_message_id=continuation_agent_message_id,
                approved_operation_ids=frozenset(approved_operation_ids),
            ),
        )
        return result

    async def run_durable_follow_up(
        self,
        *,
        db: AsyncSession,
        current_user: Any,
        request: HubAssistantFollowUpTaskRequest,
        agent_message_id: UUID | None = None,
    ) -> HubAssistantRunResult:
        follow_up_agent_message_id = agent_message_id or uuid4()
        follow_up_message = self._build_follow_up_resume_message(request)
        try:
            executed = await self._execute_run(
                db=db,
                current_user=current_user,
                conversation_id=request.hub_assistant_conversation_id,
                message=follow_up_message,
                allow_write_tools=False,
            )
            await self._persistence.persist_follow_up_agent_message(
                db=db,
                current_user=current_user,
                conversation_id=request.hub_assistant_conversation_id,
                answer=executed.result.answer,
                agent_message_id=follow_up_agent_message_id,
                metadata={
                    "hub_assistant": True,
                    "runtime": executed.result.runtime,
                    "message_kind": "durable_follow_up_summary",
                    "follow_up_task_id": str(request.task_id),
                    "tracked_conversation_ids": list(request.tracked_conversation_ids),
                    "changed_conversation_ids": list(request.changed_conversation_ids),
                    "write_tools_enabled": executed.result.write_tools_enabled,
                    "tools": list(executed.result.tool_names),
                    "follow_up": {
                        "hub_assistant_conversation_id": request.hub_assistant_conversation_id,
                        "tracked_conversation_ids": list(
                            request.tracked_conversation_ids
                        ),
                        "changed_conversation_ids": list(
                            request.changed_conversation_ids
                        ),
                        "previous_target_agent_message_anchors": dict(
                            request.previous_target_agent_message_anchors
                        ),
                        "observed_target_agent_message_anchors": dict(
                            request.observed_target_agent_message_anchors
                        ),
                    },
                },
                status=(
                    "interrupted"
                    if executed.result.status == HubAssistantRunStatus.INTERRUPTED
                    else "done"
                ),
                finish_reason=(
                    "interrupt"
                    if executed.result.status == HubAssistantRunStatus.INTERRUPTED
                    else "completed"
                ),
            )
            if executed.result.interrupt is not None:
                await self._persistence.persist_permission_interrupt(
                    db=db,
                    current_user=current_user,
                    local_session_id=executed.local_session_id,
                    interrupt=executed.result.interrupt,
                )
            return executed.result
        except Exception as exc:
            await self._persistence.persist_follow_up_agent_message(
                db=db,
                current_user=current_user,
                conversation_id=request.hub_assistant_conversation_id,
                answer=str(exc),
                agent_message_id=follow_up_agent_message_id,
                metadata={
                    "hub_assistant": True,
                    "runtime": "swival",
                    "message_kind": "durable_follow_up_summary",
                    "follow_up_task_id": str(request.task_id),
                    "tracked_conversation_ids": list(request.tracked_conversation_ids),
                    "changed_conversation_ids": list(request.changed_conversation_ids),
                    "write_tools_enabled": False,
                    "tools": [],
                    "follow_up": {
                        "hub_assistant_conversation_id": request.hub_assistant_conversation_id,
                        "tracked_conversation_ids": list(
                            request.tracked_conversation_ids
                        ),
                        "changed_conversation_ids": list(
                            request.changed_conversation_ids
                        ),
                        "previous_target_agent_message_anchors": dict(
                            request.previous_target_agent_message_anchors
                        ),
                        "observed_target_agent_message_anchors": dict(
                            request.observed_target_agent_message_anchors
                        ),
                    },
                    "follow_up_phase": "failed",
                },
                status="error",
                finish_reason="failed",
            )
            raise

    async def run_permission_reply_continuation(
        self,
        *,
        db: AsyncSession,
        current_user: Any,
        request: PermissionReplyContinuationTaskRequest,
    ) -> None:
        extra = {
            "user_id": str(request.current_user_id),
            "conversation_id": request.hub_assistant_conversation_id,
            "request_id": request.request_id,
            "agent_message_id": str(request.agent_message_id),
        }
        try:
            executed = await self._execute_run(
                db=db,
                current_user=current_user,
                conversation_id=request.hub_assistant_conversation_id,
                message=request.message,
                allow_write_tools=True,
                approved_write_operation_ids=request.approved_operation_ids,
            )
            await self._persistence.persist_follow_up_agent_message(
                db=db,
                current_user=current_user,
                conversation_id=request.hub_assistant_conversation_id,
                answer=executed.result.answer,
                agent_message_id=request.agent_message_id,
                metadata={
                    "hub_assistant": True,
                    "runtime": executed.result.runtime,
                    "reply_resolution": "replied",
                    "interrupt_request_id": request.request_id,
                    "tools": list(executed.result.tool_names),
                    "write_tools_enabled": executed.result.write_tools_enabled,
                    "continuation_phase": (
                        "interrupted"
                        if executed.result.status == HubAssistantRunStatus.INTERRUPTED
                        else "completed"
                    ),
                },
                status=(
                    "interrupted"
                    if executed.result.status == HubAssistantRunStatus.INTERRUPTED
                    else "done"
                ),
                finish_reason=(
                    "interrupt"
                    if executed.result.status == HubAssistantRunStatus.INTERRUPTED
                    else "completed"
                ),
            )
            if executed.result.interrupt is not None:
                await self._persistence.persist_permission_interrupt(
                    db=db,
                    current_user=current_user,
                    local_session_id=executed.local_session_id,
                    interrupt=executed.result.interrupt,
                )
            await commit_safely(db)
        except Exception as exc:
            logger.exception(
                "Hub Assistant Hub Assistant continuation failed", extra=extra
            )
            await self._persistence.persist_follow_up_agent_message(
                db=db,
                current_user=current_user,
                conversation_id=request.hub_assistant_conversation_id,
                answer=str(exc),
                agent_message_id=request.agent_message_id,
                metadata={
                    "hub_assistant": True,
                    "runtime": "swival",
                    "reply_resolution": "replied",
                    "interrupt_request_id": request.request_id,
                    "tools": [],
                    "write_tools_enabled": True,
                    "continuation_phase": "failed",
                },
                status="error",
                finish_reason="failed",
            )
            await commit_safely(db)
            raise

    def _build_follow_up_resume_message(
        self,
        request: HubAssistantFollowUpTaskRequest,
    ) -> str:
        return FOLLOW_UP_RESUME_MESSAGE_TEMPLATE.format(
            tracked_conversation_ids=", ".join(request.tracked_conversation_ids)
            or "(none)",
            changed_conversation_ids=", ".join(request.changed_conversation_ids)
            or "(none)",
            previous_target_agent_message_anchors=dict(
                request.previous_target_agent_message_anchors
            ),
            previous_target_agent_message_ids={
                conversation_id: anchor.get("message_id")
                for conversation_id, anchor in request.previous_target_agent_message_anchors.items()
                if anchor.get("message_id")
            },
            observed_target_agent_message_anchors=dict(
                request.observed_target_agent_message_anchors
            ),
        )

    def _answer_requests_write_approval(self, answer: str | None) -> bool:
        return self._runtime.answer_requests_write_approval(answer)

    def _strip_write_approval_metadata(self, answer: str | None) -> str | None:
        return self._runtime.strip_write_approval_metadata(answer)

    def _list_write_tool_definitions(
        self,
    ) -> tuple[HubAssistantToolDefinition, ...]:
        return self._runtime.list_write_tool_definitions()

    def _extract_requested_write_operation_ids(
        self, answer: str | None
    ) -> tuple[str, ...]:
        return self._runtime.extract_requested_write_operation_ids(answer)

    def _build_permission_interrupt(
        self,
        *,
        current_user: Any,
        conversation_id: str,
        message: str,
        answer: str | None,
        requested_write_operation_ids: tuple[str, ...],
    ) -> HubAssistantPermissionInterrupt:
        return self._runtime.build_permission_interrupt(
            current_user=current_user,
            conversation_id=conversation_id,
            message=message,
            answer=answer,
            requested_write_operation_ids=requested_write_operation_ids,
        )

    def _select_run_tool_definitions(
        self,
        *,
        allow_write_tools: bool,
        delegated_write_operation_ids: frozenset[str] = frozenset(),
    ) -> tuple[HubAssistantToolDefinition, ...]:
        return self._runtime.select_run_tool_definitions(
            allow_write_tools=allow_write_tools,
            delegated_write_operation_ids=delegated_write_operation_ids,
        )

    def _load_swival_session_cls(self) -> type[Any]:
        return self._runtime.load_swival_session_cls()

    def _resolve_swival_base_dir(self, current_user: Any) -> str:
        return self._runtime.resolve_swival_base_dir(current_user)

    def _is_swival_importable(self) -> bool:
        return self._runtime.is_swival_importable()


hub_assistant_service = HubAssistantService()
