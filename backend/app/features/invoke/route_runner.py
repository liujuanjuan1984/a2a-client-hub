"""Shared invoke flow runner for personal/hub A2A route handlers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable, Literal
from uuid import UUID

from fastapi import HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.error_codes import status_code_for_invoke_error_code
from app.api.error_handlers import build_error_detail, build_error_response
from app.api.retry_after import db_busy_retry_after_headers
from app.db.locking import (
    RetryableDbLockError,
    RetryableDbQueryTimeoutError,
)
from app.db.session import AsyncSessionLocal
from app.db.transaction import commit_safely, prepare_for_external_call
from app.features.invoke import guard as invoke_guard
from app.features.invoke import route_runner_streaming
from app.features.invoke import session_binding as invoke_session_binding
from app.features.invoke.guard import (
    build_invoke_guard_key,
    guard_inflight_invoke,
    release_invoke_guard,
    try_acquire_invoke_guard,
)
from app.features.invoke.recovery import (
    InvokeMetadataBindingRequiredError,
    build_rebound_invoke_payload,
    finalize_outbound_invoke_payload,
    resolve_session_binding_outbound_mode,
    validate_provider_aware_continue_session,
)
from app.features.invoke.route_runner_session_control import (
    build_session_control_error_response,
    build_session_control_response,
    run_append_session_control,
)
from app.features.invoke.route_runner_state import (
    AgentSource,
    InvokeState,
    find_latest_agent_message_id,
    normalize_optional_message_id,
    prepare_state,
    register_inflight_invoke,
)
from app.features.invoke.service import (
    StreamOutcome,
    a2a_invoke_service,
)
from app.features.invoke.stream_persistence import (
    InvokePersistenceRequest,
    coerce_uuid,
)
from app.features.invoke.stream_persistence import (
    ensure_local_message_headers as ensure_local_message_headers_impl,
)
from app.features.invoke.stream_persistence import (
    flush_stream_buffer as flush_stream_buffer_impl,
)
from app.features.invoke.stream_persistence import (
    is_interrupt_requested,
)
from app.features.invoke.stream_persistence import (
    persist_interrupt_lifecycle_event as persist_interrupt_lifecycle_event_impl,
)
from app.features.invoke.stream_persistence import (
    persist_local_outcome as persist_local_outcome_impl,
)
from app.features.invoke.stream_persistence import (
    persist_stream_block_update as persist_stream_block_update_impl,
)
from app.features.invoke.stream_persistence import (
    persist_synthetic_final_block_if_needed as persist_synthetic_final_block_if_needed_impl,
)
from app.features.sessions.common import serialize_interrupt_event_block_content
from app.features.sessions.service import session_hub_service
from app.integrations.a2a_extensions.service import get_a2a_extensions_service
from app.runtime.ws_ticket import ws_ticket_service
from app.schemas.a2a_invoke import (
    A2AAgentInvokeRequest,
    A2AAgentInvokeResponse,
)
from app.schemas.ws_ticket import WsTicketResponse
from app.utils.async_cleanup import await_cancel_safe, await_cancel_safe_suppressed

_invoke_inflight_keys = invoke_guard._invoke_inflight_keys
_InvokeState = InvokeState
_prepare_state = prepare_state
_register_inflight_invoke = register_inflight_invoke
_validate_provider_aware_continue_session = validate_provider_aware_continue_session
_finalize_outbound_invoke_payload_impl = finalize_outbound_invoke_payload
_is_interrupt_requested = is_interrupt_requested
_diagnose_stream_hints_contract_gap = (
    route_runner_streaming.diagnose_stream_hints_contract_gap
)

_SESSION_NOT_FOUND_RETRY_LIMIT = 1
_SESSION_NOT_FOUND_RECOVERY_EXHAUSTED_MESSAGE = (
    "Failed to recover conversation session. Please retry."
)


async def _close_open_transaction(db: AsyncSession) -> None:
    await prepare_for_external_call(db)


async def _continue_session_with_short_transaction(
    *,
    user_id: UUID,
    conversation_id: str,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as short_db:
        continue_binding, db_mutated = await session_hub_service.continue_session(
            short_db,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if db_mutated:
            await commit_safely(short_db)
        else:
            await _close_open_transaction(short_db)
        return continue_binding


async def _recover_rebound_invoke_payload(
    *,
    runtime: Any,
    user_id: UUID,
    payload: A2AAgentInvokeRequest,
    logger: Any,
    log_extra: dict[str, Any],
) -> A2AAgentInvokeRequest | None:
    if not isinstance(payload.conversation_id, str):
        return None

    continue_binding = await _continue_session_with_short_transaction(
        user_id=user_id,
        conversation_id=payload.conversation_id,
    )
    validation_result = await _validate_provider_aware_continue_session(
        runtime=runtime,
        continue_payload=continue_binding,
        logger=logger,
        log_extra=log_extra,
    )
    if validation_result == "failed":
        return None

    return build_rebound_invoke_payload(
        payload=payload,
        continue_payload=continue_binding,
    )


async def _find_latest_agent_message_id(
    *,
    user_id: UUID,
    conversation_id: UUID,
) -> str | None:
    return await find_latest_agent_message_id(
        user_id=user_id,
        conversation_id=conversation_id,
    )


async def _record_preempt_history_event(
    *,
    state: InvokeState,
    user_id: UUID,
    event: dict[str, Any],
) -> None:
    if state.local_session_id is None:
        return
    async with AsyncSessionLocal() as db:
        await session_hub_service.record_preempt_event_by_local_session_id(
            db,
            local_session_id=state.local_session_id,
            user_id=user_id,
            event=event,
        )
        await commit_safely(db)


async def _preempt_previous_invoke_if_requested(
    *,
    state: InvokeState,
    payload: A2AAgentInvokeRequest,
    user_id: UUID,
) -> None:
    if state.local_session_id is None:
        return
    if not is_interrupt_requested(payload):
        return
    target_message_id = await _find_latest_agent_message_id(
        user_id=user_id,
        conversation_id=state.local_session_id,
    )
    pending_event = {
        "reason": "invoke_interrupt",
        "source": "user",
        "target_message_id": target_message_id,
        "replacement_user_message_id": state.user_message_id,
        "replacement_agent_message_id": state.agent_message_id,
    }
    report = await session_hub_service.preempt_inflight_invoke_report(
        user_id=user_id,
        conversation_id=state.local_session_id,
        reason="invoke_interrupt",
        pending_event=pending_event,
    )
    if not report.attempted:
        return

    event = {
        **pending_event,
        "status": report.status,
        "target_task_ids": report.target_task_ids,
        "failed_error_codes": report.failed_error_codes,
    }
    await _record_preempt_history_event(
        state=state,
        user_id=user_id,
        event=event,
    )
    if report.status == "failed":
        raise ValueError("invoke_interrupt_failed")


async def _bind_inflight_task_if_needed(
    *,
    state: InvokeState,
    user_id: UUID,
) -> None:
    if state.local_session_id is None or state.inflight_token is None:
        return
    raw_task_id = (
        state.stream_identity.get("upstream_task_id")
        if isinstance(state.stream_identity, dict)
        else None
    )
    normalized_task_id = raw_task_id.strip() if isinstance(raw_task_id, str) else None
    if not normalized_task_id or normalized_task_id == state.upstream_task_id:
        return
    bind_report = await session_hub_service.bind_inflight_task_id_report(
        user_id=user_id,
        conversation_id=state.local_session_id,
        token=state.inflight_token,
        task_id=normalized_task_id,
    )
    if bind_report.bound:
        state.upstream_task_id = normalized_task_id
    if bind_report.preempt_event is not None:
        await _record_preempt_history_event(
            state=state,
            user_id=user_id,
            event=bind_report.preempt_event,
        )


async def _unregister_inflight_invoke(
    *,
    state: InvokeState,
    user_id: UUID,
) -> None:
    if state.local_session_id is None or state.inflight_token is None:
        return
    await session_hub_service.unregister_inflight_invoke(
        user_id=user_id,
        conversation_id=state.local_session_id,
        token=state.inflight_token,
    )
    state.inflight_token = None


async def _resolve_session_binding_outbound_mode(
    *,
    runtime: Any,
    logger: Any,
    log_extra: dict[str, Any],
) -> bool:
    return await resolve_session_binding_outbound_mode(
        runtime=runtime,
        logger=logger,
        log_extra=log_extra,
        extensions_service_getter=get_a2a_extensions_service,
    )


async def _try_acquire_invoke_guard(guard_key: str) -> bool:
    return await try_acquire_invoke_guard(guard_key)


async def _release_invoke_guard(guard_key: str) -> None:
    await release_invoke_guard(guard_key)


async def _finalize_outbound_invoke_payload(
    *,
    payload: A2AAgentInvokeRequest,
    runtime: Any,
    logger: Any,
    log_extra: dict[str, Any],
) -> A2AAgentInvokeRequest:
    return await _finalize_outbound_invoke_payload_impl(
        payload=payload,
        runtime=runtime,
        logger=logger,
        log_extra=log_extra,
        resolve_outbound_mode=_resolve_session_binding_outbound_mode,
    )


def _build_invoke_metadata_error_response(
    *,
    runtime: Any,
    exc: InvokeMetadataBindingRequiredError,
) -> A2AAgentInvokeResponse:
    return A2AAgentInvokeResponse(
        success=False,
        content=None,
        error=str(exc),
        error_code="invoke_metadata_not_bound",
        source="hub_invoke_metadata",
        jsonrpc_code=None,
        missing_params=list(exc.missing_params) or None,
        upstream_error=exc.upstream_error,
        agent_name=getattr(runtime.resolved, "name", None),
        agent_url=getattr(runtime.resolved, "url", None),
    )


def _normalize_optional_message_id(value: str | None) -> str | None:
    return normalize_optional_message_id(value)


def _build_stream_hints_runtime_meta_from_card(
    *,
    runtime: Any,
    card: Any,
    logger: Any,
    log_extra: dict[str, Any],
) -> dict[str, Any]:
    return route_runner_streaming.build_stream_hints_runtime_meta_from_card(
        runtime=runtime,
        card=card,
        logger=logger,
        log_extra=log_extra,
    )


async def _ensure_local_message_headers(
    *,
    state: InvokeState,
    request: InvokePersistenceRequest,
) -> None:
    await ensure_local_message_headers_impl(
        state=state,
        request=request,
        session_factory=AsyncSessionLocal,
        commit_fn=commit_safely,
        session_hub=session_hub_service,
    )


async def _flush_stream_buffer(
    *,
    state: InvokeState,
    user_id: UUID,
) -> None:
    await flush_stream_buffer_impl(
        state=state,
        user_id=user_id,
        session_factory=AsyncSessionLocal,
        commit_fn=commit_safely,
        session_hub=session_hub_service,
    )


async def _persist_stream_block_update(
    *,
    state: InvokeState,
    event_payload: dict[str, Any],
    request: InvokePersistenceRequest,
) -> None:
    async def _ensure_headers_adapter(**kwargs: Any) -> None:
        await _ensure_local_message_headers(
            state=kwargs["state"],
            request=kwargs["request"],
        )

    async def _flush_buffer_adapter(**kwargs: Any) -> None:
        await _flush_stream_buffer(
            state=kwargs["state"],
            user_id=kwargs["user_id"],
        )

    await persist_stream_block_update_impl(
        state=state,
        event_payload=event_payload,
        request=request,
        stream_service=a2a_invoke_service,
        session_factory=AsyncSessionLocal,
        commit_fn=commit_safely,
        session_hub=session_hub_service,
        ensure_headers_fn=_ensure_headers_adapter,
        flush_buffer_fn=_flush_buffer_adapter,
    )


async def _persist_interrupt_lifecycle_event(
    *,
    state: InvokeState,
    event_payload: dict[str, Any],
    request: InvokePersistenceRequest,
) -> None:
    async def _ensure_headers_adapter(**kwargs: Any) -> None:
        await _ensure_local_message_headers(
            state=kwargs["state"],
            request=kwargs["request"],
        )

    async def _flush_buffer_adapter(**kwargs: Any) -> None:
        await _flush_stream_buffer(
            state=kwargs["state"],
            user_id=kwargs["user_id"],
        )

    await persist_interrupt_lifecycle_event_impl(
        state=state,
        event_payload=event_payload,
        request=request,
        stream_service=a2a_invoke_service,
        build_interrupt_message_content=serialize_interrupt_event_block_content,
        session_factory=AsyncSessionLocal,
        commit_fn=commit_safely,
        session_hub=session_hub_service,
        ensure_headers_fn=_ensure_headers_adapter,
        flush_buffer_fn=_flush_buffer_adapter,
    )


async def _persist_synthetic_final_block_if_needed(
    *,
    state: InvokeState,
    outcome: StreamOutcome,
    user_id: UUID,
) -> None:
    await persist_synthetic_final_block_if_needed_impl(
        state=state,
        outcome=outcome,
        user_id=user_id,
        session_factory=AsyncSessionLocal,
        commit_fn=commit_safely,
        session_hub=session_hub_service,
    )


async def _persist_local_outcome(
    *,
    state: InvokeState,
    outcome: StreamOutcome,
    request: InvokePersistenceRequest,
    response_metadata: dict[str, Any] | None = None,
) -> None:
    async def _ensure_headers_adapter(**kwargs: Any) -> None:
        await _ensure_local_message_headers(
            state=kwargs["state"],
            request=kwargs["request"],
        )

    async def _persist_final_block_adapter(**kwargs: Any) -> None:
        await _persist_synthetic_final_block_if_needed(
            state=kwargs["state"],
            outcome=kwargs["outcome"],
            user_id=kwargs["user_id"],
        )

    await persist_local_outcome_impl(
        state=state,
        outcome=outcome,
        request=request,
        response_metadata=response_metadata,
        session_factory=AsyncSessionLocal,
        commit_fn=commit_safely,
        session_hub=session_hub_service,
        ensure_headers_fn=_ensure_headers_adapter,
        persist_final_block_fn=_persist_final_block_adapter,
    )


def _build_consume_stream_callbacks(
    *,
    state: InvokeState,
    request: InvokePersistenceRequest,
    logger: Any = None,
    log_extra: dict[str, Any] | None = None,
) -> tuple[
    Callable[[dict[str, Any]], Any],
    Callable[[StreamOutcome], Any],
]:
    resolved_log_extra = log_extra if log_extra is not None else {}

    async def on_event(event_payload: dict[str, Any]) -> None:
        route_runner_streaming.diagnose_stream_hints_contract_gap(
            state=state,
            event_payload=event_payload,
            logger=logger,
            log_extra=resolved_log_extra,
        )
        route_runner_streaming.collect_stream_hints(
            state=state, event_payload=event_payload
        )
        await _bind_inflight_task_if_needed(state=state, user_id=request.user_id)
        await _persist_stream_block_update(
            state=state,
            event_payload=event_payload,
            request=request,
        )
        await _persist_interrupt_lifecycle_event(
            state=state,
            event_payload=event_payload,
            request=request,
        )

    async def on_finalized(outcome: StreamOutcome) -> dict[str, Any] | None:
        try:
            await _flush_stream_buffer(state=state, user_id=request.user_id)
            await _persist_local_outcome(
                state=state,
                outcome=outcome,
                request=request,
            )
            return route_runner_streaming.build_persisted_finalization_ack_event(
                state=state,
                outcome=outcome,
            )
        finally:
            await _unregister_inflight_invoke(state=state, user_id=request.user_id)

    return on_event, on_finalized


async def _run_preempt_session_control(
    *,
    runtime: Any,
    payload: A2AAgentInvokeRequest,
    user_id: UUID,
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

    target_message_id = await _find_latest_agent_message_id(
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
    async with AsyncSessionLocal() as db:
        await session_hub_service.record_preempt_event_by_local_session_id(
            db,
            local_session_id=local_session_id,
            user_id=user_id,
            event=event,
        )
        await commit_safely(db)
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


async def run_http_invoke_with_session_recovery(
    *,
    gateway: Any,
    runtime: Any,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
    stream: bool,
    validate_message: Callable[[dict[str, Any]], list[Any]],
    logger: Any,
    log_extra: dict[str, Any],
    max_recovery_attempts: int = _SESSION_NOT_FOUND_RETRY_LIMIT,
) -> A2AAgentInvokeResponse | StreamingResponse:
    current_payload = payload
    remaining_retries = max_recovery_attempts

    while True:
        response = await run_http_invoke(
            gateway=gateway,
            runtime=runtime,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            payload=current_payload,
            stream=stream,
            validate_message=validate_message,
            logger=logger,
            log_extra=log_extra,
        )
        if isinstance(response, StreamingResponse):
            return response
        if response.success:
            return response
        if not invoke_session_binding.is_recoverable_invoke_session_error(
            response.error_code
        ):
            return response
        if remaining_retries <= 0:
            return response

        remaining_retries -= 1
        try:
            rebound_payload = await _recover_rebound_invoke_payload(
                runtime=runtime,
                user_id=user_id,
                payload=current_payload,
                logger=logger,
                log_extra=log_extra,
            )
        except ValueError:
            return response
        if rebound_payload is None:
            return response
        current_payload = rebound_payload


async def run_http_invoke(
    *,
    gateway: Any,
    runtime: Any,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
    stream: bool,
    validate_message: Callable[[dict[str, Any]], list[Any]],
    logger: Any,
    log_extra: dict[str, Any],
) -> A2AAgentInvokeResponse | StreamingResponse:
    try:
        payload = await _finalize_outbound_invoke_payload(
            payload=payload,
            runtime=runtime,
            logger=logger,
            log_extra=log_extra,
        )
    except InvokeMetadataBindingRequiredError as exc:
        return _build_invoke_metadata_error_response(runtime=runtime, exc=exc)
    if (
        invoke_session_binding.resolve_invoke_session_control_intent(payload)
        == "append"
    ):
        return await run_append_session_control(runtime=runtime, payload=payload)
    if (
        invoke_session_binding.resolve_invoke_session_control_intent(payload)
        == "preempt"
        and not payload.query.strip()
    ):
        return await _run_preempt_session_control(
            runtime=runtime,
            payload=payload,
            user_id=user_id,
        )
    state = await _prepare_state(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )
    stream_log_extra = dict(log_extra)
    on_session_started = (
        route_runner_streaming.build_stream_hints_session_started_callback(
            runtime=runtime,
            state=state,
            logger=logger,
            log_extra=log_extra,
            stream_log_extra=stream_log_extra,
        )
    )
    await _preempt_previous_invoke_if_requested(
        state=state,
        payload=payload,
        user_id=user_id,
    )
    await _register_inflight_invoke(
        state=state,
        user_id=user_id,
        gateway=gateway,
        resolved=runtime.resolved,
    )
    persistence_request = route_runner_streaming.build_invoke_persistence_request(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        query=payload.query,
        transport="http_sse" if stream else "http_json",
        stream_enabled=stream,
    )

    if stream:
        on_event, on_finalized = _build_consume_stream_callbacks(
            state=state,
            request=persistence_request,
            logger=logger,
            log_extra=stream_log_extra,
        )
        try:
            return a2a_invoke_service.stream_sse(
                gateway=gateway,
                resolved=runtime.resolved,
                query=payload.query,
                context_id=state.context_id,
                metadata=payload.metadata,
                validate_message=validate_message,
                logger=logger,
                log_extra=stream_log_extra,
                on_event=on_event,
                on_finalized=on_finalized,
                on_session_started=on_session_started,
                resume_from_sequence=payload.resume_from_sequence,
                cache_key=state.user_message_id,
            )
        except Exception:
            await _unregister_inflight_invoke(state=state, user_id=user_id)
            raise

    on_event, on_finalized = _build_consume_stream_callbacks(
        state=state,
        request=persistence_request,
        logger=logger,
        log_extra=stream_log_extra,
    )
    try:
        outcome = await a2a_invoke_service.consume_stream(
            gateway=gateway,
            resolved=runtime.resolved,
            query=payload.query,
            context_id=state.context_id,
            metadata=payload.metadata,
            validate_message=validate_message,
            logger=logger,
            log_extra=stream_log_extra,
            on_event=on_event,
            on_finalized=on_finalized,
            on_session_started=on_session_started,
        )
    except Exception:
        await _unregister_inflight_invoke(state=state, user_id=user_id)
        raise
    success = bool(outcome.success)
    content = state.persisted_response_content
    if content is None:
        content = outcome.final_text
    error = None if success else (outcome.error_message or content)
    error_code = (
        state.persisted_error_code
        if not success and state.persisted_error_code
        else outcome.error_code
    )
    return A2AAgentInvokeResponse(
        success=success,
        content=content,
        error=error,
        error_code=error_code,
        source=outcome.source,
        jsonrpc_code=outcome.jsonrpc_code,
        missing_params=list(outcome.missing_params or []) or None,
        upstream_error=outcome.upstream_error,
        agent_name=runtime.resolved.name,
        agent_url=runtime.resolved.url,
    )


async def run_background_invoke(
    *,
    gateway: Any,
    invoke_session: Any | None = None,
    runtime: Any,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
    validate_message: Callable[[dict[str, Any]], list[Any]],
    logger: Any,
    log_extra: dict[str, Any],
    user_sender: Literal["user", "automation"] = "user",
    extra_persisted_metadata: dict[str, Any] | None = None,
    total_timeout_seconds: float | None = None,
    idle_timeout_seconds: float | None = None,
) -> dict[str, Any]:
    try:
        payload = await _finalize_outbound_invoke_payload(
            payload=payload,
            runtime=runtime,
            logger=logger,
            log_extra=log_extra,
        )
    except InvokeMetadataBindingRequiredError as exc:
        response = _build_invoke_metadata_error_response(runtime=runtime, exc=exc)
        return {
            "success": False,
            "response_content": "",
            "error": response.error,
            "error_code": response.error_code,
            "source": response.source,
            "jsonrpc_code": response.jsonrpc_code,
            "missing_params": response.missing_params,
            "upstream_error": response.upstream_error,
            "internal_error_message": None,
            "conversation_id": payload.conversation_id,
            "message_refs": {},
            "context_id": None,
        }
    state = await _prepare_state(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )
    stream_log_extra = dict(log_extra)
    on_session_started = (
        route_runner_streaming.build_stream_hints_session_started_callback(
            runtime=runtime,
            state=state,
            logger=logger,
            log_extra=log_extra,
            stream_log_extra=stream_log_extra,
        )
    )
    await _preempt_previous_invoke_if_requested(
        state=state,
        payload=payload,
        user_id=user_id,
    )
    await _register_inflight_invoke(
        state=state,
        user_id=user_id,
        gateway=gateway,
        resolved=runtime.resolved,
    )
    persistence_request = route_runner_streaming.build_invoke_persistence_request(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        query=payload.query,
        transport="scheduled",
        stream_enabled=True,
        user_sender=user_sender,
        extra_persisted_metadata=extra_persisted_metadata,
    )

    on_event, on_finalized = _build_consume_stream_callbacks(
        state=state,
        request=persistence_request,
        logger=logger,
        log_extra=stream_log_extra,
    )
    try:
        outcome = await a2a_invoke_service.consume_stream(
            gateway=gateway,
            invoke_session=invoke_session,
            resolved=runtime.resolved,
            query=payload.query,
            context_id=state.context_id,
            metadata=payload.metadata,
            validate_message=validate_message,
            logger=logger,
            log_extra=stream_log_extra,
            on_event=on_event,
            on_finalized=on_finalized,
            on_session_started=on_session_started,
            total_timeout_seconds=total_timeout_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
        )
    except Exception:
        await _unregister_inflight_invoke(state=state, user_id=user_id)
        raise
    success = bool(outcome.success)
    response_content = state.persisted_response_content
    if response_content is None:
        fallback_value = outcome.final_text or outcome.error_message
        response_content = str(fallback_value or "")
    return {
        "success": success,
        "response_content": response_content,
        "error": outcome.error_message,
        "error_code": state.persisted_error_code or outcome.error_code,
        "source": outcome.source,
        "jsonrpc_code": outcome.jsonrpc_code,
        "missing_params": list(outcome.missing_params or []) or None,
        "upstream_error": outcome.upstream_error,
        "internal_error_message": outcome.internal_error_message,
        "conversation_id": (
            state.message_refs.get("conversation_id") if state.message_refs else None
        ),
        "message_refs": dict(state.message_refs) if state.message_refs else {},
        "context_id": state.context_id,
    }


async def run_ws_invoke(
    *,
    websocket: WebSocket,
    gateway: Any,
    runtime: Any,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
    validate_message: Callable[[dict[str, Any]], list[Any]],
    logger: Any,
    log_extra: dict[str, Any],
    on_error_metadata: Callable[[dict[str, Any]], Any] | None = None,
    send_stream_end: bool = True,
) -> None:
    try:
        payload = await _finalize_outbound_invoke_payload(
            payload=payload,
            runtime=runtime,
            logger=logger,
            log_extra=log_extra,
        )
    except InvokeMetadataBindingRequiredError as exc:
        response = _build_invoke_metadata_error_response(runtime=runtime, exc=exc)
        error_payload = {
            "message": response.error or "Invoke failed",
            "error_code": response.error_code,
            "source": response.source,
            "missing_params": response.missing_params,
            "upstream_error": response.upstream_error,
        }
        await a2a_invoke_service.send_ws_error(
            websocket=websocket,
            message=response.error or "Invoke failed",
            error_code=response.error_code,
            source=response.source,
            jsonrpc_code=None,
            missing_params=response.missing_params,
            upstream_error=response.upstream_error,
        )
        if on_error_metadata is not None:
            await a2a_invoke_service._call_callback(on_error_metadata, error_payload)
        if send_stream_end:
            await a2a_invoke_service.send_ws_stream_end(websocket)
        return
    state = await _prepare_state(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )
    stream_log_extra = dict(log_extra)
    on_session_started = (
        route_runner_streaming.build_stream_hints_session_started_callback(
            runtime=runtime,
            state=state,
            logger=logger,
            log_extra=log_extra,
            stream_log_extra=stream_log_extra,
        )
    )
    await _preempt_previous_invoke_if_requested(
        state=state,
        payload=payload,
        user_id=user_id,
    )
    await _register_inflight_invoke(
        state=state,
        user_id=user_id,
        gateway=gateway,
        resolved=runtime.resolved,
    )
    persistence_request = route_runner_streaming.build_invoke_persistence_request(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        query=payload.query,
        transport="ws",
        stream_enabled=True,
    )
    on_event, on_finalized = _build_consume_stream_callbacks(
        state=state,
        request=persistence_request,
        logger=logger,
        log_extra=stream_log_extra,
    )
    try:
        await a2a_invoke_service.stream_ws(
            websocket=websocket,
            gateway=gateway,
            resolved=runtime.resolved,
            query=payload.query,
            context_id=state.context_id,
            metadata=payload.metadata,
            validate_message=validate_message,
            logger=logger,
            log_extra=stream_log_extra,
            on_event=on_event,
            on_error_metadata=on_error_metadata,
            on_finalized=on_finalized,
            on_session_started=on_session_started,
            send_stream_end=send_stream_end,
            resume_from_sequence=payload.resume_from_sequence,
            cache_key=state.user_message_id,
        )
    except Exception:
        await _unregister_inflight_invoke(state=state, user_id=user_id)
        raise


async def run_ws_invoke_with_session_recovery(
    *,
    websocket: WebSocket,
    gateway: Any,
    runtime: Any,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
    validate_message: Callable[[dict[str, Any]], list[Any]],
    logger: Any,
    log_extra: dict[str, Any],
    max_recovery_attempts: int = _SESSION_NOT_FOUND_RETRY_LIMIT,
) -> None:
    current_payload = payload
    remaining_retries = max_recovery_attempts
    while True:
        stream_error_code: str | None = None
        stream_error_message: str | None = None

        def _remember_stream_error(error_event: dict[str, Any]) -> None:
            nonlocal stream_error_code
            nonlocal stream_error_message
            raw_code = error_event.get("error_code")
            if isinstance(raw_code, str):
                stream_error_code = raw_code.strip() or None
            raw_message = error_event.get("message")
            if isinstance(raw_message, str):
                stream_error_message = raw_message

        async def _send_recovery_failed_error() -> None:
            await a2a_invoke_service.send_ws_error(
                websocket=websocket,
                message=stream_error_message
                or _SESSION_NOT_FOUND_RECOVERY_EXHAUSTED_MESSAGE,
                error_code=invoke_session_binding.ws_error_code_for_recovery_failed(
                    stream_error_code or ""
                ),
            )

        await run_ws_invoke(
            websocket=websocket,
            gateway=gateway,
            runtime=runtime,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            payload=current_payload,
            validate_message=validate_message,
            logger=logger,
            log_extra=log_extra,
            on_error_metadata=_remember_stream_error,
            send_stream_end=False,
        )
        if stream_error_code is None:
            await a2a_invoke_service.send_ws_stream_end(websocket)
            return

        if not invoke_session_binding.is_recoverable_invoke_session_error(
            stream_error_code
        ):
            await a2a_invoke_service.send_ws_stream_end(websocket)
            return
        if remaining_retries <= 0:
            await _send_recovery_failed_error()
            await a2a_invoke_service.send_ws_stream_end(websocket)
            return

        remaining_retries -= 1
        try:
            rebound_payload = await _recover_rebound_invoke_payload(
                runtime=runtime,
                user_id=user_id,
                payload=current_payload,
                logger=logger,
                log_extra=log_extra,
            )
        except ValueError:
            await a2a_invoke_service.send_ws_stream_end(websocket)
            return
        if rebound_payload is None:
            await _send_recovery_failed_error()
            await a2a_invoke_service.send_ws_stream_end(websocket)
            return
        current_payload = rebound_payload


async def run_ws_invoke_route(
    *,
    websocket: WebSocket,
    db: AsyncSession,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    gateway: Any,
    runtime_builder: Callable[[], Awaitable[Any]],
    runtime_not_found_errors: tuple[type[Exception], ...],
    runtime_not_found_message: str | Callable[[Exception], str],
    runtime_not_found_code: str,
    runtime_validation_errors: tuple[type[Exception], ...],
    validate_message: Callable[[dict[str, Any]], list[Any]],
    logger: Any,
    invoke_log_message: str,
    invoke_log_extra_builder: Callable[[A2AAgentInvokeRequest, Any], dict[str, Any]],
    unexpected_log_message: str,
) -> None:
    selected_subprotocol = getattr(websocket.state, "selected_subprotocol", None)
    if selected_subprotocol:
        await websocket.accept(subprotocol=selected_subprotocol)
    else:
        await websocket.accept()

    try:
        data = await websocket.receive_json()
        try:
            payload = A2AAgentInvokeRequest.model_validate(data)
        except ValidationError:
            await a2a_invoke_service.send_ws_error(
                websocket,
                message="Invalid request payload",
                error_code="invalid_request",
            )
            await await_cancel_safe(
                websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
            )
            return

        if not payload.query.strip():
            await a2a_invoke_service.send_ws_error(
                websocket,
                message="Query must be a non-empty string",
                error_code="invalid_query",
            )
            await await_cancel_safe(
                websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
            )
            return

        try:
            runtime = await runtime_builder()
        except runtime_not_found_errors as exc:
            message = (
                runtime_not_found_message(exc)
                if callable(runtime_not_found_message)
                else runtime_not_found_message
            )
            await a2a_invoke_service.send_ws_error(
                websocket,
                message=message,
                error_code=runtime_not_found_code,
            )
            await await_cancel_safe(
                websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            )
            return
        except runtime_validation_errors as exc:
            await a2a_invoke_service.send_ws_error(
                websocket,
                message=str(exc),
                error_code="runtime_invalid",
            )
            await await_cancel_safe(websocket.close(code=status.WS_1011_INTERNAL_ERROR))
            return
        await _close_open_transaction(db)

        logger.info(
            invoke_log_message,
            extra=invoke_log_extra_builder(payload, runtime),
        )
        guard_key = build_invoke_guard_key(
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            payload=payload,
        )

        try:
            async with guard_inflight_invoke(guard_key):
                await run_ws_invoke_with_session_recovery(
                    websocket=websocket,
                    gateway=gateway,
                    runtime=runtime,
                    user_id=user_id,
                    agent_id=agent_id,
                    agent_source=agent_source,
                    payload=payload,
                    validate_message=validate_message,
                    logger=logger,
                    log_extra={
                        "user_id": str(user_id),
                        "agent_id": str(agent_id),
                    },
                    max_recovery_attempts=_SESSION_NOT_FOUND_RETRY_LIMIT,
                )
        except ValueError as exc:
            await a2a_invoke_service.send_ws_error(
                websocket,
                message=str(exc),
                error_code=invoke_session_binding.ws_error_code_for_invoke_session_error(
                    str(exc)
                ),
            )
            await await_cancel_safe(
                websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            )
            return

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected", extra={"user_id": str(user_id)})
    except Exception:
        logger.error(unexpected_log_message, exc_info=True)
        try:
            await a2a_invoke_service.send_ws_error(
                websocket,
                message="Upstream streaming failed",
                error_code="upstream_stream_error",
            )
        except Exception:
            pass
    finally:
        try:
            await await_cancel_safe_suppressed(websocket.close())
        except Exception:
            pass


async def run_http_invoke_route(
    *,
    db: AsyncSession,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
    stream: bool,
    gateway: Any,
    runtime_builder: Callable[[], Awaitable[Any]],
    runtime_not_found_errors: tuple[type[Exception], ...],
    runtime_not_found_status_code: int,
    runtime_validation_errors: tuple[type[Exception], ...],
    runtime_validation_status_code: int,
    runtime_validation_status_overrides: (
        tuple[tuple[type[Exception], int], ...] | None
    ) = None,
    validate_message: Callable[[dict[str, Any]], list[Any]],
    logger: Any,
    invoke_log_message: str,
    invoke_log_extra_builder: Callable[[A2AAgentInvokeRequest, Any], dict[str, Any]],
) -> A2AAgentInvokeResponse | StreamingResponse | JSONResponse:
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="Query must be a non-empty string")

    try:
        runtime = await runtime_builder()
    except runtime_not_found_errors as exc:
        raise HTTPException(
            status_code=runtime_not_found_status_code,
            detail=str(exc),
        ) from exc
    except runtime_validation_errors as exc:
        status_code = runtime_validation_status_code
        if runtime_validation_status_overrides:
            for error_type, override in runtime_validation_status_overrides:
                if isinstance(exc, error_type):
                    status_code = override
                    break
        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        ) from exc
    await _close_open_transaction(db)

    logger.info(
        invoke_log_message,
        extra=invoke_log_extra_builder(payload, runtime),
    )
    guard_key = build_invoke_guard_key(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )

    if stream and guard_key:
        acquired = await _try_acquire_invoke_guard(guard_key)
        if not acquired:
            raise HTTPException(
                status_code=invoke_session_binding.status_code_for_invoke_session_error(
                    "invoke_inflight"
                ),
                detail="invoke_inflight",
            )
        try:
            response = await run_http_invoke_with_session_recovery(
                gateway=gateway,
                runtime=runtime,
                user_id=user_id,
                agent_id=agent_id,
                agent_source=agent_source,
                payload=payload,
                stream=stream,
                validate_message=validate_message,
                logger=logger,
                log_extra={
                    "user_id": str(user_id),
                    "agent_id": str(agent_id),
                },
                max_recovery_attempts=_SESSION_NOT_FOUND_RETRY_LIMIT,
            )
        except ValueError as exc:
            await _release_invoke_guard(guard_key)
            raise HTTPException(
                status_code=invoke_session_binding.status_code_for_invoke_session_error(
                    str(exc)
                ),
                detail=str(exc),
            ) from exc
        except Exception:
            await _release_invoke_guard(guard_key)
            raise

        if isinstance(response, StreamingResponse):
            original_iterator = response.body_iterator

            async def guarded_iterator() -> AsyncIterator[Any]:
                try:
                    async for chunk in original_iterator:
                        yield chunk
                finally:
                    await _release_invoke_guard(guard_key)

            response.body_iterator = guarded_iterator()
            return response

        if not response.success:
            await _release_invoke_guard(guard_key)
            return build_error_response(
                status_code=status_code_for_invoke_error_code(response.error_code),
                detail=build_error_detail(
                    message=response.error or "Invoke failed",
                    error_code=response.error_code,
                    source=response.source,
                    jsonrpc_code=response.jsonrpc_code,
                    missing_params=response.missing_params,
                    upstream_error=response.upstream_error,
                ),
            )
        await _release_invoke_guard(guard_key)
        return response

    try:
        async with guard_inflight_invoke(guard_key):
            response = await run_http_invoke_with_session_recovery(
                gateway=gateway,
                runtime=runtime,
                user_id=user_id,
                agent_id=agent_id,
                agent_source=agent_source,
                payload=payload,
                stream=stream,
                validate_message=validate_message,
                logger=logger,
                log_extra={
                    "user_id": str(user_id),
                    "agent_id": str(agent_id),
                },
                max_recovery_attempts=_SESSION_NOT_FOUND_RETRY_LIMIT,
            )

            if isinstance(response, StreamingResponse):
                return response

            if response.success:
                return response
            return build_error_response(
                status_code=status_code_for_invoke_error_code(response.error_code),
                detail=build_error_detail(
                    message=response.error or "Invoke failed",
                    error_code=response.error_code,
                    source=response.source,
                    jsonrpc_code=response.jsonrpc_code,
                    missing_params=response.missing_params,
                    upstream_error=response.upstream_error,
                ),
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=invoke_session_binding.status_code_for_invoke_session_error(
                str(exc)
            ),
            detail=str(exc),
        ) from exc


async def run_issue_ws_ticket_route(
    *,
    db: AsyncSession,
    user_id: UUID,
    scope_type: str,
    scope_id: UUID,
    ensure_access: Callable[[], Awaitable[Any]],
    not_found_errors: tuple[type[Exception], ...],
    not_found_status_code: int,
    not_found_detail: str | Callable[[Exception], str],
) -> WsTicketResponse:
    try:
        await ensure_access()
    except not_found_errors as exc:
        detail = (
            not_found_detail(exc) if callable(not_found_detail) else not_found_detail
        )
        raise HTTPException(status_code=not_found_status_code, detail=detail) from exc

    try:
        issued = await ws_ticket_service.issue_ticket(
            db,
            user_id=user_id,
            scope_type=scope_type,
            scope_id=scope_id,
        )
    except RetryableDbLockError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except RetryableDbQueryTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers=db_busy_retry_after_headers(),
        ) from exc
    return WsTicketResponse(
        token=issued.token,
        expires_at=issued.expires_at,
        expires_in=issued.expires_in,
    )
