"""Shared invoke flow runner for personal/hub A2A route handlers."""

from __future__ import annotations

import asyncio
import inspect
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal
from uuid import UUID

from fastapi import HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.error_codes import status_code_for_invoke_error_code
from app.db.session import AsyncSessionLocal
from app.db.transaction import commit_safely
from app.schemas.a2a_invoke import A2AAgentInvokeRequest, A2AAgentInvokeResponse
from app.schemas.ws_ticket import WsTicketResponse
from app.services.a2a_invoke_service import a2a_invoke_service
from app.services.invoke_session_binding import (
    is_recoverable_invoke_session_error,
    merge_invoke_binding_state,
    normalize_invoke_binding_state,
    status_code_for_invoke_session_error,
    ws_error_code_for_invoke_session_error,
    ws_error_code_for_recovery_failed,
)
from app.services.session_hub import session_hub_service
from app.services.ws_ticket_service import ws_ticket_service
from app.utils.payload_extract import (
    as_dict,
    extract_context_id,
    extract_provider_and_external_session_id,
)
from app.utils.session_identity import normalize_non_empty_text

AgentSource = Literal["personal", "shared"]

_invoke_inflight_guard = asyncio.Lock()
_invoke_inflight_keys: dict[str, int] = {}

_SESSION_NOT_FOUND_RETRY_LIMIT = 1
_SESSION_NOT_FOUND_RECOVERY_EXHAUSTED_MESSAGE = (
    "Failed to recover conversation session. Please retry."
)


@dataclass
class _InvokeState:
    local_session_id: UUID | None
    local_source: Literal["manual", "scheduled"] | None
    context_id: str | None
    metadata: dict[str, Any]
    stream_identity: dict[str, Any]
    stream_usage: dict[str, Any]
    user_message_id: str | None
    client_agent_message_id: str | None
    message_refs: dict[str, UUID] | None = None
    persisted_response_content: str | None = None
    persisted_success: bool | None = None
    persisted_error_code: str | None = None


def _normalize_query_for_invoke_guard(query: str) -> str:
    return " ".join(query.split())


def _build_invoke_guard_key(
    *,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
) -> str | None:
    conversation_id = (
        payload.conversation_id.strip()
        if isinstance(payload.conversation_id, str)
        else ""
    )
    context_id = (
        payload.context_id.strip() if isinstance(payload.context_id, str) else ""
    )
    if not conversation_id and not context_id:
        return None
    normalized_query = _normalize_query_for_invoke_guard(payload.query)
    return (
        f"{user_id}:{agent_source}:{agent_id}:{conversation_id}:{context_id}:"
        f"{normalized_query}"
    )


@asynccontextmanager
async def _guard_inflight_invoke(
    guard_key: str | None,
):
    if not guard_key:
        yield
        return

    acquired = await _try_acquire_invoke_guard(guard_key)
    if not acquired:
        raise ValueError("invoke_inflight")

    try:
        yield
    finally:
        await _release_invoke_guard(guard_key)


async def _try_acquire_invoke_guard(guard_key: str) -> bool:
    async with _invoke_inflight_guard:
        active_count = _invoke_inflight_keys.get(guard_key, 0)
        if active_count > 0:
            return False
        _invoke_inflight_keys[guard_key] = 1
        return True


async def _release_invoke_guard(guard_key: str) -> None:
    async with _invoke_inflight_guard:
        remaining = _invoke_inflight_keys.get(guard_key, 0) - 1
        if remaining <= 0:
            _invoke_inflight_keys.pop(guard_key, None)
        else:
            _invoke_inflight_keys[guard_key] = remaining


async def _prepare_state(
    *,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
) -> _InvokeState:
    local_session_id: UUID | None = None
    local_source: Literal["manual", "scheduled"] | None = None
    async with AsyncSessionLocal() as prepare_db:
        (
            local_session,
            local_source,
        ) = await session_hub_service.ensure_local_session_for_invoke(
            prepare_db,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            conversation_id=payload.conversation_id,
        )
        if local_session is not None and isinstance(local_session.id, UUID):
            local_session_id = local_session.id
        await commit_safely(prepare_db)

    resolved_context_id, resolved_invoke_metadata = normalize_invoke_binding_state(
        context_id=payload.context_id,
        metadata=payload.metadata,
    )
    return _InvokeState(
        local_session_id=local_session_id,
        local_source=local_source,
        context_id=resolved_context_id,
        metadata=resolved_invoke_metadata,
        stream_identity={},
        stream_usage={},
        user_message_id=payload.user_message_id,
        client_agent_message_id=payload.client_agent_message_id,
        message_refs=None,
        persisted_response_content=None,
        persisted_success=None,
        persisted_error_code=None,
    )


async def _close_open_transaction(db: AsyncSession) -> None:
    in_transaction = getattr(db, "in_transaction", None)
    rollback = getattr(db, "rollback", None)
    if not callable(in_transaction) or not callable(rollback):
        return
    if not in_transaction():
        return
    rollback_outcome = rollback()
    if inspect.isawaitable(rollback_outcome):
        await rollback_outcome


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


def _build_stream_callbacks(
    *,
    state: _InvokeState,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    query: str,
    transport: Literal["http_json", "http_sse", "scheduled", "ws"],
    stream_enabled: bool = True,
    on_error_metadata: Callable[[dict[str, Any]], Any] | None = None,
) -> tuple[
    Callable[[dict[str, Any]], Any],
    Callable[[str], Any],
    Callable[[str], Any],
    Callable[[dict[str, Any]], Any],
]:
    stream_response_metadata: dict[str, Any] = {}

    async def on_event(event_payload: dict[str, Any]) -> None:
        (
            event_context_id,
            event_metadata,
        ) = a2a_invoke_service.extract_binding_hints_from_serialized_event(
            event_payload
        )
        state.context_id, state.metadata = merge_invoke_binding_state(
            current_context_id=state.context_id,
            current_metadata=state.metadata,
            next_context_id=event_context_id,
            next_metadata=event_metadata,
        )
        identity_hints = (
            a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
                event_payload
            )
        )
        if identity_hints:
            state.stream_identity.update(identity_hints)
        usage_hints = a2a_invoke_service.extract_usage_hints_from_serialized_event(
            event_payload
        )
        if usage_hints:
            state.stream_usage = usage_hints

    async def on_complete(stream_text: str) -> None:
        if state.local_session_id is None or state.local_source is None:
            return
        final_response_metadata = dict(stream_response_metadata)
        if state.stream_identity:
            final_response_metadata.update(state.stream_identity)
        if state.stream_usage:
            final_response_metadata["usage"] = dict(state.stream_usage)
        async with AsyncSessionLocal() as persist_db:
            message_refs = await session_hub_service.record_local_invoke_messages_by_local_session_id(
                persist_db,
                local_session_id=state.local_session_id,
                source=state.local_source,
                user_id=user_id,
                agent_id=agent_id,
                agent_source=agent_source,
                query=query,
                response_content=stream_text or "",
                success=True,
                context_id=state.context_id,
                user_message_id=state.user_message_id,
                client_agent_message_id=state.client_agent_message_id,
                invoke_metadata=state.metadata,
                extra_metadata={"transport": transport, "stream": stream_enabled},
                response_metadata=final_response_metadata,
            )
            await commit_safely(persist_db)
        state.message_refs = message_refs
        state.persisted_success = True
        state.persisted_response_content = stream_text or ""
        state.persisted_error_code = None

    async def on_complete_metadata(payload: dict[str, Any]) -> None:
        nonlocal stream_response_metadata
        if not isinstance(payload, dict):
            return
        stream_response_metadata = dict(payload)

    async def on_error(error_message: str) -> None:
        if state.local_session_id is None or state.local_source is None:
            return
        error_response_metadata = (
            dict(state.stream_identity) if state.stream_identity else None
        )
        if state.stream_usage:
            if error_response_metadata is None:
                error_response_metadata = {}
            error_response_metadata["usage"] = dict(state.stream_usage)
        async with AsyncSessionLocal() as persist_db:
            message_refs = await session_hub_service.record_local_invoke_messages_by_local_session_id(
                persist_db,
                local_session_id=state.local_session_id,
                source=state.local_source,
                user_id=user_id,
                agent_id=agent_id,
                agent_source=agent_source,
                query=query,
                response_content=error_message,
                success=False,
                context_id=state.context_id,
                user_message_id=state.user_message_id,
                client_agent_message_id=state.client_agent_message_id,
                invoke_metadata=state.metadata,
                extra_metadata={"transport": transport, "stream": stream_enabled},
                response_metadata=error_response_metadata,
            )
            await commit_safely(persist_db)
        state.message_refs = message_refs
        state.persisted_success = False
        state.persisted_response_content = error_message
        if on_error_metadata is not None:
            payload = {
                "message": error_message,
                "error_code": state.persisted_error_code,
            }
            outcome = on_error_metadata(payload)
            if inspect.isawaitable(outcome):
                await outcome

    return on_event, on_complete, on_error, on_complete_metadata


def _extract_rebound_continue_binding_fields(
    *,
    continue_payload: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    """Resolve provider/context binding from the continue payload metadata."""
    continue_payload_dict = as_dict(continue_payload)
    continue_metadata = as_dict(continue_payload_dict.get("metadata"))

    provider, external_session_id = extract_provider_and_external_session_id(
        continue_metadata
    )
    context_id = extract_context_id(continue_metadata)

    return provider, external_session_id, context_id


def _build_rebound_invoke_payload(
    *,
    payload: A2AAgentInvokeRequest,
    continue_payload: dict[str, Any],
) -> A2AAgentInvokeRequest:
    (
        provider,
        external_session_id,
        context_id,
    ) = _extract_rebound_continue_binding_fields(continue_payload=continue_payload)
    conversation_id = continue_payload.get("conversationId")

    normalized_provider = provider.lower() if provider else ""
    normalized_external_session_id = external_session_id or ""
    next_metadata = dict(payload.metadata or {})
    if normalized_provider:
        next_metadata["provider"] = normalized_provider
    if normalized_external_session_id:
        next_metadata["externalSessionId"] = normalized_external_session_id
    next_context_id = normalize_non_empty_text(context_id) or payload.context_id
    next_conversation_id = (
        normalize_non_empty_text(conversation_id) or payload.conversation_id
    )

    return payload.model_copy(
        update={
            "conversation_id": next_conversation_id,
            "context_id": next_context_id,
            "metadata": next_metadata,
        },
    )


async def run_http_invoke_with_session_recovery(
    *,
    db: AsyncSession,
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
            db=db,
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
        if stream or response.success:
            return response
        if not is_recoverable_invoke_session_error(response.error_code):
            return response
        if remaining_retries <= 0:
            return response
        if not isinstance(current_payload.conversation_id, str):
            return response

        remaining_retries -= 1
        try:
            continue_binding = await _continue_session_with_short_transaction(
                user_id=user_id,
                conversation_id=current_payload.conversation_id,
            )
        except ValueError:
            return response
        current_payload = _build_rebound_invoke_payload(
            payload=current_payload,
            continue_payload=continue_binding,
        )


async def run_http_invoke(
    *,
    db: AsyncSession,
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
    state = await _prepare_state(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )

    if stream:
        on_event, on_complete, on_error, on_complete_metadata = _build_stream_callbacks(
            state=state,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            query=payload.query,
            transport="http_sse",
        )
        return a2a_invoke_service.stream_sse(
            gateway=gateway,
            resolved=runtime.resolved,
            query=payload.query,
            context_id=payload.context_id,
            metadata=payload.metadata,
            validate_message=validate_message,
            logger=logger,
            log_extra=log_extra,
            on_complete=on_complete,
            on_complete_metadata=on_complete_metadata,
            on_error=on_error,
            on_event=on_event,
            resume_from_sequence=payload.resume_from_sequence,
            cache_key=payload.user_message_id,
        )

    def _capture_error_metadata(payload_data: dict[str, Any]) -> None:
        error_code = payload_data.get("error_code")
        state.persisted_error_code = (
            str(error_code) if isinstance(error_code, str) and error_code else None
        )

    on_event, on_complete, on_error, on_complete_metadata = _build_stream_callbacks(
        state=state,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        query=payload.query,
        transport="http_json",
        stream_enabled=False,
        on_error_metadata=_capture_error_metadata,
    )
    result = await a2a_invoke_service.consume_stream(
        gateway=gateway,
        resolved=runtime.resolved,
        query=payload.query,
        context_id=payload.context_id,
        metadata=payload.metadata,
        validate_message=validate_message,
        logger=logger,
        log_extra=log_extra,
        on_complete=on_complete,
        on_complete_metadata=on_complete_metadata,
        on_error=on_error,
        on_event=on_event,
        on_error_metadata=_capture_error_metadata,
    )
    success = bool(result.get("success"))
    content = state.persisted_response_content
    if content is None:
        content = result.get("content")
    error = None if success else (result.get("error") or content)
    error_code = (
        state.persisted_error_code
        if not success and state.persisted_error_code
        else result.get("error_code")
    )
    return A2AAgentInvokeResponse(
        success=success,
        content=content,
        error=error,
        error_code=error_code,
        agent_name=runtime.resolved.name,
        agent_url=runtime.resolved.url,
    )


async def run_background_invoke(
    *,
    db: AsyncSession,
    gateway: Any,
    runtime: Any,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
    validate_message: Callable[[dict[str, Any]], list[Any]],
    logger: Any,
    log_extra: dict[str, Any],
    total_timeout_seconds: float | None = None,
    idle_timeout_seconds: float | None = None,
) -> dict[str, Any]:
    state = await _prepare_state(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )

    def _capture_error_metadata(payload_data: dict[str, Any]) -> None:
        error_code = payload_data.get("error_code")
        state.persisted_error_code = (
            str(error_code) if isinstance(error_code, str) and error_code else None
        )

    on_event, on_complete, on_error, on_complete_metadata = _build_stream_callbacks(
        state=state,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        query=payload.query,
        transport="scheduled",
        stream_enabled=True,
        on_error_metadata=_capture_error_metadata,
    )
    stream_result = await a2a_invoke_service.consume_stream(
        gateway=gateway,
        resolved=runtime.resolved,
        query=payload.query,
        context_id=payload.context_id,
        metadata=payload.metadata,
        validate_message=validate_message,
        logger=logger,
        log_extra=log_extra,
        on_complete=on_complete,
        on_complete_metadata=on_complete_metadata,
        on_error=on_error,
        on_event=on_event,
        on_error_metadata=_capture_error_metadata,
        total_timeout_seconds=total_timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
    )
    success = bool(stream_result.get("success"))
    response_content = state.persisted_response_content
    if response_content is None:
        fallback_value = (
            stream_result.get("content") if success else stream_result.get("error")
        )
        response_content = str(fallback_value or "")
    return {
        "success": success,
        "response_content": response_content,
        "error": stream_result.get("error"),
        "error_code": state.persisted_error_code or stream_result.get("error_code"),
        "conversation_id": (
            state.message_refs.get("conversation_id") if state.message_refs else None
        ),
        "message_refs": dict(state.message_refs) if state.message_refs else {},
        "context_id": state.context_id,
    }


async def run_ws_invoke(
    *,
    websocket: WebSocket,
    db: AsyncSession,
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
    state = await _prepare_state(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )
    on_event, on_complete, on_error, on_complete_metadata = _build_stream_callbacks(
        state=state,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        query=payload.query,
        transport="ws",
        on_error_metadata=on_error_metadata,
    )
    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=gateway,
        resolved=runtime.resolved,
        query=payload.query,
        context_id=payload.context_id,
        metadata=payload.metadata,
        validate_message=validate_message,
        logger=logger,
        log_extra=log_extra,
        on_complete=on_complete,
        on_complete_metadata=on_complete_metadata,
        on_error=on_error,
        on_event=on_event,
        on_error_metadata=on_error_metadata,
        send_stream_end=send_stream_end,
        resume_from_sequence=payload.resume_from_sequence,
        cache_key=payload.user_message_id,
    )


async def run_ws_invoke_with_session_recovery(
    *,
    websocket: WebSocket,
    db: AsyncSession,
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

        def _send_recovery_failed_error() -> None:
            return a2a_invoke_service.send_ws_error(
                websocket=websocket,
                message=stream_error_message
                or _SESSION_NOT_FOUND_RECOVERY_EXHAUSTED_MESSAGE,
                error_code=ws_error_code_for_recovery_failed(stream_error_code or ""),
            )

        await run_ws_invoke(
            websocket=websocket,
            db=db,
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

        if not is_recoverable_invoke_session_error(stream_error_code):
            await a2a_invoke_service.send_ws_stream_end(websocket)
            return
        if remaining_retries <= 0:
            await _send_recovery_failed_error()
            await a2a_invoke_service.send_ws_stream_end(websocket)
            return
        if not isinstance(current_payload.conversation_id, str):
            await a2a_invoke_service.send_ws_stream_end(websocket)
            return

        remaining_retries -= 1
        try:
            continue_binding = await _continue_session_with_short_transaction(
                user_id=user_id,
                conversation_id=current_payload.conversation_id,
            )
        except ValueError:
            await a2a_invoke_service.send_ws_stream_end(websocket)
            return
        current_payload = _build_rebound_invoke_payload(
            payload=current_payload,
            continue_payload=continue_binding,
        )


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
    await websocket.accept(subprotocol=selected_subprotocol)

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
            await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
            return

        if not payload.query.strip():
            await a2a_invoke_service.send_ws_error(
                websocket,
                message="Query must be a non-empty string",
                error_code="invalid_query",
            )
            await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
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
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        except runtime_validation_errors as exc:
            await a2a_invoke_service.send_ws_error(
                websocket,
                message=str(exc),
                error_code="runtime_invalid",
            )
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            return
        await _close_open_transaction(db)

        logger.info(
            invoke_log_message,
            extra=invoke_log_extra_builder(payload, runtime),
        )
        guard_key = _build_invoke_guard_key(
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            payload=payload,
        )

        try:
            async with _guard_inflight_invoke(guard_key):
                await run_ws_invoke_with_session_recovery(
                    websocket=websocket,
                    db=db,
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
                error_code=ws_error_code_for_invoke_session_error(str(exc)),
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
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
            await websocket.close()
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
        raise HTTPException(
            status_code=runtime_validation_status_code,
            detail=str(exc),
        ) from exc
    await _close_open_transaction(db)

    logger.info(
        invoke_log_message,
        extra=invoke_log_extra_builder(payload, runtime),
    )
    guard_key = _build_invoke_guard_key(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )

    if stream and guard_key:
        acquired = await _try_acquire_invoke_guard(guard_key)
        if not acquired:
            raise HTTPException(
                status_code=status_code_for_invoke_session_error("invoke_inflight"),
                detail="invoke_inflight",
            )
        try:
            response = await run_http_invoke_with_session_recovery(
                db=db,
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
        except Exception:
            await _release_invoke_guard(guard_key)
            raise

        if isinstance(response, StreamingResponse):
            original_iterator = response.body_iterator

            async def guarded_iterator():
                try:
                    async for chunk in original_iterator:
                        yield chunk
                finally:
                    await _release_invoke_guard(guard_key)

            response.body_iterator = guarded_iterator()
            return response

        if not response.success:
            await _release_invoke_guard(guard_key)
            return JSONResponse(
                status_code=status_code_for_invoke_error_code(response.error_code),
                content=response.model_dump(),
            )
        await _release_invoke_guard(guard_key)
        return response

    try:
        async with _guard_inflight_invoke(guard_key):
            response = await run_http_invoke_with_session_recovery(
                db=db,
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
            if response.success:
                return response
            return JSONResponse(
                status_code=status_code_for_invoke_error_code(response.error_code),
                content=response.model_dump(),
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=status_code_for_invoke_session_error(str(exc)),
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

    issued = await ws_ticket_service.issue_ticket(
        db,
        user_id=user_id,
        scope_type=scope_type,
        scope_id=scope_id,
    )
    return WsTicketResponse(
        token=issued.token,
        expires_at=issued.expires_at,
        expires_in=issued.expires_in,
    )


__all__ = [
    "run_background_invoke",
    "run_http_invoke",
    "run_http_invoke_with_session_recovery",
    "run_http_invoke_route",
    "run_issue_ws_ticket_route",
    "run_ws_invoke",
    "run_ws_invoke_route",
]
