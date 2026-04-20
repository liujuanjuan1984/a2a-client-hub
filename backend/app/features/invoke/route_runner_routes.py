"""Route adapter helpers for invoke HTTP and WebSocket entrypoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable, cast
from uuid import UUID

from fastapi import HTTPException, WebSocket, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.error_codes import status_code_for_invoke_error_code
from app.api.error_handlers import build_error_detail, build_error_response
from app.features.invoke import session_binding as invoke_session_binding
from app.features.invoke.service import a2a_invoke_service
from app.schemas.a2a_invoke import (
    A2AAgentInvokeRequest,
    A2AAgentInvokeResponse,
)


async def run_ws_invoke_route(
    *,
    websocket: WebSocket,
    db: AsyncSession,
    user_id: UUID,
    agent_id: UUID,
    agent_source: Any,
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
    close_open_transaction_fn: Callable[[AsyncSession], Awaitable[None]],
    build_invoke_guard_key_fn: Callable[..., str | None],
    run_ws_invoke_with_session_recovery_fn: Callable[..., Awaitable[None]],
    await_cancel_safe_fn: Callable[[Any], Awaitable[Any]],
    await_cancel_safe_suppressed_fn: Callable[[Any], Awaitable[Any]],
    guard_inflight_invoke_fn: Callable[[str | None], Any],
    session_not_found_retry_limit: int,
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
            await await_cancel_safe_fn(
                websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
            )
            return

        if not payload.query.strip():
            await a2a_invoke_service.send_ws_error(
                websocket,
                message="Query must be a non-empty string",
                error_code="invalid_query",
            )
            await await_cancel_safe_fn(
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
            await await_cancel_safe_fn(
                websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            )
            return
        except runtime_validation_errors as exc:
            await a2a_invoke_service.send_ws_error(
                websocket,
                message=str(exc),
                error_code="runtime_invalid",
            )
            await await_cancel_safe_fn(
                websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            )
            return
        await close_open_transaction_fn(db)

        logger.info(
            invoke_log_message,
            extra=invoke_log_extra_builder(payload, runtime),
        )
        guard_key = build_invoke_guard_key_fn(
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            payload=payload,
        )

        try:
            async with guard_inflight_invoke_fn(guard_key):
                await run_ws_invoke_with_session_recovery_fn(
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
                    max_recovery_attempts=session_not_found_retry_limit,
                )
        except ValueError as exc:
            await a2a_invoke_service.send_ws_error(
                websocket,
                message=str(exc),
                error_code=invoke_session_binding.ws_error_code_for_invoke_session_error(
                    str(exc)
                ),
            )
            await await_cancel_safe_fn(
                websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            )
            return

    except Exception as exc:
        from fastapi import WebSocketDisconnect

        if isinstance(exc, WebSocketDisconnect):
            logger.info("WebSocket disconnected", extra={"user_id": str(user_id)})
        else:
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
            await await_cancel_safe_suppressed_fn(websocket.close())
        except Exception:
            pass


async def run_http_invoke_route(
    *,
    db: AsyncSession,
    user_id: UUID,
    agent_id: UUID,
    agent_source: Any,
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
    close_open_transaction_fn: Callable[[AsyncSession], Awaitable[None]],
    build_invoke_guard_key_fn: Callable[..., str | None],
    try_acquire_invoke_guard_fn: Callable[[str], Awaitable[bool]],
    release_invoke_guard_fn: Callable[[str], Awaitable[None]],
    run_http_invoke_with_session_recovery_fn: Callable[..., Awaitable[Any]],
    guard_inflight_invoke_fn: Callable[[str | None], Any],
    session_not_found_retry_limit: int = 1,
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
    await close_open_transaction_fn(db)

    logger.info(
        invoke_log_message,
        extra=invoke_log_extra_builder(payload, runtime),
    )
    guard_key = build_invoke_guard_key_fn(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )

    if stream and guard_key:
        acquired = await try_acquire_invoke_guard_fn(guard_key)
        if not acquired:
            raise HTTPException(
                status_code=invoke_session_binding.status_code_for_invoke_session_error(
                    "invoke_inflight"
                ),
                detail="invoke_inflight",
            )
        try:
            response = cast(
                A2AAgentInvokeResponse | StreamingResponse,
                await run_http_invoke_with_session_recovery_fn(
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
                    max_recovery_attempts=session_not_found_retry_limit,
                ),
            )
        except ValueError as exc:
            await release_invoke_guard_fn(guard_key)
            raise HTTPException(
                status_code=invoke_session_binding.status_code_for_invoke_session_error(
                    str(exc)
                ),
                detail=str(exc),
            ) from exc
        except Exception:
            await release_invoke_guard_fn(guard_key)
            raise

        if isinstance(response, StreamingResponse):
            original_iterator = response.body_iterator

            async def guarded_iterator() -> AsyncIterator[Any]:
                try:
                    async for chunk in original_iterator:
                        yield chunk
                finally:
                    await release_invoke_guard_fn(guard_key)

            response.body_iterator = guarded_iterator()
            return response

        if not response.success:
            await release_invoke_guard_fn(guard_key)
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
        await release_invoke_guard_fn(guard_key)
        return response

    try:
        async with guard_inflight_invoke_fn(guard_key):
            response = cast(
                A2AAgentInvokeResponse | StreamingResponse,
                await run_http_invoke_with_session_recovery_fn(
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
                    max_recovery_attempts=session_not_found_retry_limit,
                ),
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
