"""Tool execution orchestration helpers for AgentService."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.service_types import (
    AgentRuntimeContext,
    AgentStreamEvent,
    ExecutableToolCall,
)
from app.agents.tools.planner import ToolExecutionBatch
from app.agents.tools.responses import ToolResult, create_tool_error
from app.cardbox.service import cardbox_service
from app.core.logging import get_logger, log_exception
from app.db.models.agent_session import AgentSession
from app.handlers import agent_message as agent_message_service
from app.handlers import agent_session as session_handler
from app.handlers.agent_session import SessionHandlerError
from app.services.agent_audit_logger import agent_audit_logger
from app.services.note_reference_service import (
    NOTE_TOOL_NAMES,
    NoteReferenceResolutionError,
    note_reference_service,
)
from app.utils.json_encoder import json_dumps
from app.utils.timezone_util import utc_now_iso

logger = get_logger(__name__)


class ToolExecutionEngine:
    """Prepares, executes, and persists tool runs."""

    def __init__(self, *, tool_policy, audit_logger=agent_audit_logger) -> None:
        self._tool_policy = tool_policy
        self._audit_logger = audit_logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def build_tool_call_message(assistant_message: Any) -> Dict[str, Any]:
        tool_calls_payload = []
        for tool_call in getattr(assistant_message, "tool_calls", []) or []:
            tool_calls_payload.append(
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
            )

        return {
            "role": "assistant",
            "content": getattr(assistant_message, "content", "") or "",
            "tool_calls": tool_calls_payload,
        }

    async def execute_tool_batch(
        self,
        *,
        batch: ToolExecutionBatch,
        tool_registry,
        note_reference_lookup: Optional[Dict[str, Any]],
        runtime: AgentRuntimeContext,
        messages: List[Dict[str, Any]],
        tool_failures: List[Dict[str, str]],
    ) -> List[AgentStreamEvent]:
        db = runtime.db
        user_id = runtime.user_id
        message_id = runtime.message_id
        log_context = runtime.log_context
        cardbox_session = runtime.cardbox_session

        events: List[AgentStreamEvent] = []
        executables: List[ExecutableToolCall] = []
        pending_audits: List[Dict[str, Any]] = []

        for prepared_call in batch.calls:
            executable, prep_events = await self._prepare_tool_call_execution(
                prepared_call=prepared_call,
                note_reference_lookup=note_reference_lookup,
                messages=messages,
                tool_failures=tool_failures,
                cardbox_session=cardbox_session,
                db=db,
                user_id=user_id,
                message_id=message_id,
                log_context=log_context,
            )
            events.extend(prep_events)
            if executable is not None:
                executables.append(executable)

        try:
            for executable in executables:
                tool_result = await self._invoke_tool_call(
                    executable=executable,
                    tool_registry=tool_registry,
                    log_context=log_context,
                )
                events.extend(
                    await self._finalise_tool_execution(
                        executable=executable,
                        tool_result=tool_result,
                        messages=messages,
                        tool_failures=tool_failures,
                        cardbox_session=cardbox_session,
                        db=db,
                        user_id=user_id,
                        message_id=message_id,
                        log_context=log_context,
                        runtime=runtime,
                        audit_queue=pending_audits,
                    )
                )
        finally:
            if pending_audits:
                try:
                    await self._audit_logger.bulk_log_tool_runs(db, pending_audits)
                except Exception:  # pragma: no cover - defensive logging
                    logger.exception(
                        "Failed to persist agent audit batch",
                        extra=runtime.logging_extra(action="agent.audit.batch_failed"),
                    )

        return events

    async def handle_invalid_tool_call(
        self,
        *,
        tool_call: Any,
        run_record: Dict[str, Any],
        reason: str,
        error_kind: str,
        messages: List[Dict[str, Any]],
        tool_failures: List[Dict[str, str]],
        runtime: AgentRuntimeContext,
    ) -> AgentStreamEvent:
        tool_name = run_record.get("tool_name") or "invalid_tool"
        logger.warning(
            "Skipping invalid tool call",
            extra=runtime.logging_extra(
                action="agent.tool.invalid_call", tool_name=tool_name, reason=reason
            ),
        )
        tool_failures.append({"tool": tool_name, "reason": reason})
        run_record["status"] = "failed"
        run_record["message"] = reason
        self._complete_tool_run(run_record)

        error_result = create_tool_error(
            message=f"Tool invocation failed: {reason}",
            kind=error_kind,
            detail=reason,
        )
        success_flag, tool_content, _ = self._parse_tool_result(error_result)
        card_id = self._sync_tool_result_to_cardbox(
            session=runtime.cardbox_session,
            user_id=runtime.user_id,
            tool_name=tool_name,
            tool_call_id=tool_call.id,
            arguments=run_record.get("arguments"),
            result=tool_content,
            message_id=runtime.message_id,
            success=success_flag,
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_content,
            }
        )
        await self._persist_tool_message(
            runtime.db,
            session=runtime.cardbox_session,
            user_id=runtime.user_id,
            content=tool_content,
            tool_name=tool_name,
            tool_call_id=tool_call.id,
            run_record=run_record,
            arguments=run_record.get("arguments"),
            cardbox_card_id=card_id,
        )

        return AgentStreamEvent(
            event="tool_failed",
            data=self._build_tool_event_payload(run_record, error=reason),
        )

    def build_tool_event_payload(
        self,
        run_record: Dict[str, Any],
        *,
        include_arguments: bool = False,
        **extra: Any,
    ) -> Dict[str, Any]:
        return self._build_tool_event_payload(
            run_record, include_arguments=include_arguments, **extra
        )

    async def resolve_session_for_cardbox(
        self,
        db: AsyncSession,
        *,
        session_id_value: Optional[Any],
        user_id: UUID,
        session_was_provided: bool,
    ) -> Optional[AgentSession]:
        if not session_was_provided:
            return None

        session_uuid = self._coerce_uuid(session_id_value)
        if session_uuid is None:
            return None

        try:
            session = await session_handler.get_session(
                db,
                session_id=session_uuid,
                user_id=user_id,
            )
        except SessionHandlerError as exc:
            log_exception(
                logger,
                f"Failed to load session {session_id_value} for Cardbox sync: {exc}",
                None,
            )
            return None

        if session is None:
            logger.warning(
                "Skipping Cardbox tool sync: session %s not found for user %s",
                session_uuid,
                user_id,
            )
            return None

        try:
            cardbox_service.ensure_session_box(session)
        except Exception as exc:
            log_exception(
                logger,
                f"Failed to ensure Cardbox for session {session_uuid}: {exc}",
                None,
            )
            return None

        return session

    def create_tool_run_record(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        sequence: int,
        run_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        started_at = self._now_iso()
        return {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "status": "started",
            "message": None,
            "arguments": arguments,
            "sequence": sequence,
            "started_at": started_at,
            "finished_at": None,
            "duration_ms": None,
            "progress": None,
            "_started_ts": time.perf_counter(),
            "run_id": run_id or uuid4(),
        }

    @staticmethod
    def sanitize_tool_runs(tool_runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {k: v for k, v in run.items() if not k.startswith("_")} for run in tool_runs
        ]

    @staticmethod
    def compose_tool_failure_message(failures: List[Dict[str, str]]) -> str:
        lines = [
            "The following tool executions failed. Please adjust the parameters and try again:",
        ]
        for item in failures:
            tool_name = item.get("tool", "unknown")
            reason = item.get("reason") or "unknown error"
            lines.append(f"- {tool_name}: {reason}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _prepare_tool_call_execution(
        self,
        *,
        prepared_call,
        note_reference_lookup: Optional[Dict[str, Any]],
        messages: List[Dict[str, Any]],
        tool_failures: List[Dict[str, str]],
        cardbox_session,
        db: AsyncSession,
        user_id: UUID,
        message_id: UUID,
        log_context: Dict[str, Any],
    ) -> Tuple[Optional[ExecutableToolCall], List[AgentStreamEvent]]:
        events: List[AgentStreamEvent] = []
        function_args = dict(prepared_call.arguments)
        run_record = prepared_call.run_record
        tool_name = prepared_call.name

        if note_reference_lookup is not None and tool_name in NOTE_TOOL_NAMES:
            try:
                resolved = note_reference_service.resolve_tool_arguments(
                    tool_name, function_args, note_reference_lookup
                )
                function_args = resolved
                run_record["arguments"] = function_args
            except NoteReferenceResolutionError as resolution_error:
                run_record["status"] = "failed"
                resolution_payload = create_tool_error(
                    message="Unable to resolve the specified tag/contact/task",
                    kind="validation_error",
                    detail=json_dumps(
                        resolution_error.detail,
                        ensure_ascii=False,
                    ),
                )
                success_flag, tool_content, payload = self._parse_tool_result(
                    resolution_payload
                )
                card_id = self._sync_tool_result_to_cardbox(
                    session=cardbox_session,
                    user_id=user_id,
                    tool_name=tool_name,
                    tool_call_id=prepared_call.tool_call.id,
                    arguments=function_args,
                    result=tool_content,
                    message_id=message_id,
                    success=success_flag,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": prepared_call.tool_call.id,
                        "content": tool_content,
                    }
                )
                reason_text = self._extract_tool_failure_reason(payload, tool_content)
                run_record["message"] = reason_text
                self._complete_tool_run(run_record)
                await self._persist_tool_message(
                    db,
                    session=cardbox_session,
                    user_id=user_id,
                    content=tool_content,
                    tool_name=tool_name,
                    tool_call_id=prepared_call.tool_call.id,
                    run_record=run_record,
                    arguments=function_args,
                    cardbox_card_id=card_id,
                )
                tool_failures.append({"tool": tool_name, "reason": reason_text})
                events.append(
                    AgentStreamEvent(
                        event="tool_failed",
                        data=self._build_tool_event_payload(
                            run_record, error=reason_text
                        ),
                    )
                )
                return None, events

        allowed, reason = self._tool_policy.should_execute(
            tool_name, prepared_call.call_index, prepared_call.metadata
        )
        if not allowed:
            logger.warning(
                "Tool execution blocked by policy",
                extra={
                    **log_context,
                    "action": "agent.tool.blocked",
                    "tool_name": tool_name,
                    "reason": reason,
                },
            )
            run_record["status"] = "failed"
            run_record["message"] = reason or "policy_blocked"
            policy_error = create_tool_error(
                message=f"Tool '{tool_name}' call blocked by policy",
                kind=reason or "policy_blocked",
            )
            success_flag, tool_content, payload = self._parse_tool_result(policy_error)
            card_id = self._sync_tool_result_to_cardbox(
                session=cardbox_session,
                user_id=user_id,
                tool_name=tool_name,
                tool_call_id=prepared_call.tool_call.id,
                arguments=function_args,
                result=tool_content,
                message_id=message_id,
                success=False,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": prepared_call.tool_call.id,
                    "content": tool_content,
                }
            )
            reason_text = self._extract_tool_failure_reason(payload, tool_content)
            run_record["message"] = reason_text
            self._complete_tool_run(run_record)
            await self._persist_tool_message(
                db,
                session=cardbox_session,
                user_id=user_id,
                content=tool_content,
                tool_name=tool_name,
                tool_call_id=prepared_call.tool_call.id,
                run_record=run_record,
                arguments=function_args,
                cardbox_card_id=card_id,
            )
            tool_failures.append({"tool": tool_name, "reason": reason_text})
            events.append(
                AgentStreamEvent(
                    event="tool_failed",
                    data=self._build_tool_event_payload(run_record, error=reason_text),
                )
            )
            return None, events

        executable = ExecutableToolCall(prepared=prepared_call, arguments=function_args)
        return executable, events

    async def _invoke_tool_call(
        self,
        *,
        executable: ExecutableToolCall,
        tool_registry,
        log_context: Dict[str, Any],
    ) -> ToolResult:
        tool_name = executable.prepared.name
        function_args = executable.arguments

        logger.info("Executing tool '%s' with args: %s", tool_name, function_args)

        self._tool_policy.register_start(tool_name)
        try:
            result = await tool_registry.execute_tool(
                tool_name=tool_name,
                metadata_override=executable.prepared.metadata,
                **function_args,
            )
        except Exception as exc:  # pragma: no cover - defensive branch
            log_exception(
                logger,
                f"Tool {tool_name} execution raised exception: {exc}",
                None,
            )
            self._tool_policy.register_finish(tool_name, success=False)
            return create_tool_error(
                message=f"Tool '{tool_name}' execution failed",
                kind="tool_error",
                detail=str(exc),
            )
        else:
            self._tool_policy.register_finish(tool_name, success=result.is_success)
            return result

    async def _finalise_tool_execution(
        self,
        *,
        executable: ExecutableToolCall,
        tool_result: ToolResult,
        messages: List[Dict[str, Any]],
        tool_failures: List[Dict[str, str]],
        cardbox_session,
        db: AsyncSession,
        user_id: UUID,
        message_id: UUID,
        log_context: Dict[str, Any],
        runtime: AgentRuntimeContext,
        audit_queue: List[Dict[str, Any]],
    ) -> List[AgentStreamEvent]:
        events: List[AgentStreamEvent] = []
        run_record = executable.prepared.run_record
        tool_call = executable.prepared.tool_call
        tool_name = executable.prepared.name
        function_args = executable.arguments

        success_flag, tool_content, payload = self._parse_tool_result(tool_result)
        audit_payload = (
            tool_result.audit if isinstance(tool_result.audit, dict) else None
        )
        metadata = executable.prepared.metadata
        error_message: Optional[str] = None
        card_id = self._sync_tool_result_to_cardbox(
            session=cardbox_session,
            user_id=user_id,
            tool_name=tool_name,
            tool_call_id=tool_call.id,
            arguments=function_args,
            result=tool_content,
            message_id=message_id,
            success=success_flag,
        )
        logger.info(
            "Tool result synced to Cardbox",
            extra={
                **log_context,
                "action": "agent.cardbox.tool_sync",
                "tool_name": tool_name,
                "tool_call_id": tool_call.id,
                "cardbox_card_id": str(card_id) if card_id else None,
                "success": success_flag,
            },
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_content,
            }
        )

        if success_flag:
            run_record["status"] = "finished"
            run_record["message"] = self._summarise_tool_output(tool_content)
            self._complete_tool_run(run_record)
            await self._persist_tool_message(
                db,
                session=cardbox_session,
                user_id=user_id,
                content=tool_content,
                tool_name=tool_name,
                tool_call_id=tool_call.id,
                run_record=run_record,
                arguments=function_args,
                cardbox_card_id=card_id,
            )
            events.append(
                AgentStreamEvent(
                    event="tool_finished",
                    data=self._build_tool_event_payload(
                        run_record, result=run_record["message"]
                    ),
                )
            )
        else:
            reason = self._extract_tool_failure_reason(payload, tool_content)
            run_record["status"] = "failed"
            run_record["message"] = reason
            self._complete_tool_run(run_record)
            error_message = reason
            await self._persist_tool_message(
                db,
                session=cardbox_session,
                user_id=user_id,
                content=tool_content,
                tool_name=tool_name,
                tool_call_id=tool_call.id,
                run_record=run_record,
                arguments=function_args,
                cardbox_card_id=card_id,
            )
            tool_failures.append({"tool": tool_name, "reason": reason})
            events.append(
                AgentStreamEvent(
                    event="tool_failed",
                    data=self._build_tool_event_payload(run_record, error=reason),
                )
            )

        self._maybe_record_agent_audit(
            runtime=runtime,
            tool_name=tool_name,
            tool_call_id=tool_call.id,
            run_record=run_record,
            function_args=function_args,
            audit_payload=audit_payload,
            metadata=metadata,
            error_message=error_message,
            audit_queue=audit_queue,
        )

        return events

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sync_tool_result_to_cardbox(
        *,
        session: Optional[AgentSession],
        user_id: UUID,
        tool_name: str,
        tool_call_id: str,
        arguments: Dict[str, Any],
        result: Any,
        message_id: Optional[Any],
        success: bool,
    ) -> Optional[str]:
        if session is None:
            return None

        return cardbox_service.record_tool_result(
            session=session,
            user_id=user_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            result=result,
            arguments=arguments,
            message_id=str(message_id) if message_id else None,
            success=success,
        )

    @staticmethod
    def _parse_tool_result(
        result: ToolResult,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        payload = result.to_payload()
        text = result.to_content()
        return result.is_success, text, payload

    @staticmethod
    def _extract_tool_failure_reason(
        payload: Optional[Dict[str, Any]], fallback: str
    ) -> str:
        if payload:
            return payload.get("detail") or payload.get("message") or fallback
        return fallback

    @staticmethod
    def _summarise_tool_output(content: str, max_length: int = 200) -> str:
        if content is None:
            return ""
        if len(content) <= max_length:
            return content
        return content[:max_length] + "…"

    @staticmethod
    def _complete_tool_run(run_record: Dict[str, Any]) -> None:
        if not run_record.get("finished_at"):
            run_record["finished_at"] = utc_now_iso()

        start_ts = run_record.get("_started_ts")
        if start_ts is not None and run_record.get("duration_ms") is None:
            elapsed_ms = int(max((time.perf_counter() - start_ts) * 1000, 0))
            run_record["duration_ms"] = elapsed_ms
        run_record.pop("_started_ts", None)

    @staticmethod
    def _build_tool_event_payload(
        run_record: Dict[str, Any],
        *,
        include_arguments: bool = False,
        **extra: Any,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "tool_call_id": run_record.get("tool_call_id"),
            "tool_name": run_record.get("tool_name"),
            "sequence": run_record.get("sequence"),
            "status": run_record.get("status"),
            "started_at": run_record.get("started_at"),
        }
        if include_arguments and run_record.get("arguments") is not None:
            payload["arguments"] = run_record.get("arguments")
        if run_record.get("finished_at"):
            payload["finished_at"] = run_record.get("finished_at")
        if run_record.get("duration_ms") is not None:
            payload["duration_ms"] = run_record.get("duration_ms")
        if run_record.get("message"):
            payload["message"] = run_record.get("message")
        if run_record.get("progress"):
            payload["progress"] = run_record.get("progress")
        payload.update(extra)
        return payload

    @staticmethod
    async def _persist_tool_message(
        db: AsyncSession,
        *,
        session: Optional[AgentSession],
        user_id: UUID,
        content: str,
        tool_name: str,
        tool_call_id: str,
        run_record: Dict[str, Any],
        arguments: Optional[Dict[str, Any]],
        cardbox_card_id: Optional[str],
    ) -> Optional[Any]:
        if session is None:
            return None

        metadata = {
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "status": run_record.get("status"),
            "sequence": run_record.get("sequence"),
            "arguments": arguments,
            "started_at": run_record.get("started_at"),
            "finished_at": run_record.get("finished_at"),
            "duration_ms": run_record.get("duration_ms"),
            "progress": run_record.get("progress"),
            "summary": run_record.get("message"),
            "success": run_record.get("status") == "finished",
            "cardbox_card_id": cardbox_card_id,
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}

        try:
            return await agent_message_service.create_agent_message(
                db,
                user_id=user_id,
                content=content,
                sender="agent",
                session=session,
                sync_to_cardbox=False,
                message_type="tool",
                metadata=metadata,
                cardbox_card_id=cardbox_card_id,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger,
                f"Failed to persist tool message: {exc}",
                None,
            )
            return None

    def _maybe_record_agent_audit(
        self,
        *,
        runtime: AgentRuntimeContext,
        tool_name: str,
        tool_call_id: str,
        run_record: Dict[str, Any],
        function_args: Dict[str, Any],
        audit_payload: Optional[Dict[str, Any]],
        metadata,
        error_message: Optional[str],
        audit_queue: List[Dict[str, Any]],
    ) -> None:
        if metadata.read_only:
            return

        audit_payload = audit_payload or {}
        target_entities = (
            audit_payload.get("target_entities") or audit_payload.get("targets") or None
        )
        before_snapshot = audit_payload.get("before") or audit_payload.get(
            "before_snapshot"
        )
        after_snapshot = audit_payload.get("after") or audit_payload.get(
            "after_snapshot"
        )
        operation = audit_payload.get("operation")
        extra_payload = audit_payload.get("extra") or {}
        if "arguments" not in extra_payload:
            merged_extra = dict(extra_payload)
            merged_extra["arguments"] = function_args
        else:
            merged_extra = extra_payload

        entry_payload = {
            "run_id": run_record.get("run_id"),
            "trigger_user_id": runtime.user_id,
            "agent_name": runtime.agent_name,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "session_id": runtime.session_id,
            "message_id": runtime.message_id,
            "status": run_record.get("status", "finished"),
            "duration_ms": run_record.get("duration_ms"),
            "operation": operation or tool_name,
            "target_entities": target_entities,
            "before_snapshot": before_snapshot,
            "after_snapshot": after_snapshot,
            "error": error_message,
            "extra": merged_extra,
        }
        entry_payload["run_id"] = self._coerce_uuid(entry_payload["run_id"]) or uuid4()
        audit_queue.append(entry_payload)

    @staticmethod
    def normalize_tool_name(candidate: Any) -> str:
        if isinstance(candidate, str):
            return candidate.strip()
        return ""

    @staticmethod
    def _coerce_uuid(value: Any) -> Optional[UUID]:
        if value is None:
            return None
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _now_iso() -> str:
        return utc_now_iso()


__all__ = ["ToolExecutionEngine"]
