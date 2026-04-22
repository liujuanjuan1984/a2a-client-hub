"""Shared invoke flow runner for personal/hub A2A route handlers."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal
from uuid import UUID

from fastapi import WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.db.transaction import commit_safely, prepare_for_external_call
from app.features.invoke import guard as invoke_guard
from app.features.invoke import (
    route_runner_routes,
    route_runner_streaming,
    route_runner_ws_ticket,
)
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
    run_append_session_control,
    run_preempt_session_control,
)
from app.features.invoke.route_runner_state import (
    AgentSource,
    InvokeState,
    bind_inflight_task_if_needed,
    find_latest_agent_message_id,
    preempt_previous_invoke_if_requested,
    prepare_state,
    record_preempt_history_event,
    register_inflight_invoke,
    unregister_inflight_invoke,
)
from app.features.invoke.service import (
    StreamOutcome,
    a2a_invoke_service,
)
from app.features.invoke.stream_persistence import (
    InvokePersistenceRequest,
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
from app.features.working_directory import adapt_working_directory_metadata_for_upstream
from app.integrations.a2a_extensions.service import get_a2a_extensions_service
from app.runtime.ws_ticket import ws_ticket_service
from app.schemas.a2a_invoke import (
    A2AAgentInvokeRequest,
    A2AAgentInvokeResponse,
)
from app.schemas.ws_ticket import WsTicketResponse
from app.utils.async_cleanup import await_cancel_safe, await_cancel_safe_suppressed
from app.utils.payload_extract import extract_provider_and_external_session_id

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


def _adapt_invoke_metadata_for_upstream(
    payload: A2AAgentInvokeRequest,
) -> dict[str, Any] | None:
    provider, _external_session_id = extract_provider_and_external_session_id(
        {"metadata": payload.metadata or {}}
    )
    return adapt_working_directory_metadata_for_upstream(
        payload.metadata,
        payload.working_directory,
        metadata_namespace=provider or "opencode",
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
    await record_preempt_history_event(
        state=state,
        user_id=user_id,
        event=event,
        session_factory=AsyncSessionLocal,
        commit_fn=commit_safely,
        session_hub=session_hub_service,
    )


async def _preempt_previous_invoke_if_requested(
    *,
    state: InvokeState,
    payload: A2AAgentInvokeRequest,
    user_id: UUID,
) -> None:
    await preempt_previous_invoke_if_requested(
        state=state,
        payload=payload,
        user_id=user_id,
        find_latest_agent_message_id_fn=_find_latest_agent_message_id,
        is_interrupt_requested_fn=_is_interrupt_requested,
        record_preempt_history_event_fn=_record_preempt_history_event,
    )


async def _bind_inflight_task_if_needed(
    *,
    state: InvokeState,
    user_id: UUID,
) -> None:
    await bind_inflight_task_if_needed(
        state=state,
        user_id=user_id,
        record_preempt_history_event_fn=_record_preempt_history_event,
    )


async def _unregister_inflight_invoke(
    *,
    state: InvokeState,
    user_id: UUID,
) -> None:
    await unregister_inflight_invoke(
        state=state,
        user_id=user_id,
    )


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
    return route_runner_streaming.build_consume_stream_callbacks(
        state=state,
        request=request,
        logger=logger,
        log_extra=log_extra,
        diagnose_stream_hints_contract_gap_fn=_diagnose_stream_hints_contract_gap,
        collect_stream_hints_fn=route_runner_streaming.collect_stream_hints,
        bind_inflight_task_if_needed_fn=_bind_inflight_task_if_needed,
        persist_stream_block_update_fn=_persist_stream_block_update,
        persist_interrupt_lifecycle_event_fn=_persist_interrupt_lifecycle_event,
        flush_stream_buffer_fn=_flush_stream_buffer,
        persist_local_outcome_fn=_persist_local_outcome,
        build_persisted_finalization_ack_event_fn=(
            route_runner_streaming.build_persisted_finalization_ack_event
        ),
        unregister_inflight_invoke_fn=_unregister_inflight_invoke,
    )


async def _run_preempt_session_control(
    *,
    runtime: Any,
    payload: A2AAgentInvokeRequest,
    user_id: UUID,
) -> A2AAgentInvokeResponse:
    return await run_preempt_session_control(
        runtime=runtime,
        payload=payload,
        user_id=user_id,
        find_latest_agent_message_id_fn=_find_latest_agent_message_id,
        session_factory=AsyncSessionLocal,
        commit_fn=commit_safely,
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
    upstream_metadata = _adapt_invoke_metadata_for_upstream(payload)

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
                metadata=upstream_metadata,
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
            metadata=upstream_metadata,
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
    upstream_metadata = _adapt_invoke_metadata_for_upstream(payload)

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
            metadata=upstream_metadata,
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
    upstream_metadata = _adapt_invoke_metadata_for_upstream(payload)
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
            metadata=upstream_metadata,
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
    await route_runner_routes.run_ws_invoke_route(
        websocket=websocket,
        db=db,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        gateway=gateway,
        runtime_builder=runtime_builder,
        runtime_not_found_errors=runtime_not_found_errors,
        runtime_not_found_message=runtime_not_found_message,
        runtime_not_found_code=runtime_not_found_code,
        runtime_validation_errors=runtime_validation_errors,
        validate_message=validate_message,
        logger=logger,
        invoke_log_message=invoke_log_message,
        invoke_log_extra_builder=invoke_log_extra_builder,
        unexpected_log_message=unexpected_log_message,
        close_open_transaction_fn=_close_open_transaction,
        build_invoke_guard_key_fn=build_invoke_guard_key,
        run_ws_invoke_with_session_recovery_fn=run_ws_invoke_with_session_recovery,
        await_cancel_safe_fn=await_cancel_safe,
        await_cancel_safe_suppressed_fn=await_cancel_safe_suppressed,
        guard_inflight_invoke_fn=guard_inflight_invoke,
        session_not_found_retry_limit=_SESSION_NOT_FOUND_RETRY_LIMIT,
    )


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
    return await route_runner_routes.run_http_invoke_route(
        db=db,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
        stream=stream,
        gateway=gateway,
        runtime_builder=runtime_builder,
        runtime_not_found_errors=runtime_not_found_errors,
        runtime_not_found_status_code=runtime_not_found_status_code,
        runtime_validation_errors=runtime_validation_errors,
        runtime_validation_status_code=runtime_validation_status_code,
        runtime_validation_status_overrides=runtime_validation_status_overrides,
        validate_message=validate_message,
        logger=logger,
        invoke_log_message=invoke_log_message,
        invoke_log_extra_builder=invoke_log_extra_builder,
        close_open_transaction_fn=_close_open_transaction,
        build_invoke_guard_key_fn=build_invoke_guard_key,
        try_acquire_invoke_guard_fn=_try_acquire_invoke_guard,
        release_invoke_guard_fn=_release_invoke_guard,
        run_http_invoke_with_session_recovery_fn=run_http_invoke_with_session_recovery,
        guard_inflight_invoke_fn=guard_inflight_invoke,
        session_not_found_retry_limit=_SESSION_NOT_FOUND_RETRY_LIMIT,
    )


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
    return await route_runner_ws_ticket.run_issue_ws_ticket_route(
        db=db,
        user_id=user_id,
        scope_type=scope_type,
        scope_id=scope_id,
        ensure_access=ensure_access,
        not_found_errors=not_found_errors,
        not_found_status_code=not_found_status_code,
        not_found_detail=not_found_detail,
        issue_ticket_fn=ws_ticket_service.issue_ticket,
    )
