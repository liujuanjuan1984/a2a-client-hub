"""Shared invoke flow runner for personal/hub A2A route handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal
from uuid import UUID

from fastapi import HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.transaction import commit_safely
from app.schemas.a2a_invoke import A2AAgentInvokeRequest, A2AAgentInvokeResponse
from app.schemas.ws_ticket import WsTicketResponse
from app.services.a2a_invoke_service import a2a_invoke_service
from app.services.invoke_session_binding import (
    merge_invoke_binding_state,
    normalize_invoke_binding_state,
    status_code_for_invoke_session_error,
    ws_error_code_for_invoke_session_error,
)
from app.services.session_hub import session_hub_service
from app.services.ws_ticket_service import ws_ticket_service

AgentSource = Literal["personal", "shared"]


@dataclass
class _InvokeState:
    local_session: Any
    local_source: Any
    context_id: str | None
    metadata: dict[str, Any]
    stream_identity: dict[str, Any]


async def _prepare_state(
    *,
    db: AsyncSession,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
) -> _InvokeState:
    (
        local_session,
        local_source,
    ) = await session_hub_service.ensure_local_session_for_invoke(
        db,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        session_key=payload.session_id,
    )
    resolved_context_id, resolved_invoke_metadata = normalize_invoke_binding_state(
        context_id=payload.context_id,
        metadata=payload.metadata,
    )
    return _InvokeState(
        local_session=local_session,
        local_source=local_source,
        context_id=resolved_context_id,
        metadata=resolved_invoke_metadata,
        stream_identity={},
    )


def _build_stream_callbacks(
    *,
    db: AsyncSession,
    state: _InvokeState,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    query: str,
    transport: Literal["http_sse", "ws"],
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

    async def on_complete(stream_text: str) -> None:
        if state.local_session is None or state.local_source is None:
            return
        final_response_metadata = dict(stream_response_metadata)
        if state.stream_identity:
            final_response_metadata.update(state.stream_identity)
        await session_hub_service.record_local_invoke_messages(
            db,
            session=state.local_session,
            source=state.local_source,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            query=query,
            response_content=stream_text or "",
            success=True,
            context_id=state.context_id,
            invoke_metadata=state.metadata,
            extra_metadata={"transport": transport, "stream": True},
            response_metadata=final_response_metadata,
        )
        await commit_safely(db)

    async def on_complete_metadata(payload: dict[str, Any]) -> None:
        nonlocal stream_response_metadata
        if not isinstance(payload, dict):
            return
        stream_response_metadata = dict(payload)

    async def on_error(error_message: str) -> None:
        if state.local_session is None or state.local_source is None:
            return
        error_response_metadata = (
            dict(state.stream_identity) if state.stream_identity else None
        )
        await session_hub_service.record_local_invoke_messages(
            db,
            session=state.local_session,
            source=state.local_source,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            query=query,
            response_content=error_message,
            success=False,
            context_id=state.context_id,
            invoke_metadata=state.metadata,
            extra_metadata={"transport": transport, "stream": True},
            response_metadata=error_response_metadata,
        )
        await commit_safely(db)

    return on_event, on_complete, on_error, on_complete_metadata


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
        db=db,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )

    if stream:
        on_event, on_complete, on_error, on_complete_metadata = _build_stream_callbacks(
            db=db,
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
        )

    result = await gateway.invoke(
        resolved=runtime.resolved,
        query=payload.query,
        context_id=payload.context_id,
        metadata=payload.metadata,
    )

    success = bool(result.get("success"))
    if state.local_session is not None and state.local_source is not None:
        (
            result_context_id,
            result_metadata,
        ) = a2a_invoke_service.extract_binding_hints_from_invoke_result(result)
        state.context_id, state.metadata = merge_invoke_binding_state(
            current_context_id=state.context_id,
            current_metadata=state.metadata,
            next_context_id=result_context_id,
            next_metadata=result_metadata,
        )
        state.stream_identity.update(
            a2a_invoke_service.extract_stream_identity_hints_from_invoke_result(result)
        )
        response_content = (
            result.get("content")
            if success
            else (result.get("error") or "A2A invocation failed")
        ) or ""
        response_metadata = (
            dict(state.stream_identity) if state.stream_identity else None
        )
        await session_hub_service.record_local_invoke_messages(
            db,
            session=state.local_session,
            source=state.local_source,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            query=payload.query,
            response_content=response_content,
            success=success,
            context_id=state.context_id,
            invoke_metadata=state.metadata,
            extra_metadata={
                "transport": "http_json",
                "stream": False,
                "error_code": result.get("error_code"),
            },
            response_metadata=response_metadata,
        )
        await commit_safely(db)

    return A2AAgentInvokeResponse(
        success=success,
        content=result.get("content"),
        error=result.get("error"),
        error_code=result.get("error_code"),
        agent_name=runtime.resolved.name,
        agent_url=runtime.resolved.url,
    )


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
) -> None:
    state = await _prepare_state(
        db=db,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )
    on_event, on_complete, on_error, on_complete_metadata = _build_stream_callbacks(
        db=db,
        state=state,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        query=payload.query,
        transport="ws",
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

        logger.info(
            invoke_log_message,
            extra=invoke_log_extra_builder(payload, runtime),
        )

        try:
            await run_ws_invoke(
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
) -> A2AAgentInvokeResponse | StreamingResponse:
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

    logger.info(
        invoke_log_message,
        extra=invoke_log_extra_builder(payload, runtime),
    )
    try:
        return await run_http_invoke(
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
    "run_http_invoke",
    "run_http_invoke_route",
    "run_issue_ws_ticket_route",
    "run_ws_invoke",
    "run_ws_invoke_route",
]
