"""Shared invoke flow runner for personal/hub A2A route handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal
from uuid import UUID

from fastapi import WebSocket
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.transaction import commit_safely
from app.schemas.a2a_invoke import A2AAgentInvokeRequest, A2AAgentInvokeResponse
from app.services.a2a_invoke_service import a2a_invoke_service
from app.services.invoke_session_binding import (
    merge_invoke_binding_state,
    normalize_invoke_binding_state,
)
from app.services.session_hub import session_hub_service

AgentSource = Literal["personal", "shared"]


@dataclass
class _InvokeState:
    local_session: Any
    local_source: Any
    context_id: str | None
    metadata: dict[str, Any]


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
]:
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

    async def on_complete(stream_text: str) -> None:
        if state.local_session is None or state.local_source is None:
            return
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
        )
        await commit_safely(db)

    async def on_error(error_message: str) -> None:
        if state.local_session is None or state.local_source is None:
            return
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
        )
        await commit_safely(db)

    return on_event, on_complete, on_error


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
        on_event, on_complete, on_error = _build_stream_callbacks(
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
        response_content = (
            result.get("content")
            if success
            else (result.get("error") or "A2A invocation failed")
        ) or ""
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
    on_event, on_complete, on_error = _build_stream_callbacks(
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
        on_error=on_error,
        on_event=on_event,
    )


__all__ = ["run_http_invoke", "run_ws_invoke"]
