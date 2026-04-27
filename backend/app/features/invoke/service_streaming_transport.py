"""Transport-oriented streaming helpers for invoke service."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from fastapi import WebSocket
from fastapi.responses import StreamingResponse

from app.features.invoke import stream_payloads
from app.features.invoke.service_types import (
    StreamErrorMetadataCallbackFn,
    StreamEventPayloadCallbackFn,
    StreamFinalizedCallbackFn,
    StreamFinishReason,
    StreamMetadataCallbackFn,
    StreamOutcome,
    StreamSessionStartedCallbackFn,
    StreamTextCallbackFn,
    ValidateMessageFn,
)
from app.features.invoke.stream_diagnostics import (
    build_artifact_update_log_sample,
    build_validation_errors_log_sample,
    extract_artifact_validation_errors,
    warn_non_contract_artifact_update_once,
)
from app.utils.json_encoder import json_dumps


def stream_sse(
    runtime: Any,
    *,
    accumulator_factory: Callable[[], Any],
    gateway: Any,
    invoke_session: Any | None = None,
    resolved: Any,
    query: str,
    context_id: str | None,
    metadata: dict[str, Any] | None,
    validate_message: ValidateMessageFn,
    logger: Any,
    log_extra: dict[str, Any],
    on_complete: StreamTextCallbackFn | None = None,
    on_complete_metadata: StreamMetadataCallbackFn | None = None,
    on_error: StreamTextCallbackFn | None = None,
    on_event: StreamEventPayloadCallbackFn | None = None,
    on_finalized: StreamFinalizedCallbackFn | None = None,
    on_session_started: StreamSessionStartedCallbackFn | None = None,
    resume_from_sequence: int | None = None,
    cache_key: str | None = None,
) -> StreamingResponse:
    from app.features.invoke.stream_cache.memory_cache import global_stream_cache

    async def event_generator() -> Any:
        stream_text_accumulator = accumulator_factory()
        stream_failed = False
        client_disconnected = False
        started_at = time.monotonic()
        last_event_at = started_at
        terminal_event_seen = False
        final_outcome: StreamOutcome | None = None
        heartbeat_interval_seconds = runtime._stream_heartbeat_interval_seconds()
        log_warning = getattr(logger, "warning", None)
        log_info = getattr(logger, "info", None)
        non_contract_drop_reasons: set[str] = set()

        seq_counter = 0
        if resume_from_sequence is not None and cache_key:
            cached_events = await global_stream_cache.get_events_with_sequence_after(
                cache_key, resume_from_sequence
            )
            for cached_sequence, cached_event in cached_events:
                parsed_sequence = (
                    stream_payloads.extract_stream_sequence_from_serialized_event(
                        cached_event
                    )
                )
                if parsed_sequence is not None:
                    seq_counter = max(seq_counter, parsed_sequence)
                else:
                    seq_counter = max(seq_counter, cached_sequence)
                stream_text_accumulator.consume(cached_event)
                yield f"data: {json_dumps(cached_event, ensure_ascii=False)}\n\n"

            seq_counter = max(seq_counter, resume_from_sequence)
        serialized: dict[str, Any] = {}

        try:
            async for event in runtime._iter_stream_events_with_heartbeat(
                runtime._iter_gateway_stream(
                    gateway=gateway,
                    invoke_session=invoke_session,
                    resolved=resolved,
                    query=query,
                    context_id=context_id,
                    metadata=metadata,
                    on_session_started=on_session_started,
                ),
                heartbeat_interval_seconds=heartbeat_interval_seconds,
            ):
                if event is None:
                    last_event_at = time.monotonic()
                    yield runtime._SSE_HEARTBEAT_FRAME
                    continue
                serialized = runtime.serialize_stream_event(
                    event, validate_message=validate_message
                )
                validation_errors = extract_artifact_validation_errors(
                    serialized,
                    validate_message=validate_message,
                )
                if validation_errors:
                    logger.warning(
                        "Dropped invalid stream event",
                        extra={
                            **log_extra,
                            "validation_error_count": len(validation_errors),
                            "validation_errors_sample": (
                                build_validation_errors_log_sample(validation_errors)
                            ),
                            "artifact_update_sample": (
                                build_artifact_update_log_sample(serialized)
                            ),
                        },
                    )
                    continue
                stream_block, non_contract_reason = (
                    runtime._analyze_stream_chunk_contract(serialized)
                )
                warn_non_contract_artifact_update_once(
                    seen_reasons=non_contract_drop_reasons,
                    reason=non_contract_reason,
                    payload=serialized,
                    log_warning=log_warning,
                    log_info=log_info,
                    log_extra=log_extra,
                )

                event_sequence = seq_counter + 1
                if (
                    resume_from_sequence is not None
                    and event_sequence <= resume_from_sequence
                ):
                    continue
                seq_counter = max(seq_counter, event_sequence)

                await runtime._call_callback(on_event, serialized)
                runtime._ensure_outbound_stream_contract(
                    serialized, event_sequence=event_sequence
                )
                if cache_key:
                    await global_stream_cache.append_event(
                        cache_key, serialized, seq_counter
                    )
                stream_text_accumulator.consume(serialized, stream_block=stream_block)
                last_event_at = time.monotonic()
                yield f"data: {json_dumps(serialized, ensure_ascii=False)}\n\n"
                if runtime._is_terminal_status_event(serialized):
                    terminal_event_seen = True
                    break
        except asyncio.CancelledError:
            client_disconnected = True
            final_outcome = StreamOutcome(
                success=False,
                finish_reason=StreamFinishReason.CLIENT_DISCONNECT,
                final_text=stream_text_accumulator.result() or "",
                error_message=None,
                error_code=None,
                elapsed_seconds=time.monotonic() - started_at,
                idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                terminal_event_seen=terminal_event_seen,
            )
            raise
        except Exception as exc:
            stream_failed = True
            logger.warning("A2A SSE stream failed", exc_info=True, extra=log_extra)
            error_payload = runtime._build_stream_error_payload(exc)
            final_outcome = StreamOutcome(
                success=False,
                finish_reason=StreamFinishReason.UPSTREAM_ERROR,
                final_text=stream_text_accumulator.result() or "",
                error_message=runtime._STREAM_ERROR_MESSAGE,
                error_code=error_payload.error_code,
                elapsed_seconds=time.monotonic() - started_at,
                idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                terminal_event_seen=False,
                source=error_payload.source,
                jsonrpc_code=error_payload.jsonrpc_code,
                missing_params=error_payload.missing_params,
                upstream_error=error_payload.upstream_error,
            )
            await runtime._call_callback(on_error, runtime._STREAM_ERROR_MESSAGE)
            yield (
                "event: error\n"
                f"data: {json_dumps(error_payload.as_event_data(), ensure_ascii=False)}\n\n"
            )
        finally:
            if cache_key and runtime._is_terminal_status_event(serialized):
                await global_stream_cache.mark_completed(cache_key)
            if not stream_failed and not client_disconnected:
                final_text = stream_text_accumulator.result()
                await runtime._call_callback(on_complete_metadata, {})
                await runtime._call_callback(on_complete, final_text)
                final_outcome = StreamOutcome(
                    success=True,
                    finish_reason=StreamFinishReason.SUCCESS,
                    final_text=final_text,
                    error_message=None,
                    error_code=None,
                    elapsed_seconds=time.monotonic() - started_at,
                    idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                    terminal_event_seen=terminal_event_seen,
                )
            finalization_event: dict[str, Any] | None = None
            if final_outcome is not None:
                finalized_callback_result = await runtime._call_callback_safely(
                    on_finalized,
                    final_outcome,
                    logger=logger,
                    log_extra=log_extra,
                    warning_message="A2A SSE finalized callback failed",
                )
                if isinstance(finalized_callback_result, dict):
                    finalization_event = finalized_callback_result
            if finalization_event is not None and not client_disconnected:
                yield f"data: {json_dumps(finalization_event, ensure_ascii=False)}\n\n"
            if not client_disconnected:
                yield "event: stream_end\ndata: {}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store, no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def stream_ws(
    runtime: Any,
    *,
    accumulator_factory: Callable[[], Any],
    websocket: WebSocket,
    gateway: Any,
    resolved: Any,
    query: str,
    context_id: str | None,
    metadata: dict[str, Any] | None,
    validate_message: ValidateMessageFn,
    logger: Any,
    log_extra: dict[str, Any],
    on_complete: StreamTextCallbackFn | None = None,
    on_complete_metadata: StreamMetadataCallbackFn | None = None,
    on_error: StreamTextCallbackFn | None = None,
    on_event: StreamEventPayloadCallbackFn | None = None,
    on_error_metadata: StreamErrorMetadataCallbackFn | None = None,
    on_finalized: StreamFinalizedCallbackFn | None = None,
    on_session_started: StreamSessionStartedCallbackFn | None = None,
    send_stream_end: bool = True,
    resume_from_sequence: int | None = None,
    cache_key: str | None = None,
) -> None:
    from app.features.invoke.stream_cache.memory_cache import global_stream_cache

    stream_text_accumulator = accumulator_factory()
    client_disconnected = False
    started_at = time.monotonic()
    last_event_at = started_at
    terminal_event_seen = False
    final_outcome: StreamOutcome | None = None
    heartbeat_interval_seconds = runtime._stream_heartbeat_interval_seconds()
    log_warning = getattr(logger, "warning", None)
    log_info = getattr(logger, "info", None)
    non_contract_drop_reasons: set[str] = set()

    seq_counter = 0
    if resume_from_sequence is not None and cache_key:
        cached_events = await global_stream_cache.get_events_with_sequence_after(
            cache_key, resume_from_sequence
        )
        for cached_sequence, cached_event in cached_events:
            parsed_sequence = (
                stream_payloads.extract_stream_sequence_from_serialized_event(
                    cached_event
                )
            )
            if parsed_sequence is not None:
                seq_counter = max(seq_counter, parsed_sequence)
            else:
                seq_counter = max(seq_counter, cached_sequence)
            stream_text_accumulator.consume(cached_event)
            await websocket.send_text(json_dumps(cached_event, ensure_ascii=False))

        seq_counter = max(seq_counter, resume_from_sequence)

    serialized: dict[str, Any] = {}
    try:
        async for event in runtime._iter_stream_events_with_heartbeat(
            runtime._iter_gateway_stream(
                gateway=gateway,
                invoke_session=None,
                resolved=resolved,
                query=query,
                context_id=context_id,
                metadata=metadata,
                on_session_started=on_session_started,
            ),
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        ):
            if event is None:
                last_event_at = time.monotonic()
                await websocket.send_text(
                    json_dumps(runtime._WS_HEARTBEAT_EVENT, ensure_ascii=False)
                )
                continue
            serialized = runtime.serialize_stream_event(
                event, validate_message=validate_message
            )
            validation_errors = extract_artifact_validation_errors(
                serialized,
                validate_message=validate_message,
            )
            if validation_errors:
                logger.warning(
                    "Dropped invalid stream event",
                    extra={
                        **log_extra,
                        "validation_error_count": len(validation_errors),
                        "validation_errors_sample": (
                            build_validation_errors_log_sample(validation_errors)
                        ),
                        "artifact_update_sample": (
                            build_artifact_update_log_sample(serialized)
                        ),
                    },
                )
                continue
            stream_block, non_contract_reason = runtime._analyze_stream_chunk_contract(
                serialized
            )
            warn_non_contract_artifact_update_once(
                seen_reasons=non_contract_drop_reasons,
                reason=non_contract_reason,
                payload=serialized,
                log_warning=log_warning,
                log_info=log_info,
                log_extra=log_extra,
            )

            event_sequence = seq_counter + 1
            if (
                resume_from_sequence is not None
                and event_sequence <= resume_from_sequence
            ):
                continue
            seq_counter = max(seq_counter, event_sequence)

            await runtime._call_callback(on_event, serialized)
            runtime._ensure_outbound_stream_contract(
                serialized, event_sequence=event_sequence
            )
            if cache_key:
                await global_stream_cache.append_event(
                    cache_key, serialized, seq_counter
                )
            stream_text_accumulator.consume(serialized, stream_block=stream_block)
            last_event_at = time.monotonic()
            await websocket.send_text(json_dumps(serialized, ensure_ascii=False))
            if runtime._is_terminal_status_event(serialized):
                terminal_event_seen = True
                break
        final_text = stream_text_accumulator.result()
        await runtime._call_callback(on_complete_metadata, {})
        await runtime._call_callback(on_complete, final_text)
        final_outcome = StreamOutcome(
            success=True,
            finish_reason=StreamFinishReason.SUCCESS,
            final_text=final_text,
            error_message=None,
            error_code=None,
            elapsed_seconds=time.monotonic() - started_at,
            idle_seconds=max(time.monotonic() - last_event_at, 0.0),
            terminal_event_seen=terminal_event_seen,
        )
    except asyncio.CancelledError:
        client_disconnected = True
        final_outcome = StreamOutcome(
            success=False,
            finish_reason=StreamFinishReason.CLIENT_DISCONNECT,
            final_text=stream_text_accumulator.result() or "",
            error_message=None,
            error_code=None,
            elapsed_seconds=time.monotonic() - started_at,
            idle_seconds=max(time.monotonic() - last_event_at, 0.0),
            terminal_event_seen=terminal_event_seen,
        )
        raise
    except Exception as exc:
        if runtime._is_client_disconnect_error(exc):
            client_disconnected = True
            logger.info("A2A WS client disconnected", extra=log_extra)
            final_outcome = StreamOutcome(
                success=False,
                finish_reason=StreamFinishReason.CLIENT_DISCONNECT,
                final_text=stream_text_accumulator.result() or "",
                error_message=None,
                error_code=None,
                elapsed_seconds=time.monotonic() - started_at,
                idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                terminal_event_seen=terminal_event_seen,
            )
            return
        logger.warning("A2A WS stream failed", exc_info=True, extra=log_extra)
        error_payload = runtime._build_stream_error_payload(exc)
        final_outcome = StreamOutcome(
            success=False,
            finish_reason=StreamFinishReason.UPSTREAM_ERROR,
            final_text=stream_text_accumulator.result() or "",
            error_message=runtime._STREAM_ERROR_MESSAGE,
            error_code=error_payload.error_code,
            elapsed_seconds=time.monotonic() - started_at,
            idle_seconds=max(time.monotonic() - last_event_at, 0.0),
            terminal_event_seen=False,
            source=error_payload.source,
            jsonrpc_code=error_payload.jsonrpc_code,
            missing_params=error_payload.missing_params,
            upstream_error=error_payload.upstream_error,
        )
        await runtime._call_callback(on_error, runtime._STREAM_ERROR_MESSAGE)
        await runtime._call_callback(on_error_metadata, error_payload.as_event_data())
        await runtime.send_ws_error(
            websocket,
            message=error_payload.message,
            error_code=error_payload.error_code,
            source=error_payload.source,
            jsonrpc_code=error_payload.jsonrpc_code,
            missing_params=list(error_payload.missing_params or []),
            upstream_error=error_payload.upstream_error,
        )
    finally:
        if cache_key and runtime._is_terminal_status_event(serialized):
            await global_stream_cache.mark_completed(cache_key)
        finalization_event: dict[str, Any] | None = None
        if final_outcome is not None:
            finalized_callback_result = await runtime._call_callback_safely(
                on_finalized,
                final_outcome,
                logger=logger,
                log_extra=log_extra,
                warning_message="A2A WS finalized callback failed",
            )
            if isinstance(finalized_callback_result, dict):
                finalization_event = finalized_callback_result
        if finalization_event is not None and not client_disconnected:
            await websocket.send_text(
                json_dumps(finalization_event, ensure_ascii=False)
            )
        if send_stream_end and not client_disconnected:
            await runtime.send_ws_stream_end(websocket)
