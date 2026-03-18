"""Shared helpers for invoking A2A agents across different catalogs.

The hub (admin-managed) and user-managed A2A routes should share streaming
transport logic to keep behavior consistent and reduce drift.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncIterator, Callable

from a2a.client.client import ClientEvent
from a2a.types import Message
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.services.a2a_payload_analysis import (
    PayloadAnalysis,
)
from app.services.a2a_payload_analysis import analyze_payload as analyze_payload_object
from app.services.a2a_payload_analysis import (
    coerce_payload_to_dict as coerce_payload_object,
)
from app.services.a2a_payload_analysis import (
    extract_binding_hints_from_invoke_result as extract_binding_hints_from_result,
)
from app.services.a2a_payload_analysis import (
    extract_binding_hints_from_serialized_event as extract_binding_hints_from_event,
)
from app.services.a2a_payload_analysis import (
    extract_preferred_text_from_payload as extract_preferred_text,
)
from app.services.a2a_payload_analysis import (
    extract_readable_content_from_invoke_result as extract_readable_content_from_result,
)
from app.services.a2a_payload_analysis import (
    extract_stream_identity_hints_from_invoke_result as extract_stream_identity_hints_from_result,
)
from app.services.a2a_payload_analysis import (
    extract_stream_identity_hints_from_serialized_event as extract_stream_identity_hints_from_event,
)
from app.services.a2a_payload_analysis import (
    extract_usage_hints_from_invoke_result as extract_usage_hints_from_result,
)
from app.services.a2a_payload_analysis import (
    extract_usage_hints_from_serialized_event as extract_usage_hints_from_event,
)
from app.services.a2a_stream_diagnostics import (
    build_artifact_update_log_sample,
    build_validation_errors_log_sample,
    extract_artifact_validation_errors,
    warn_non_contract_artifact_update_once,
)
from app.services.a2a_stream_payloads import (
    analyze_stream_chunk_contract,
    extract_artifact_source,
    extract_artifact_type,
    extract_interrupt_lifecycle_from_serialized_event,
    extract_shared_stream_metadata,
    extract_stream_chunk_from_serialized_event,
    extract_stream_sequence_from_serialized_event,
    extract_stream_text_from_parts,
)
from app.utils.json_encoder import json_dumps
from app.utils.payload_extract import as_dict

logger = logging.getLogger(__name__)

StreamEvent = ClientEvent | Message
ValidateMessageFn = Callable[[dict[str, Any]], list[Any]]
StreamTextCallbackFn = Callable[[str], Any]
StreamEventPayloadCallbackFn = Callable[[dict[str, Any]], Any]
StreamMetadataCallbackFn = Callable[[dict[str, Any]], Any]
StreamErrorMetadataCallbackFn = Callable[[dict[str, Any]], Any]


class StreamFinishReason(str, Enum):
    SUCCESS = "success"
    TIMEOUT_TOTAL = "timeout_total"
    TIMEOUT_IDLE = "timeout_idle"
    UPSTREAM_ERROR = "upstream_error"
    CLIENT_DISCONNECT = "client_disconnect"


@dataclass(frozen=True)
class StreamOutcome:
    success: bool
    finish_reason: StreamFinishReason
    final_text: str
    error_message: str | None
    error_code: str | None
    elapsed_seconds: float
    idle_seconds: float
    terminal_event_seen: bool
    internal_error_message: str | None = None


StreamFinalizedCallbackFn = Callable[[StreamOutcome], Any]


class A2AInvokeService:
    """Transport-level helpers for blocking/SSE/WS A2A invocation."""

    # Keep client-facing stream errors generic. Internal errors go to logs.
    _STREAM_ERROR_MESSAGE = "Upstream streaming failed"
    _STREAM_ERROR_CODE = "upstream_stream_error"
    _SSE_HEARTBEAT_FRAME = ": keep-alive\n\n"
    _WS_HEARTBEAT_EVENT = {"event": "heartbeat", "data": {}}
    _WS_STREAM_END_EVENT = {"event": "stream_end", "data": {}}
    _ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,64}$")

    @classmethod
    def build_ws_error_event(
        cls,
        *,
        message: str,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"message": message}
        if error_code:
            data["error_code"] = error_code
        return {"event": "error", "data": data}

    async def send_ws_error(
        self,
        websocket: WebSocket,
        *,
        message: str,
        error_code: str | None = None,
    ) -> None:
        try:
            await websocket.send_text(
                json_dumps(
                    self.build_ws_error_event(message=message, error_code=error_code),
                    ensure_ascii=False,
                )
            )
        except Exception as exc:
            if self._is_client_disconnect_error(exc):
                return
            raise

    async def send_ws_stream_end(self, websocket: WebSocket) -> None:
        try:
            await websocket.send_text(
                json_dumps(self._WS_STREAM_END_EVENT, ensure_ascii=False)
            )
        except Exception as exc:
            if self._is_client_disconnect_error(exc):
                return
            raise

    @staticmethod
    def _is_client_disconnect_error(exc: Exception) -> bool:
        if isinstance(exc, WebSocketDisconnect):
            return True
        class_name = exc.__class__.__name__
        if class_name in {
            "ClientDisconnected",
            "ConnectionClosed",
            "ConnectionClosedOK",
        }:
            return True
        if (
            isinstance(exc, RuntimeError)
            and "close message has been sent" in str(exc).lower()
        ):
            return True
        return False

    @staticmethod
    async def _call_callback(callback: Callable[[Any], Any] | None, value: Any) -> None:
        if callback is None:
            return
        outcome = callback(value)
        if inspect.isawaitable(outcome):
            await outcome

    @staticmethod
    async def _call_callback_safely(
        callback: Callable[[Any], Any] | None,
        value: Any,
        *,
        logger: Any,
        log_extra: dict[str, Any],
        warning_message: str,
    ) -> None:
        try:
            await A2AInvokeService._call_callback(callback, value)
        except Exception:
            log_warning = getattr(logger, "warning", None)
            if callable(log_warning):
                log_warning(warning_message, exc_info=True, extra=log_extra)
                return
            logging.getLogger(__name__).warning(
                warning_message,
                exc_info=True,
                extra=log_extra,
            )

    @classmethod
    def analyze_payload(cls, payload: dict[str, Any]) -> PayloadAnalysis:
        return analyze_payload_object(payload)

    @classmethod
    def _extract_stream_sequence_from_serialized_event(
        cls, payload: dict[str, Any]
    ) -> int | None:
        return extract_stream_sequence_from_serialized_event(payload)

    @staticmethod
    def _pick_non_empty_str(
        payload: dict[str, Any],
        keys: tuple[str, ...],
    ) -> str | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _pick_int(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)
            if isinstance(value, str) and value.strip().lstrip("-").isdigit():
                return int(value.strip())
        return None

    @classmethod
    def extract_binding_hints_from_serialized_event(
        cls, payload: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any]]:
        return extract_binding_hints_from_event(payload)

    @classmethod
    def extract_stream_identity_hints_from_serialized_event(
        cls, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return extract_stream_identity_hints_from_event(payload)

    @classmethod
    def extract_usage_hints_from_serialized_event(
        cls, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return extract_usage_hints_from_event(payload)

    @classmethod
    def extract_interrupt_lifecycle_from_serialized_event(
        cls, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        return extract_interrupt_lifecycle_from_serialized_event(payload)

    @classmethod
    def extract_stream_chunk_from_serialized_event(
        cls, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        return extract_stream_chunk_from_serialized_event(payload)

    @classmethod
    def _coerce_payload_to_dict(cls, payload: Any) -> dict[str, Any]:
        return coerce_payload_object(payload)

    @classmethod
    def extract_binding_hints_from_invoke_result(
        cls, result: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any]]:
        return extract_binding_hints_from_result(result)

    @classmethod
    def extract_stream_identity_hints_from_invoke_result(
        cls, result: dict[str, Any]
    ) -> dict[str, Any]:
        return extract_stream_identity_hints_from_result(result)

    @classmethod
    def extract_usage_hints_from_invoke_result(
        cls, result: dict[str, Any]
    ) -> dict[str, Any]:
        return extract_usage_hints_from_result(result)

    @staticmethod
    def _extract_text_from_parts(parts: Any) -> str | None:
        resolved = extract_stream_text_from_parts(parts)
        return resolved or None

    @classmethod
    def _extract_preferred_text_from_payload(cls, payload: Any) -> str | None:
        return extract_preferred_text(payload)

    @classmethod
    def extract_readable_content_from_invoke_result(
        cls, result: dict[str, Any]
    ) -> str | None:
        return extract_readable_content_from_result(result)

    class _StreamTextAccumulator:
        """Accumulates stream text for persistence.

        For typed artifact updates:
        - aggregate ordered message blocks by `block_type`
        - same type appends; switched type starts a new block
        - preserve append/overwrite semantics per update
        - accepted values: `text`, `reasoning`, `tool_call`

        """

        def __init__(self) -> None:
            self._blocks: list[dict[str, Any]] = []
            self._block_seq = 0

        @staticmethod
        def _extract_text_from_parts(parts: Any) -> str:
            return extract_stream_text_from_parts(parts)

        @staticmethod
        def _extract_shared_stream_metadata(
            payload: dict[str, Any], artifact: dict[str, Any]
        ) -> dict[str, Any]:
            return extract_shared_stream_metadata(payload, artifact)

        @staticmethod
        def _extract_artifact_type(
            payload: dict[str, Any], artifact: dict[str, Any]
        ) -> str | None:
            return extract_artifact_type(payload, artifact)

        @staticmethod
        def _extract_artifact_source(
            payload: dict[str, Any], artifact: dict[str, Any]
        ) -> str | None:
            return extract_artifact_source(payload, artifact)

        def _push_new_block(self, block_type: str, delta: str, done: bool) -> None:
            now = self._block_seq
            self._block_seq += 1
            self._blocks.append(
                {
                    "id": f"block-{now + 1}",
                    "type": block_type,
                    "content": delta,
                    "is_finished": done,
                    "seq": now,
                }
            )

        def _apply_block_update(
            self,
            *,
            block_type: str,
            delta: str,
            append: bool,
            done: bool,
            source: str | None,
        ) -> None:
            if not delta:
                return
            overwrite = (not append) or source == "final_snapshot"
            last = self._blocks[-1] if self._blocks else None

            if overwrite:
                if (
                    isinstance(last, dict)
                    and last.get("type") == block_type
                    and last.get("is_finished") is False
                ):
                    last["content"] = delta
                    last["is_finished"] = done
                    return
                if isinstance(last, dict) and last.get("is_finished") is False:
                    last["is_finished"] = True
                self._push_new_block(block_type, delta, done)
                return

            if (
                isinstance(last, dict)
                and last.get("type") == block_type
                and last.get("is_finished") is False
            ):
                current = last.get("content")
                last["content"] = (
                    f"{current if isinstance(current, str) else ''}{delta}"
                )
                last["is_finished"] = done
                return

            if isinstance(last, dict) and last.get("is_finished") is False:
                last["is_finished"] = True
            self._push_new_block(block_type, delta, done)

        def consume(
            self,
            payload: dict[str, Any],
            *,
            stream_block: dict[str, Any] | None = None,
        ) -> None:
            resolved_stream_block = stream_block
            if resolved_stream_block is None:
                resolved_stream_block = (
                    A2AInvokeService.extract_stream_chunk_from_serialized_event(payload)
                )
            if not resolved_stream_block:
                return
            block_type = resolved_stream_block.get("block_type")
            delta = resolved_stream_block.get("content")
            if not isinstance(block_type, str) or not isinstance(delta, str):
                return
            self._apply_block_update(
                block_type=block_type,
                delta=delta,
                append=bool(resolved_stream_block.get("append", True)),
                done=bool(resolved_stream_block.get("is_finished", False)),
                source=(
                    str(resolved_stream_block.get("source"))
                    if isinstance(resolved_stream_block.get("source"), str)
                    else None
                ),
            )

        def result(self) -> str:
            return "".join(
                block.get("content", "")
                for block in self._blocks
                if block.get("type") == "text" and isinstance(block.get("content"), str)
            )

    @staticmethod
    def serialize_stream_event(
        event: StreamEvent, *, validate_message: ValidateMessageFn
    ) -> dict[str, Any]:
        from app.core.config import settings

        if isinstance(event, tuple):
            resolved = event[1] if event[1] else event[0]
        else:
            resolved = event

        if isinstance(resolved, dict):
            payload = dict(resolved)
        else:
            payload = resolved.model_dump(exclude_none=True)
        if settings.debug:
            payload["validation_errors"] = validate_message(payload)
        return payload

    @classmethod
    def _analyze_stream_chunk_contract(
        cls, payload: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None]:
        return analyze_stream_chunk_contract(payload)

    @staticmethod
    def _is_terminal_status_event(payload: dict[str, Any]) -> bool:
        return payload.get("kind") == "status-update" and payload.get("final") is True

    @classmethod
    def _ensure_outbound_stream_contract(
        cls,
        payload: dict[str, Any],
        *,
        event_sequence: int,
    ) -> None:
        if payload.get("kind") != "artifact-update":
            return
        if cls._pick_int(payload, ("seq",)) is None:
            payload["seq"] = event_sequence

        artifact = as_dict(payload.get("artifact"))
        artifact_metadata = as_dict(artifact.get("metadata"))
        root_metadata = as_dict(payload.get("metadata"))
        shared_stream = cls._StreamTextAccumulator._extract_shared_stream_metadata(
            payload, artifact
        )

        message_id = None
        for candidate in (
            payload,
            artifact,
            artifact_metadata,
            root_metadata,
            shared_stream,
        ):
            if message_id is None:
                message_id = cls._pick_non_empty_str(
                    candidate, ("message_id", "messageId")
                )
        if (
            message_id
            and cls._pick_non_empty_str(payload, ("message_id", "messageId")) is None
        ):
            payload["message_id"] = message_id

        event_id = None
        for candidate in (
            payload,
            artifact,
            artifact_metadata,
            root_metadata,
            shared_stream,
        ):
            if event_id is None:
                event_id = cls._pick_non_empty_str(candidate, ("event_id", "eventId"))
        payload["event_id"] = event_id or (
            f"{message_id}:{event_sequence}"
            if message_id
            else f"stream:{event_sequence}"
        )

    @staticmethod
    def _stream_heartbeat_interval_seconds() -> float:
        from app.core.config import settings

        interval = float(settings.a2a_stream_heartbeat_interval)
        if interval <= 0:
            return 0.0
        return interval

    @classmethod
    def _extract_error_code_from_exception(cls, exc: BaseException) -> str | None:
        if isinstance(exc, asyncio.TimeoutError):
            return "timeout"

        candidate = getattr(exc, "error_code", None)
        normalized = cls._normalize_error_code(candidate)
        if normalized is not None:
            return normalized

        detail = getattr(exc, "detail", None)
        normalized = cls._normalize_error_code(detail)
        if normalized is not None:
            return normalized

        candidate = getattr(exc, "code", None)
        normalized = cls._normalize_error_code(candidate)
        if normalized is not None:
            return normalized

        for arg in getattr(exc, "args", ()):
            if isinstance(arg, dict):
                mapped = arg.get("error_code") or arg.get("code")
                normalized = cls._normalize_error_code(mapped)
                if normalized is not None:
                    return normalized
                if isinstance(mapped, int):
                    return str(mapped)
            normalized = cls._normalize_error_code(arg)
            if normalized is not None:
                return normalized

        return None

    @classmethod
    def _normalize_error_code(cls, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        candidate = value.strip().replace("-", "_").lower()
        if not cls._ERROR_CODE_PATTERN.fullmatch(candidate):
            return None
        return candidate

    @staticmethod
    def _extract_internal_error_message(exc: BaseException) -> str | None:
        detail = getattr(exc, "detail", None)
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        message = str(exc).strip()
        return message or None

    async def _iter_stream_events_with_heartbeat(
        self,
        stream: AsyncIterator[StreamEvent],
        *,
        heartbeat_interval_seconds: float,
    ) -> AsyncIterator[StreamEvent | None]:
        stream_iter = stream.__aiter__()
        next_event_task: asyncio.Task[StreamEvent] = asyncio.create_task(
            anext(stream_iter)
        )
        try:
            while True:
                if heartbeat_interval_seconds > 0:
                    done, _ = await asyncio.wait(
                        {next_event_task},
                        timeout=heartbeat_interval_seconds,
                    )
                    if not done:
                        yield None
                        continue
                else:
                    await next_event_task

                try:
                    event = next_event_task.result()
                except StopAsyncIteration:
                    return

                next_event_task = asyncio.create_task(anext(stream_iter))
                yield event
        finally:
            if not next_event_task.done():
                next_event_task.cancel()
                with suppress(asyncio.CancelledError):
                    await next_event_task
            else:
                # Consume terminal StopAsyncIteration from finished tasks so event loop
                # doesn't emit "Task exception was never retrieved" warnings.
                with suppress(StopAsyncIteration, asyncio.CancelledError):
                    _ = next_event_task.result()

    def stream_sse(
        self,
        *,
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
        on_finalized: StreamFinalizedCallbackFn | None = None,
        resume_from_sequence: int | None = None,
        cache_key: str | None = None,
    ) -> StreamingResponse:
        from app.services.stream_cache.memory_cache import global_stream_cache

        async def event_generator() -> AsyncIterator[str]:
            stream_text_accumulator = self._StreamTextAccumulator()
            stream_failed = False
            client_disconnected = False
            started_at = time.monotonic()
            last_event_at = started_at
            terminal_event_seen = False
            final_outcome: StreamOutcome | None = None
            heartbeat_interval_seconds = self._stream_heartbeat_interval_seconds()
            log_warning = getattr(logger, "warning", None)
            log_info = getattr(logger, "info", None)
            non_contract_drop_reasons: set[str] = set()

            # Replay cached events if resuming
            seq_counter = 0
            if resume_from_sequence is not None and cache_key:
                cached_events = (
                    await global_stream_cache.get_events_with_sequence_after(
                        cache_key, resume_from_sequence
                    )
                )
                for cached_sequence, cached_event in cached_events:
                    parsed_sequence = (
                        self._extract_stream_sequence_from_serialized_event(
                            cached_event
                        )
                    )
                    if parsed_sequence is not None:
                        seq_counter = max(seq_counter, parsed_sequence)
                    else:
                        seq_counter = max(seq_counter, cached_sequence)
                    stream_text_accumulator.consume(cached_event)
                    yield f"data: {json_dumps(cached_event, ensure_ascii=False)}\n\n"

                # Continue generating sequence from max of cached or resumed
                seq_counter = max(seq_counter, resume_from_sequence)
            serialized = {}

            try:
                async for event in self._iter_stream_events_with_heartbeat(
                    gateway.stream(
                        resolved=resolved,
                        query=query,
                        context_id=context_id,
                        metadata=metadata,
                    ),
                    heartbeat_interval_seconds=heartbeat_interval_seconds,
                ):
                    if event is None:
                        last_event_at = time.monotonic()
                        yield self._SSE_HEARTBEAT_FRAME
                        continue
                    serialized = self.serialize_stream_event(
                        event, validate_message=validate_message
                    )
                    validation_errors = extract_artifact_validation_errors(
                        serialized,
                        validate_message=validate_message,
                    )
                    if validation_errors:
                        logger.warning(
                            "Dropped invalid artifact-update event",
                            extra={
                                **log_extra,
                                "validation_error_count": len(validation_errors),
                                "validation_errors_sample": build_validation_errors_log_sample(
                                    validation_errors
                                ),
                                "artifact_update_sample": build_artifact_update_log_sample(
                                    serialized
                                ),
                            },
                        )
                        continue
                    stream_block, non_contract_reason = (
                        self._analyze_stream_chunk_contract(serialized)
                    )
                    warn_non_contract_artifact_update_once(
                        seen_reasons=non_contract_drop_reasons,
                        reason=non_contract_reason,
                        payload=serialized,
                        log_warning=log_warning,
                        log_info=log_info,
                        log_extra=log_extra,
                    )

                    parsed_sequence = (
                        stream_block.get("seq")
                        if isinstance(stream_block, dict)
                        and isinstance(stream_block.get("seq"), int)
                        else self._extract_stream_sequence_from_serialized_event(
                            serialized
                        )
                    )
                    event_sequence = (
                        parsed_sequence
                        if parsed_sequence is not None
                        else seq_counter + 1
                    )
                    if event_sequence <= seq_counter:
                        event_sequence = seq_counter + 1

                    # If this event sequence was already replayed from cache, skip yielding it again
                    # This happens if upstream didn't support resume and gave us everything from start
                    if (
                        resume_from_sequence is not None
                        and event_sequence <= resume_from_sequence
                    ):
                        continue
                    seq_counter = max(seq_counter, event_sequence)

                    await self._call_callback(on_event, serialized)
                    self._ensure_outbound_stream_contract(
                        serialized, event_sequence=event_sequence
                    )
                    if cache_key:
                        await global_stream_cache.append_event(
                            cache_key, serialized, seq_counter
                        )
                    stream_text_accumulator.consume(
                        serialized, stream_block=stream_block
                    )
                    last_event_at = time.monotonic()
                    yield f"data: {json_dumps(serialized, ensure_ascii=False)}\n\n"
                    if self._is_terminal_status_event(serialized):
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
                error_code = (
                    self._extract_error_code_from_exception(exc)
                    or self._STREAM_ERROR_CODE
                )
                final_outcome = StreamOutcome(
                    success=False,
                    finish_reason=StreamFinishReason.UPSTREAM_ERROR,
                    final_text=stream_text_accumulator.result() or "",
                    error_message=self._STREAM_ERROR_MESSAGE,
                    error_code=error_code,
                    elapsed_seconds=time.monotonic() - started_at,
                    idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                    terminal_event_seen=False,
                )
                await self._call_callback(on_error, self._STREAM_ERROR_MESSAGE)
                error_payload = self.build_ws_error_event(
                    message=self._STREAM_ERROR_MESSAGE,
                    error_code=error_code,
                )
                yield (
                    "event: error\n"
                    f"data: {json_dumps(error_payload['data'], ensure_ascii=False)}\n\n"
                )
            finally:
                if cache_key and self._is_terminal_status_event(serialized):
                    await global_stream_cache.mark_completed(cache_key)
                if not stream_failed and not client_disconnected:
                    final_text = stream_text_accumulator.result()
                    await self._call_callback(
                        on_complete_metadata,
                        {},
                    )
                    await self._call_callback(on_complete, final_text)
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
                if final_outcome is not None:
                    await self._call_callback_safely(
                        on_finalized,
                        final_outcome,
                        logger=logger,
                        log_extra=log_extra,
                        warning_message="A2A SSE finalized callback failed",
                    )
                if not client_disconnected:
                    yield "event: stream_end\ndata: {}\n\n"

        # Ensure downstreams do not persist potentially sensitive content.
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
        self,
        *,
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
        send_stream_end: bool = True,
        resume_from_sequence: int | None = None,
        cache_key: str | None = None,
    ) -> None:
        from app.services.stream_cache.memory_cache import global_stream_cache

        stream_text_accumulator = self._StreamTextAccumulator()
        client_disconnected = False
        started_at = time.monotonic()
        last_event_at = started_at
        terminal_event_seen = False
        final_outcome: StreamOutcome | None = None
        heartbeat_interval_seconds = self._stream_heartbeat_interval_seconds()
        log_warning = getattr(logger, "warning", None)
        log_info = getattr(logger, "info", None)
        non_contract_drop_reasons: set[str] = set()

        # Replay cached events if resuming
        seq_counter = 0
        if resume_from_sequence is not None and cache_key:
            cached_events = await global_stream_cache.get_events_with_sequence_after(
                cache_key, resume_from_sequence
            )
            for cached_sequence, cached_event in cached_events:
                parsed_sequence = self._extract_stream_sequence_from_serialized_event(
                    cached_event
                )
                if parsed_sequence is not None:
                    seq_counter = max(seq_counter, parsed_sequence)
                else:
                    seq_counter = max(seq_counter, cached_sequence)
                stream_text_accumulator.consume(cached_event)
                await websocket.send_text(json_dumps(cached_event, ensure_ascii=False))

            # Continue generating sequence from max of cached or resumed
            seq_counter = max(seq_counter, resume_from_sequence)

        serialized = {}
        try:
            async for event in self._iter_stream_events_with_heartbeat(
                gateway.stream(
                    resolved=resolved,
                    query=query,
                    context_id=context_id,
                    metadata=metadata,
                ),
                heartbeat_interval_seconds=heartbeat_interval_seconds,
            ):
                if event is None:
                    last_event_at = time.monotonic()
                    await websocket.send_text(
                        json_dumps(self._WS_HEARTBEAT_EVENT, ensure_ascii=False)
                    )
                    continue
                serialized = self.serialize_stream_event(
                    event, validate_message=validate_message
                )
                validation_errors = extract_artifact_validation_errors(
                    serialized,
                    validate_message=validate_message,
                )
                if validation_errors:
                    logger.warning(
                        "Dropped invalid artifact-update event",
                        extra={
                            **log_extra,
                            "validation_error_count": len(validation_errors),
                            "validation_errors_sample": build_validation_errors_log_sample(
                                validation_errors
                            ),
                            "artifact_update_sample": build_artifact_update_log_sample(
                                serialized
                            ),
                        },
                    )
                    continue
                stream_block, non_contract_reason = self._analyze_stream_chunk_contract(
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

                parsed_sequence = (
                    stream_block.get("seq")
                    if isinstance(stream_block, dict)
                    and isinstance(stream_block.get("seq"), int)
                    else self._extract_stream_sequence_from_serialized_event(serialized)
                )
                event_sequence = (
                    parsed_sequence if parsed_sequence is not None else seq_counter + 1
                )
                if event_sequence <= seq_counter:
                    event_sequence = seq_counter + 1
                if (
                    resume_from_sequence is not None
                    and event_sequence <= resume_from_sequence
                ):
                    continue
                seq_counter = max(seq_counter, event_sequence)

                await self._call_callback(on_event, serialized)
                self._ensure_outbound_stream_contract(
                    serialized, event_sequence=event_sequence
                )
                if cache_key:
                    await global_stream_cache.append_event(
                        cache_key, serialized, seq_counter
                    )
                stream_text_accumulator.consume(serialized, stream_block=stream_block)
                last_event_at = time.monotonic()
                await websocket.send_text(json_dumps(serialized, ensure_ascii=False))
                if self._is_terminal_status_event(serialized):
                    terminal_event_seen = True
                    break
            final_text = stream_text_accumulator.result()
            await self._call_callback(on_complete_metadata, {})
            await self._call_callback(on_complete, final_text)
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
            if self._is_client_disconnect_error(exc):
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
            error_code = (
                self._extract_error_code_from_exception(exc) or self._STREAM_ERROR_CODE
            )
            error_payload = {
                "message": self._STREAM_ERROR_MESSAGE,
                "error_code": error_code,
            }
            final_outcome = StreamOutcome(
                success=False,
                finish_reason=StreamFinishReason.UPSTREAM_ERROR,
                final_text=stream_text_accumulator.result() or "",
                error_message=self._STREAM_ERROR_MESSAGE,
                error_code=error_code,
                elapsed_seconds=time.monotonic() - started_at,
                idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                terminal_event_seen=False,
            )
            await self._call_callback(on_error, self._STREAM_ERROR_MESSAGE)
            await self._call_callback(on_error_metadata, error_payload)
            await self.send_ws_error(
                websocket,
                message=self._STREAM_ERROR_MESSAGE,
                error_code=error_code,
            )
        finally:
            if cache_key and self._is_terminal_status_event(serialized):
                await global_stream_cache.mark_completed(cache_key)
            if final_outcome is not None:
                await self._call_callback_safely(
                    on_finalized,
                    final_outcome,
                    logger=logger,
                    log_extra=log_extra,
                    warning_message="A2A WS finalized callback failed",
                )
            if send_stream_end and not client_disconnected:
                await self.send_ws_stream_end(websocket)

    async def consume_stream(
        self,
        *,
        gateway: Any,
        client: Any | None = None,
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
        idle_timeout_seconds: float | None = None,
        total_timeout_seconds: float | None = None,
    ) -> StreamOutcome:
        stream_text_accumulator = self._StreamTextAccumulator()
        log_warning = getattr(logger, "warning", None)
        log_info = getattr(logger, "info", None)
        non_contract_drop_reasons: set[str] = set()
        started_at = time.monotonic()
        last_event_at = started_at
        heartbeat_interval_seconds = self._stream_heartbeat_interval_seconds()
        stream_iter = self._iter_stream_events_with_heartbeat(
            gateway.stream(
                client=client,
                resolved=resolved,
                query=query,
                context_id=context_id,
                metadata=metadata,
            ),
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        ).__aiter__()
        terminal_event_seen = False
        serialized: dict[str, Any] = {}
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
                wait_timeout = (
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
                    timeout_message = (
                        f"A2A stream total timeout after {total_timeout:.1f}s"
                    )
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
                    await self._call_callback(on_error, timeout_message)
                    await self._call_callback(
                        on_error_metadata,
                        {"message": timeout_message, "error_code": "timeout"},
                    )
                    await self._call_callback_safely(
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
                        timeout_message = (
                            f"A2A stream idle timeout after {idle_value:.1f}s"
                        )
                        finish_reason = StreamFinishReason.TIMEOUT_IDLE
                    partial_content = stream_text_accumulator.result()
                    outcome = StreamOutcome(
                        success=False,
                        finish_reason=finish_reason,
                        final_text=partial_content or "",
                        error_message=timeout_message,
                        error_code="timeout",
                        elapsed_seconds=time.monotonic() - started_at,
                        idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                        terminal_event_seen=False,
                        internal_error_message=timeout_message,
                    )
                    await self._call_callback(on_error, timeout_message)
                    await self._call_callback(
                        on_error_metadata,
                        {"message": timeout_message, "error_code": "timeout"},
                    )
                    await self._call_callback_safely(
                        on_finalized,
                        outcome,
                        logger=logger,
                        log_extra=log_extra,
                        warning_message="A2A consume stream finalized callback failed",
                    )
                    return outcome
                if event is None:
                    # Align with realtime stream semantics:
                    # heartbeat frames indicate the upstream connection is still alive
                    # and should refresh the idle timer.
                    last_event_at = time.monotonic()
                    continue

                serialized = self.serialize_stream_event(
                    event, validate_message=validate_message
                )
                validation_errors = extract_artifact_validation_errors(
                    serialized, validate_message=validate_message
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
                            "Dropped invalid artifact-update event",
                            extra=warning_payload,
                        )
                    elif callable(log_info):
                        log_info(
                            "Dropped invalid artifact-update event",
                            extra=warning_payload,
                        )
                    continue
                stream_block, non_contract_reason = self._analyze_stream_chunk_contract(
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
                await self._call_callback(on_event, serialized)
                stream_text_accumulator.consume(serialized, stream_block=stream_block)
                if self._is_terminal_status_event(serialized):
                    terminal_event_seen = True
                    break

            await self._call_callback(
                on_complete_metadata,
                {},
            )
            final_text = stream_text_accumulator.result()
            await self._call_callback(on_complete, final_text)
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
            await self._call_callback_safely(
                on_finalized,
                outcome,
                logger=logger,
                log_extra=log_extra,
                warning_message="A2A consume stream finalized callback failed",
            )
            return outcome
        except asyncio.CancelledError:
            partial_content = stream_text_accumulator.result()
            outcome = StreamOutcome(
                success=False,
                finish_reason=StreamFinishReason.CLIENT_DISCONNECT,
                final_text=partial_content or "",
                error_message=None,
                error_code=None,
                elapsed_seconds=time.monotonic() - started_at,
                idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                terminal_event_seen=terminal_event_seen,
            )
            await self._call_callback_safely(
                on_finalized,
                outcome,
                logger=logger,
                log_extra=log_extra,
                warning_message="A2A consume stream finalized callback failed",
            )
            raise
        except Exception as exc:
            if callable(log_warning):
                log_warning(
                    "A2A consume stream failed",
                    exc_info=True,
                    extra=log_extra,
                )
            elif callable(log_info):
                log_info(
                    "A2A consume stream failed",
                    exc_info=True,
                    extra=log_extra,
                )
            error_code = (
                self._extract_error_code_from_exception(exc) or self._STREAM_ERROR_CODE
            )
            partial_content = stream_text_accumulator.result()
            outcome = StreamOutcome(
                success=False,
                finish_reason=StreamFinishReason.UPSTREAM_ERROR,
                final_text=partial_content or "",
                error_message=self._STREAM_ERROR_MESSAGE,
                error_code=error_code,
                elapsed_seconds=time.monotonic() - started_at,
                idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                terminal_event_seen=False,
                internal_error_message=self._extract_internal_error_message(exc),
            )
            await self._call_callback(on_error, self._STREAM_ERROR_MESSAGE)
            await self._call_callback(
                on_error_metadata,
                {"message": self._STREAM_ERROR_MESSAGE, "error_code": error_code},
            )
            await self._call_callback_safely(
                on_finalized,
                outcome,
                logger=logger,
                log_extra=log_extra,
                warning_message="A2A consume stream finalized callback failed",
            )
            return outcome


a2a_invoke_service = A2AInvokeService()

__all__ = [
    "A2AInvokeService",
    "StreamFinishReason",
    "StreamOutcome",
    "a2a_invoke_service",
]
