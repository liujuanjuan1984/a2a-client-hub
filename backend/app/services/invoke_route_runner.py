"""Shared invoke flow runner for personal/hub A2A route handlers."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal
from uuid import UUID

from fastapi import HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
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
from app.services.system_tools import (
    TOOL_INVOCATION_CHAIN_METADATA_KEY,
    TOOL_INVOCATION_DEPTH_METADATA_KEY,
    TOOL_INVOCATION_MAX_DEPTH_METADATA_KEY,
    ToolContext,
    system_tool_registry,
)
from app.services.ws_ticket_service import ws_ticket_service

AgentSource = Literal["personal", "shared"]

_invoke_inflight_guard = asyncio.Lock()
_invoke_inflight_keys: dict[str, int] = {}


def _coerce_tool_chain(raw_chain: object) -> tuple[str, ...]:
    if isinstance(raw_chain, str):
        parts = [item.strip() for item in raw_chain.split(",")]
        return tuple(item for item in parts if item)
    if not isinstance(raw_chain, (list, tuple)):
        return ()
    result: list[str] = []
    for item in raw_chain:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                result.append(stripped)
    return tuple(result)


def _coerce_tool_int(raw_depth: object) -> int:
    if isinstance(raw_depth, bool):
        return 0
    if isinstance(raw_depth, int):
        return max(raw_depth, 0)
    if isinstance(raw_depth, float):
        return max(int(raw_depth), 0) if raw_depth >= 0 else 0
    if isinstance(raw_depth, str):
        try:
            return max(int(raw_depth.strip()), 0)
        except ValueError:
            return 0
    return 0


def _parse_tool_invocation_state(
    metadata: dict[str, Any],
) -> tuple[tuple[str, ...], int, int]:
    chain = _coerce_tool_chain(metadata.get(TOOL_INVOCATION_CHAIN_METADATA_KEY))
    depth = _coerce_tool_int(metadata.get(TOOL_INVOCATION_DEPTH_METADATA_KEY))
    max_depth = _coerce_tool_int(metadata.get(TOOL_INVOCATION_MAX_DEPTH_METADATA_KEY))
    if max_depth <= 0:
        max_depth = max(1, int(settings.a2a_tool_call_max_depth))
    return chain, depth, max_depth


def _strip_tool_invocation_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(metadata)
    for key in (
        TOOL_INVOCATION_CHAIN_METADATA_KEY,
        TOOL_INVOCATION_DEPTH_METADATA_KEY,
        TOOL_INVOCATION_MAX_DEPTH_METADATA_KEY,
    ):
        cleaned.pop(key, None)
    return cleaned


@dataclass
class _InvokeState:
    local_session: Any
    local_source: Any
    conversation_id: str | None
    context_id: str | None
    metadata: dict[str, Any]
    stream_identity: dict[str, Any]
    stream_usage: dict[str, Any]
    user_message_id: str | None
    client_agent_message_id: str | None
    tool_invocation_chain: tuple[str, ...] = ()
    tool_invocation_depth: int = 0
    tool_max_invocation_depth: int = 0


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


def _pick_tool_name(tool_schema: dict[str, Any]) -> str | None:
    function_node = tool_schema.get("function")
    if isinstance(function_node, dict):
        raw_name = function_node.get("name")
    else:
        raw_name = tool_schema.get("name")
    if isinstance(raw_name, str):
        return raw_name.strip()
    return None


def _merge_tool_schemas(
    *,
    request_tools: list[dict[str, Any]],
    built_in_tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for schema in request_tools:
        if not isinstance(schema, dict):
            continue
        raw_name = _pick_tool_name(schema)
        if not raw_name:
            continue
        key = raw_name.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(schema)

    for schema in built_in_tools:
        if not isinstance(schema, dict):
            continue
        raw_name = _pick_tool_name(schema)
        if not raw_name:
            continue
        key = raw_name.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(schema)

    return merged


def _build_upstream_tools(request_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _merge_tool_schemas(
        request_tools=request_tools,
        built_in_tools=system_tool_registry.build_upstream_tool_schema(),
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
        conversation_id=payload.conversation_id,
    )
    resolved_context_id, resolved_invoke_metadata = normalize_invoke_binding_state(
        context_id=payload.context_id,
        metadata=payload.metadata,
    )
    (
        tool_invocation_chain,
        tool_invocation_depth,
        tool_max_invocation_depth,
    ) = _parse_tool_invocation_state(resolved_invoke_metadata)
    return _InvokeState(
        local_session=local_session,
        local_source=local_source,
        conversation_id=payload.conversation_id,
        context_id=resolved_context_id,
        metadata=_strip_tool_invocation_metadata(resolved_invoke_metadata),
        stream_identity={},
        stream_usage={},
        user_message_id=payload.user_message_id,
        client_agent_message_id=payload.client_agent_message_id,
        tool_invocation_chain=tool_invocation_chain,
        tool_invocation_depth=tool_invocation_depth,
        tool_max_invocation_depth=tool_max_invocation_depth,
    )


def _build_tool_context(
    *,
    db: AsyncSession,
    state: _InvokeState,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    query: str,
    logger: Any,
) -> ToolContext:
    if state.local_session is None:
        tool_invocation_chain = ()
    elif state.tool_invocation_chain:
        tool_invocation_chain = state.tool_invocation_chain
    else:
        tool_invocation_chain = (str(agent_id),)
    return ToolContext(
        db=db,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        query=query,
        context_id=state.context_id,
        conversation_id=state.conversation_id,
        logger=logger,
        metadata=state.metadata,
        tool_invocation_chain=tool_invocation_chain,
        tool_invocation_depth=state.tool_invocation_depth,
        tool_max_invocation_depth=state.tool_max_invocation_depth,
    )


async def _execute_tool_call(
    *,
    tool_call: dict[str, Any],
    tool_context: ToolContext,
    tool_results: list[dict[str, Any]],
) -> None:
    tool_name = str(tool_call.get("tool_name") or "").strip()
    if not tool_name:
        return

    tool_call_id = tool_call.get("tool_call_id")
    tool_call_id = str(tool_call_id).strip() if isinstance(tool_call_id, str) else None
    tool_args = tool_call.get("tool_args")
    if not isinstance(tool_args, dict):
        tool_args = {}

    result_payload: dict[str, Any] = {
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
    }
    tool = system_tool_registry.get_tool(tool_name)
    if tool is None:
        result_payload.update(
            {
                "success": False,
                "error": f"Tool '{tool_name}' is not supported",
                "error_code": "method_not_supported",
            }
        )
        tool_results.append(result_payload)
        return

    tool_call_timeout_seconds = float(settings.a2a_tool_call_timeout_seconds)
    try:
        if tool_call_timeout_seconds > 0:
            tool_result = await asyncio.wait_for(
                tool.execute(tool_args, tool_context),
                timeout=tool_call_timeout_seconds,
            )
        else:
            tool_result = await tool.execute(tool_args, tool_context)
    except TimeoutError:
        result_payload.update(
            {
                "success": False,
                "error": (
                    f"Tool '{tool_name}' execution timed out after "
                    f"{tool_call_timeout_seconds}s"
                ),
                "error_code": "tool_execution_timeout",
            }
        )
        tool_results.append(result_payload)
        return
    except Exception as exc:  # noqa: BLE001
        result_payload.update(
            {
                "success": False,
                "error": str(exc),
                "error_code": "tool_execution_failed",
            }
        )
        tool_results.append(result_payload)
        return

    result_payload.update(
        {
            "success": bool(tool_result.success),
            "content": tool_result.content,
            "error": tool_result.error,
            "error_code": tool_result.error_code,
            "metadata": tool_result.metadata,
            "args": tool_args,
        }
    )
    tool_results.append(result_payload)


def _build_stream_callbacks(
    *,
    db: AsyncSession,
    state: _InvokeState,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    query: str,
    transport: Literal["http_sse", "ws"],
    logger: Any,
) -> tuple[
    Callable[[dict[str, Any]], Any],
    Callable[[str], Any],
    Callable[[str], Any],
    Callable[[dict[str, Any]], Any],
    Callable[[dict[str, Any]], Any],
]:
    stream_response_metadata: dict[str, Any] = {}
    stream_tool_calls: list[dict[str, Any]] = []

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

        # Tool invocation chain/depth is derived from request metadata, which is
        # already populated in _prepare_state. Upstream stream events do not need to
        # mutate this state.

    async def on_tool_call(tool_call: dict[str, Any]) -> None:
        await _execute_tool_call(
            tool_call=tool_call,
            tool_context=_build_tool_context(
                db=db,
                state=state,
                user_id=user_id,
                agent_id=agent_id,
                agent_source=agent_source,
                query=query,
                logger=logger,
            ),
            tool_results=stream_tool_calls,
        )

    async def on_complete(stream_text: str) -> None:
        if state.local_session is None or state.local_source is None:
            return
        final_response_metadata = dict(stream_response_metadata)
        if state.stream_identity:
            final_response_metadata.update(state.stream_identity)
        if state.stream_usage:
            final_response_metadata["usage"] = dict(state.stream_usage)
        if stream_tool_calls:
            final_response_metadata["tool_calls"] = list(stream_tool_calls)
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
            user_message_id=state.user_message_id,
            client_agent_message_id=state.client_agent_message_id,
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
        if state.stream_usage:
            if error_response_metadata is None:
                error_response_metadata = {}
            error_response_metadata["usage"] = dict(state.stream_usage)
        if stream_tool_calls:
            error_response_metadata["tool_calls"] = list(stream_tool_calls)
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
            user_message_id=state.user_message_id,
            client_agent_message_id=state.client_agent_message_id,
            invoke_metadata=state.metadata,
            extra_metadata={"transport": transport, "stream": True},
            response_metadata=error_response_metadata,
        )
        await commit_safely(db)

    return (
        on_event,
        on_complete,
        on_error,
        on_complete_metadata,
        on_tool_call,
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
        db=db,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )

    if stream:
        (
            on_event,
            on_complete,
            on_error,
            on_complete_metadata,
            on_tool_call,
        ) = _build_stream_callbacks(
            db=db,
            state=state,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            query=payload.query,
            transport="http_sse",
            logger=logger,
        )
        return a2a_invoke_service.stream_sse(
            gateway=gateway,
            resolved=runtime.resolved,
            query=payload.query,
            context_id=payload.context_id,
            metadata=payload.metadata,
            tools=_build_upstream_tools(payload.tools),
            tool_choice=payload.tool_choice,
            validate_message=validate_message,
            logger=logger,
            log_extra=log_extra,
            on_complete=on_complete,
            on_complete_metadata=on_complete_metadata,
            on_error=on_error,
            on_event=on_event,
            on_tool_call=on_tool_call,
        )

    result = await gateway.invoke(
        resolved=runtime.resolved,
        query=payload.query,
        context_id=payload.context_id,
        metadata=payload.metadata,
        tools=_build_upstream_tools(payload.tools),
        tool_choice=payload.tool_choice,
    )

    tool_results: list[dict[str, Any]] = []
    if result.get("success"):
        for tool_call in a2a_invoke_service.extract_tool_calls_from_payload(result):
            await _execute_tool_call(
                tool_call=tool_call,
                tool_context=_build_tool_context(
                    db=db,
                    state=state,
                    user_id=user_id,
                    agent_id=agent_id,
                    agent_source=agent_source,
                    query=payload.query,
                    logger=logger,
                ),
                tool_results=tool_results,
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
        usage_hints = a2a_invoke_service.extract_usage_hints_from_invoke_result(result)
        if usage_hints:
            if response_metadata is None:
                response_metadata = {}
            response_metadata["usage"] = usage_hints
        if tool_results:
            if response_metadata is None:
                response_metadata = {}
            response_metadata["tool_calls"] = list(tool_results)
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
            user_message_id=state.user_message_id,
            client_agent_message_id=state.client_agent_message_id,
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
    (
        on_event,
        on_complete,
        on_error,
        on_complete_metadata,
        on_tool_call,
    ) = _build_stream_callbacks(
        db=db,
        state=state,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        query=payload.query,
        transport="ws",
        logger=logger,
    )
    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=gateway,
        resolved=runtime.resolved,
        query=payload.query,
        context_id=payload.context_id,
        metadata=payload.metadata,
        tools=_build_upstream_tools(payload.tools),
        tool_choice=payload.tool_choice,
        validate_message=validate_message,
        logger=logger,
        log_extra=log_extra,
        on_complete=on_complete,
        on_complete_metadata=on_complete_metadata,
        on_error=on_error,
        on_event=on_event,
        on_tool_call=on_tool_call,
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
        guard_key = _build_invoke_guard_key(
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            payload=payload,
        )

        try:
            async with _guard_inflight_invoke(guard_key):
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
            response = await run_http_invoke(
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

        await _release_invoke_guard(guard_key)
        return response

    try:
        async with _guard_inflight_invoke(guard_key):
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
