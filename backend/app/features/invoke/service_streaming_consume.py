"""Blocking stream consumption helpers for invoke service."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

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


async def consume_stream(
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
    on_error_metadata: StreamErrorMetadataCallbackFn | None = None,
    on_finalized: StreamFinalizedCallbackFn | None = None,
    on_session_started: StreamSessionStartedCallbackFn | None = None,
    idle_timeout_seconds: float | None = None,
    total_timeout_seconds: float | None = None,
) -> StreamOutcome:
    stream_text_accumulator = accumulator_factory()
    log_warning = getattr(logger, "warning", None)
    log_info = getattr(logger, "info", None)
    non_contract_drop_reasons: set[str] = set()
    started_at = time.monotonic()
    last_event_at = started_at
    heartbeat_interval_seconds = runtime._stream_heartbeat_interval_seconds()
    stream_iter = runtime._iter_stream_events_with_heartbeat(
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
    ).__aiter__()
    terminal_event_seen = False
    event_sequence = 0
    idle_timeout = (
        float(idle_timeout_seconds)
        if idle_timeout_seconds is not None and idle_timeout_seconds > 0
        else None
    )
    total_timeout = (
        float(total_timeout_seconds)
        if total_timeout_seconds is not None and total_timeout_seconds > 0
        else None
    )

    def _resolve_wait_timeout(now: float) -> float | None:
        wait_timeout = idle_timeout
        if total_timeout is not None:
            remaining_total = total_timeout - (now - started_at)
            if remaining_total <= 0:
                return 0.0
            return (
                min(wait_timeout, remaining_total)
                if wait_timeout is not None
                else remaining_total
            )
        return wait_timeout

    try:
        while True:
            now = time.monotonic()
            if total_timeout is not None and (now - started_at) >= (
                total_timeout - 1e-9
            ):
                timeout_message = f"A2A stream total timeout after {total_timeout:.1f}s"
                outcome = StreamOutcome(
                    success=False,
                    finish_reason=StreamFinishReason.TIMEOUT_TOTAL,
                    final_text=stream_text_accumulator.result() or "",
                    error_message=timeout_message,
                    error_code="timeout",
                    elapsed_seconds=time.monotonic() - started_at,
                    idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                    terminal_event_seen=False,
                    internal_error_message=timeout_message,
                )
                await runtime._call_callback(on_error, timeout_message)
                await runtime._call_callback(
                    on_error_metadata,
                    {"message": timeout_message, "error_code": "timeout"},
                )
                await runtime._call_callback_safely(
                    on_finalized,
                    outcome,
                    logger=logger,
                    log_extra=log_extra,
                    warning_message="A2A consume stream finalized callback failed",
                )
                return outcome
            wait_timeout = _resolve_wait_timeout(now)
            try:
                if wait_timeout is None:
                    event = await anext(stream_iter)
                else:
                    event = await asyncio.wait_for(anext(stream_iter), wait_timeout)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                is_total_timeout = total_timeout is not None and (
                    time.monotonic() - started_at
                ) >= (total_timeout - 1e-9)
                if is_total_timeout:
                    timeout_message = (
                        f"A2A stream total timeout after {total_timeout:.1f}s"
                    )
                    finish_reason = StreamFinishReason.TIMEOUT_TOTAL
                else:
                    idle_value = idle_timeout if idle_timeout is not None else 0.0
                    timeout_message = f"A2A stream idle timeout after {idle_value:.1f}s"
                    finish_reason = StreamFinishReason.TIMEOUT_IDLE
                outcome = StreamOutcome(
                    success=False,
                    finish_reason=finish_reason,
                    final_text=stream_text_accumulator.result() or "",
                    error_message=timeout_message,
                    error_code="timeout",
                    elapsed_seconds=time.monotonic() - started_at,
                    idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                    terminal_event_seen=False,
                    internal_error_message=timeout_message,
                )
                await runtime._call_callback(on_error, timeout_message)
                await runtime._call_callback(
                    on_error_metadata,
                    {"message": timeout_message, "error_code": "timeout"},
                )
                await runtime._call_callback_safely(
                    on_finalized,
                    outcome,
                    logger=logger,
                    log_extra=log_extra,
                    warning_message="A2A consume stream finalized callback failed",
                )
                return outcome
            if event is None:
                last_event_at = time.monotonic()
                continue

            serialized = runtime.serialize_stream_event(
                event, validate_message=validate_message
            )
            event_sequence += 1
            runtime._ensure_outbound_stream_contract(
                serialized, event_sequence=event_sequence
            )
            validation_errors = extract_artifact_validation_errors(
                serialized,
                validate_message=validate_message,
            )
            if validation_errors:
                warning_payload = {
                    **log_extra,
                    "validation_error_count": len(validation_errors),
                    "validation_errors_sample": build_validation_errors_log_sample(
                        validation_errors
                    ),
                    "artifact_update_sample": build_artifact_update_log_sample(
                        serialized
                    ),
                }
                if callable(log_warning):
                    log_warning(
                        "Dropped invalid stream event",
                        extra=warning_payload,
                    )
                elif callable(log_info):
                    log_info(
                        "Dropped invalid stream event",
                        extra=warning_payload,
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

            last_event_at = time.monotonic()
            await runtime._call_callback(on_event, serialized)
            runtime._ensure_outbound_stream_contract(
                serialized, event_sequence=event_sequence
            )
            stream_text_accumulator.consume(serialized, stream_block=stream_block)
            if runtime._is_terminal_status_event(serialized):
                terminal_event_seen = True
                break

        await runtime._call_callback(on_complete_metadata, {})
        final_text = stream_text_accumulator.result()
        await runtime._call_callback(on_complete, final_text)
        outcome = StreamOutcome(
            success=True,
            finish_reason=StreamFinishReason.SUCCESS,
            final_text=final_text,
            error_message=None,
            error_code=None,
            elapsed_seconds=time.monotonic() - started_at,
            idle_seconds=max(time.monotonic() - last_event_at, 0.0),
            terminal_event_seen=terminal_event_seen,
        )
        await runtime._call_callback_safely(
            on_finalized,
            outcome,
            logger=logger,
            log_extra=log_extra,
            warning_message="A2A consume stream finalized callback failed",
        )
        return outcome
    except asyncio.CancelledError:
        outcome = StreamOutcome(
            success=False,
            finish_reason=StreamFinishReason.CLIENT_DISCONNECT,
            final_text=stream_text_accumulator.result() or "",
            error_message=None,
            error_code=None,
            elapsed_seconds=time.monotonic() - started_at,
            idle_seconds=max(time.monotonic() - last_event_at, 0.0),
            terminal_event_seen=terminal_event_seen,
        )
        await runtime._call_callback_safely(
            on_finalized,
            outcome,
            logger=logger,
            log_extra=log_extra,
            warning_message="A2A consume stream finalized callback failed",
        )
        raise
    except Exception as exc:
        if callable(log_warning):
            log_warning("A2A consume stream failed", exc_info=True, extra=log_extra)
        elif callable(log_info):
            log_info("A2A consume stream failed", exc_info=True, extra=log_extra)
        error_payload = runtime._build_stream_error_payload(exc)
        outcome = StreamOutcome(
            success=False,
            finish_reason=StreamFinishReason.UPSTREAM_ERROR,
            final_text=stream_text_accumulator.result() or "",
            error_message=runtime._STREAM_ERROR_MESSAGE,
            error_code=error_payload.error_code,
            elapsed_seconds=time.monotonic() - started_at,
            idle_seconds=max(time.monotonic() - last_event_at, 0.0),
            terminal_event_seen=False,
            internal_error_message=runtime._extract_internal_error_message(exc),
            source=error_payload.source,
            jsonrpc_code=error_payload.jsonrpc_code,
            missing_params=error_payload.missing_params,
            upstream_error=error_payload.upstream_error,
        )
        await runtime._call_callback(on_error, runtime._STREAM_ERROR_MESSAGE)
        await runtime._call_callback(on_error_metadata, error_payload.as_event_data())
        await runtime._call_callback_safely(
            on_finalized,
            outcome,
            logger=logger,
            log_extra=log_extra,
            warning_message="A2A consume stream finalized callback failed",
        )
        return outcome
