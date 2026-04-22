"""Invoke route-runner session-control helpers."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal, cast
from uuid import UUID, uuid4

from app.db.session import AsyncSessionLocal
from app.db.transaction import commit_safely
from app.features.invoke.route_runner_state import (
    find_latest_agent_message_id,
    normalize_optional_message_id,
)
from app.features.invoke.session_binding import (
    resolve_invoke_session_binding_hint,
)
from app.features.invoke.stream_persistence import coerce_uuid
from app.features.sessions.service import session_hub_service
from app.integrations.a2a_extensions.service import get_a2a_extensions_service
from app.schemas.a2a_invoke import (
    A2AAgentInvokeRequest,
    A2AAgentInvokeResponse,
    A2AAgentInvokeSessionControlResult,
)
from app.utils.session_identity import normalize_non_empty_text

_APPEND_UNAVAILABLE_EXTENSION_ERROR_CODES = frozenset(
    {
        "method_not_supported",
        "method_disabled",
        "not_supported",
        "turn_not_steerable",
    }
)


def build_session_control_response(
    *,
    intent: Literal["append", "preempt"],
    status: Literal["accepted", "completed", "no_inflight", "unavailable", "failed"],
    session_id: str | None = None,
) -> A2AAgentInvokeSessionControlResult:
    return A2AAgentInvokeSessionControlResult(
        intent=intent,
        status=status,
        sessionId=session_id,
    )


def build_session_control_error_response(
    *,
    intent: Literal["append", "preempt"],
    message: str,
    error_code: str,
    runtime: Any,
    source: str = "hub_session_control",
    jsonrpc_code: int | None = None,
    missing_params: list[dict[str, Any]] | None = None,
    upstream_error: dict[str, Any] | None = None,
) -> A2AAgentInvokeResponse:
    resolved_status: Literal["unavailable", "failed"] = (
        "unavailable"
        if error_code in {"append_requires_bound_session", "append_unavailable"}
        else "failed"
    )
    return A2AAgentInvokeResponse(
        success=False,
        content=None,
        error=message,
        error_code=error_code,
        source=source,
        jsonrpc_code=jsonrpc_code,
        missing_params=missing_params,
        upstream_error=upstream_error,
        agent_name=getattr(runtime.resolved, "name", None),
        agent_url=getattr(runtime.resolved, "url", None),
        sessionControl=build_session_control_response(
            intent=intent,
            status=resolved_status,
        ),
    )


def build_append_request_payload(payload: A2AAgentInvokeRequest) -> dict[str, Any]:
    return {
        "parts": [{"type": "text", "text": payload.query.strip()}],
        "messageID": normalize_optional_message_id(payload.user_message_id)
        or str(uuid4()),
    }


def resolve_append_session_id(payload: A2AAgentInvokeRequest) -> str | None:
    _provider, external_session_id = resolve_invoke_session_binding_hint(
        session_binding=payload.session_binding,
        metadata=payload.metadata,
    )
    return external_session_id


async def run_append_session_control(
    *,
    runtime: Any,
    payload: A2AAgentInvokeRequest,
) -> A2AAgentInvokeResponse:
    session_id = resolve_append_session_id(payload)
    if not session_id:
        return build_session_control_error_response(
            intent="append",
            message="Append requires a bound upstream session.",
            error_code="append_requires_bound_session",
            runtime=runtime,
        )

    result = await get_a2a_extensions_service().append_session_control(
        runtime=runtime,
        session_id=session_id,
        request_payload=build_append_request_payload(payload),
        metadata=payload.metadata,
        working_directory=payload.working_directory,
    )
    if not result.success:
        mapped_error_code = (
            "append_unavailable"
            if result.error_code in _APPEND_UNAVAILABLE_EXTENSION_ERROR_CODES
            else result.error_code or "upstream_error"
        )
        message = (
            "Append is unavailable for the current session."
            if mapped_error_code == "append_unavailable"
            else "Append failed."
        )
        return build_session_control_error_response(
            intent="append",
            message=message,
            error_code=mapped_error_code,
            runtime=runtime,
            source=result.source or "hub_session_control",
            jsonrpc_code=result.jsonrpc_code,
            missing_params=result.missing_params,
            upstream_error=result.upstream_error,
        )

    response_payload = result.result if isinstance(result.result, dict) else {}
    if response_payload.get("ok") is not True:
        return build_session_control_error_response(
            intent="append",
            message="Append acknowledged without ok=true.",
            error_code="upstream_payload_error",
            runtime=runtime,
            source=result.source or "hub_session_control",
            jsonrpc_code=result.jsonrpc_code,
            missing_params=result.missing_params,
            upstream_error=result.upstream_error,
        )

    resolved_session_id = (
        normalize_non_empty_text(cast(str | None, response_payload.get("session_id")))
        or session_id
    )
    return A2AAgentInvokeResponse(
        success=True,
        content=None,
        error=None,
        error_code=None,
        source="hub_session_control",
        jsonrpc_code=None,
        missing_params=None,
        upstream_error=None,
        agent_name=getattr(runtime.resolved, "name", None),
        agent_url=getattr(runtime.resolved, "url", None),
        sessionControl=build_session_control_response(
            intent="append",
            status="accepted",
            session_id=resolved_session_id,
        ),
    )


async def run_preempt_session_control(
    *,
    runtime: Any,
    payload: A2AAgentInvokeRequest,
    user_id: UUID,
    find_latest_agent_message_id_fn: Callable[..., Awaitable[str | None]] = (
        find_latest_agent_message_id
    ),
    session_factory: Callable[[], Any] = AsyncSessionLocal,
    commit_fn: Callable[[Any], Awaitable[None]] = commit_safely,
) -> A2AAgentInvokeResponse:
    local_session_id = coerce_uuid(payload.conversation_id)
    if local_session_id is None:
        return A2AAgentInvokeResponse(
            success=True,
            content=None,
            error=None,
            error_code=None,
            source="hub_session_control",
            jsonrpc_code=None,
            missing_params=None,
            upstream_error=None,
            agent_name=getattr(runtime.resolved, "name", None),
            agent_url=getattr(runtime.resolved, "url", None),
            sessionControl=build_session_control_response(
                intent="preempt",
                status="no_inflight",
            ),
        )

    target_message_id = await find_latest_agent_message_id_fn(
        user_id=user_id,
        conversation_id=local_session_id,
    )
    pending_event = {
        "reason": "invoke_interrupt",
        "source": "user",
        "target_message_id": target_message_id,
    }
    report = await session_hub_service.preempt_inflight_invoke_report(
        user_id=user_id,
        conversation_id=local_session_id,
        reason="invoke_interrupt",
        pending_event=pending_event,
    )
    if not report.attempted:
        return A2AAgentInvokeResponse(
            success=True,
            content=None,
            error=None,
            error_code=None,
            source="hub_session_control",
            jsonrpc_code=None,
            missing_params=None,
            upstream_error=None,
            agent_name=getattr(runtime.resolved, "name", None),
            agent_url=getattr(runtime.resolved, "url", None),
            sessionControl=build_session_control_response(
                intent="preempt",
                status="no_inflight",
            ),
        )

    event = {
        **pending_event,
        "status": report.status,
        "target_task_ids": report.target_task_ids,
        "failed_error_codes": report.failed_error_codes,
    }
    async with session_factory() as db:
        await session_hub_service.record_preempt_event_by_local_session_id(
            db,
            local_session_id=local_session_id,
            user_id=user_id,
            event=event,
        )
        await commit_fn(db)
    if report.status == "failed":
        return build_session_control_error_response(
            intent="preempt",
            message="Interrupt failed.",
            error_code="invoke_interrupt_failed",
            runtime=runtime,
        )

    resolved_status: Literal["accepted", "completed"] = (
        "completed" if report.status == "completed" else "accepted"
    )
    return A2AAgentInvokeResponse(
        success=True,
        content=None,
        error=None,
        error_code=None,
        source="hub_session_control",
        jsonrpc_code=None,
        missing_params=None,
        upstream_error=None,
        agent_name=getattr(runtime.resolved, "name", None),
        agent_url=getattr(runtime.resolved, "url", None),
        sessionControl=build_session_control_response(
            intent="preempt",
            status=resolved_status,
        ),
    )
