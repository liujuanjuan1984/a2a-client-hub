"""Streaming transport runtime for invoke service."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from contextlib import suppress
from typing import Any, AsyncIterator

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.features.invoke import (
    service_streaming_consume,
    service_streaming_transport,
    stream_payloads,
)
from app.features.invoke.service_types import (
    StreamErrorMetadataCallbackFn,
    StreamErrorPayload,
    StreamEvent,
    StreamEventPayloadCallbackFn,
    StreamFinalizedCallbackFn,
    StreamMetadataCallbackFn,
    StreamOutcome,
    StreamSessionStartedCallbackFn,
    StreamTextCallbackFn,
    ValidateMessageFn,
)
from app.integrations.a2a_client.errors import A2APeerProtocolError
from app.integrations.a2a_client.invoke_session import AgentResolutionPolicy
from app.integrations.a2a_error_contract import (
    build_upstream_error_details_from_protocol_error,
)
from app.utils.json_encoder import json_dumps
from app.utils.payload_extract import as_dict


class StreamTextAccumulator:
    """Accumulates stream text for persistence."""

    def __init__(self) -> None:
        self._blocks: list[dict[str, Any]] = []
        self._block_seq = 0

    @staticmethod
    def _is_word_char(value: str | None) -> bool:
        return bool(value and re.fullmatch(r"[\w]", value, flags=re.UNICODE))

    @staticmethod
    def _extract_shared_stream_metadata(
        payload: dict[str, Any], artifact: dict[str, Any]
    ) -> dict[str, Any]:
        return stream_payloads.extract_shared_stream_metadata(payload, artifact)

    def _find_block_index(self, block_id: str) -> int | None:
        for index, block in enumerate(self._blocks):
            if str(block.get("block_id") or "") == block_id:
                return index
        return None

    def _find_last_text_block_index(self) -> int | None:
        for index in range(len(self._blocks) - 1, -1, -1):
            if str(self._blocks[index].get("type") or "") == "text":
                return index
        return None

    def _trim_overlapping_reasoning_prefix(self, text: str) -> str:
        if not text or not self._blocks:
            return text
        latest_reasoning = self._blocks[-1]
        if str(latest_reasoning.get("type") or "") != "reasoning":
            return text
        reasoning_content = str(latest_reasoning.get("content") or "")
        if not reasoning_content:
            return text
        for overlap in range(min(len(reasoning_content), len(text)), 0, -1):
            candidate = reasoning_content[-overlap:]
            overlap_start = len(reasoning_content) - overlap
            before_overlap = (
                reasoning_content[overlap_start - 1] if overlap_start > 0 else None
            )
            after_overlap = text[overlap] if overlap < len(text) else None
            tokens = re.findall(r"[\w]+", candidate, flags=re.UNICODE)
            if (
                text.startswith(candidate)
                and not self._is_word_char(before_overlap)
                and not self._is_word_char(after_overlap)
                and (len(tokens) >= 2 or any(len(token) >= 5 for token in tokens))
            ):
                return re.sub(r"^\s+", "", text[overlap:])
        return text

    def _adapt_legacy_stream_block(
        self,
        *,
        block_type: str,
        delta: str,
        done: bool,
        source: str | None,
        block_id: str,
        lane_id: str,
        operation: str,
        base_seq: int | None,
        seq: int | None,
    ) -> tuple[str, str, str, str, int | None, bool]:
        resolved_block_id = block_id
        resolved_lane_id = lane_id
        resolved_delta = delta
        resolved_base_seq = base_seq
        if (
            operation == "replace"
            and block_type == "text"
            and source in {"final_snapshot", "finalize_snapshot"}
        ):
            latest_text_index = self._find_last_text_block_index()
            if latest_text_index is not None:
                latest_text = self._blocks[latest_text_index]
                existing_block_id = str(latest_text.get("block_id") or "")
                existing_lane_id = str(latest_text.get("lane_id") or "")
                if existing_block_id:
                    resolved_block_id = existing_block_id
                if existing_lane_id:
                    resolved_lane_id = existing_lane_id
            resolved_delta = self._trim_overlapping_reasoning_prefix(resolved_delta)
            if resolved_base_seq is None:
                resolved_base_seq = seq
        return (
            resolved_block_id,
            resolved_lane_id,
            operation,
            resolved_delta,
            resolved_base_seq,
            done,
        )

    def _push_new_block(
        self,
        block_type: str,
        block_id: str,
        lane_id: str,
        delta: str,
        done: bool,
        base_seq: int | None,
    ) -> None:
        now = self._block_seq
        self._block_seq += 1
        self._blocks.append(
            {
                "id": f"block-{now + 1}",
                "block_id": block_id,
                "lane_id": lane_id,
                "type": block_type,
                "content": delta,
                "is_finished": done,
                "base_seq": base_seq,
                "seq": now,
            }
        )

    def _apply_block_update(
        self,
        *,
        block_type: str,
        delta: str,
        done: bool,
        source: str | None,
        block_id: str,
        lane_id: str,
        operation: str,
        base_seq: int | None,
    ) -> None:
        if not delta and operation != "finalize":
            return
        last = self._blocks[-1] if self._blocks else None
        target_index = self._find_block_index(block_id)
        target = self._blocks[target_index] if target_index is not None else None

        if operation == "finalize":
            if isinstance(target, dict):
                target["is_finished"] = True
                if base_seq is not None:
                    target["base_seq"] = base_seq
            return

        if operation == "replace":
            if isinstance(target, dict):
                target["type"] = block_type
                target["lane_id"] = lane_id
                target["content"] = delta
                target["is_finished"] = done
                if base_seq is not None:
                    target["base_seq"] = base_seq
                return
            if isinstance(last, dict) and last.get("is_finished") is False:
                last["is_finished"] = True
            self._push_new_block(
                block_type,
                block_id,
                lane_id,
                delta,
                done,
                base_seq,
            )
            return

        if isinstance(target, dict):
            current = target.get("content")
            target["type"] = block_type
            target["lane_id"] = lane_id
            target["content"] = f"{current if isinstance(current, str) else ''}{delta}"
            target["is_finished"] = done
            if base_seq is not None:
                target["base_seq"] = base_seq
            return

        if isinstance(last, dict) and last.get("is_finished") is False:
            last["is_finished"] = True
        self._push_new_block(
            block_type,
            block_id,
            lane_id,
            delta,
            done,
            base_seq,
        )

    def consume(
        self,
        payload: dict[str, Any],
        *,
        stream_block: dict[str, Any] | None = None,
    ) -> None:
        resolved_stream_block = stream_block
        if resolved_stream_block is None:
            resolved_stream_block = (
                stream_payloads.extract_stream_chunk_from_serialized_event(payload)
            )
        if not resolved_stream_block:
            return
        block_type = resolved_stream_block.get("block_type")
        delta = resolved_stream_block.get("content")
        if not isinstance(block_type, str) or not isinstance(delta, str):
            return
        block_id = resolved_stream_block.get("block_id")
        lane_id = resolved_stream_block.get("lane_id")
        operation = resolved_stream_block.get("op")
        base_seq = resolved_stream_block.get("base_seq")
        if not isinstance(block_id, str) or not block_id:
            block_id = f"stream:{block_type}"
        if not isinstance(lane_id, str) or not lane_id:
            lane_id = "primary_text" if block_type == "text" else block_type
        if not isinstance(operation, str) or not operation:
            operation = (
                "replace"
                if (not bool(resolved_stream_block.get("append", True)))
                or str(resolved_stream_block.get("source") or "")
                in {"final_snapshot", "finalize_snapshot"}
                else "append"
            )
        (
            block_id,
            lane_id,
            operation,
            delta,
            base_seq,
            done,
        ) = self._adapt_legacy_stream_block(
            block_type=block_type,
            delta=delta,
            done=bool(resolved_stream_block.get("is_finished", False)),
            source=(
                str(resolved_stream_block.get("source"))
                if isinstance(resolved_stream_block.get("source"), str)
                else None
            ),
            block_id=block_id,
            lane_id=lane_id,
            operation=operation,
            base_seq=base_seq if isinstance(base_seq, int) else None,
            seq=(
                resolved_stream_block.get("seq")
                if isinstance(resolved_stream_block.get("seq"), int)
                else None
            ),
        )
        self._apply_block_update(
            block_type=block_type,
            delta=delta,
            done=done,
            source=(
                str(resolved_stream_block.get("source"))
                if isinstance(resolved_stream_block.get("source"), str)
                else None
            ),
            block_id=block_id,
            lane_id=lane_id,
            operation=operation,
            base_seq=base_seq,
        )

    def result(self) -> str:
        return "".join(
            block.get("content", "")
            for block in self._blocks
            if block.get("type") == "text" and isinstance(block.get("content"), str)
        )


class A2AInvokeStreamingRuntime:
    """Streaming/runtime helpers for blocking, SSE, and WS invoke flows."""

    _STREAM_ERROR_MESSAGE = "Upstream streaming failed"
    _STREAM_ERROR_CODE = "upstream_stream_error"
    _SSE_HEARTBEAT_FRAME = ": keep-alive\n\n"
    _WS_HEARTBEAT_EVENT = {"event": "heartbeat", "data": {}}
    _WS_STREAM_END_EVENT = {"event": "stream_end", "data": {}}
    _ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,64}$")
    _MISSING_PARAM_MESSAGE_PATTERNS = (
        re.compile(
            r"(?P<names>[A-Za-z][A-Za-z0-9_]*(?:\s*[/,]\s*[A-Za-z][A-Za-z0-9_]*)*)\s+required\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bmissing\s+(?P<names>[A-Za-z][A-Za-z0-9_]*(?:\s*[/,]\s*[A-Za-z][A-Za-z0-9_]*)*)\b",
            re.IGNORECASE,
        ),
    )
    _SAFE_UPSTREAM_DATA_KEYS = frozenset(
        {
            "type",
            "field",
            "fields",
            "param",
            "params",
            "name",
            "names",
            "missing",
            "missing_fields",
            "missing_params",
            "missingParams",
            "required",
            "required_fields",
            "reason",
            "hint",
            "details",
        }
    )

    @classmethod
    def build_ws_error_event(
        cls,
        *,
        message: str,
        error_code: str | None = None,
        source: str | None = None,
        jsonrpc_code: int | None = None,
        missing_params: list[dict[str, Any]] | None = None,
        upstream_error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"message": message}
        if error_code:
            data["error_code"] = error_code
        if source:
            data["source"] = source
        if jsonrpc_code is not None:
            data["jsonrpc_code"] = jsonrpc_code
        if missing_params:
            data["missing_params"] = missing_params
        if upstream_error:
            data["upstream_error"] = upstream_error
        return {"event": "error", "data": data}

    async def send_ws_error(
        self,
        websocket: WebSocket,
        *,
        message: str,
        error_code: str | None = None,
        source: str | None = None,
        jsonrpc_code: int | None = None,
        missing_params: list[dict[str, Any]] | None = None,
        upstream_error: dict[str, Any] | None = None,
    ) -> None:
        try:
            await websocket.send_text(
                json_dumps(
                    self.build_ws_error_event(
                        message=message,
                        error_code=error_code,
                        source=source,
                        jsonrpc_code=jsonrpc_code,
                        missing_params=missing_params,
                        upstream_error=upstream_error,
                    ),
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
        return isinstance(exc, RuntimeError) and (
            "close message has been sent" in str(exc).lower()
        )

    @staticmethod
    async def _call_callback(
        callback: Any,
        value: Any,
    ) -> Any | None:
        if callback is None:
            return None
        outcome = callback(value)
        if inspect.isawaitable(outcome):
            return await outcome
        return outcome

    @staticmethod
    async def _call_callback_safely(
        callback: Any,
        value: Any,
        *,
        logger: Any,
        log_extra: dict[str, Any],
        warning_message: str,
    ) -> Any | None:
        try:
            return await A2AInvokeStreamingRuntime._call_callback(callback, value)
        except Exception:
            log_warning = getattr(logger, "warning", None)
            if callable(log_warning):
                log_warning(warning_message, exc_info=True, extra=log_extra)
                return None
            logging.getLogger(__name__).warning(
                warning_message,
                exc_info=True,
                extra=log_extra,
            )
            return None

    @classmethod
    async def _iter_gateway_stream(
        cls,
        *,
        gateway: Any,
        invoke_session: Any | None,
        resolved: Any,
        query: str,
        context_id: str | None,
        metadata: dict[str, Any] | None,
        on_session_started: StreamSessionStartedCallbackFn | None = None,
    ) -> AsyncIterator[StreamEvent]:
        if invoke_session is not None:
            await cls._call_callback(on_session_started, invoke_session)
            async for payload in gateway.stream(
                session=invoke_session,
                resolved=resolved,
                query=query,
                context_id=context_id,
                metadata=metadata,
            ):
                yield payload
            return

        open_invoke_session = getattr(gateway, "open_invoke_session", None)
        if callable(open_invoke_session):
            async with open_invoke_session(
                resolved=resolved,
                policy=AgentResolutionPolicy.CACHED_SHARED,
            ) as session:
                await cls._call_callback(on_session_started, session)
                async for payload in gateway.stream(
                    session=session,
                    resolved=resolved,
                    query=query,
                    context_id=context_id,
                    metadata=metadata,
                ):
                    yield payload
            return

        async for payload in gateway.stream(
            resolved=resolved,
            query=query,
            context_id=context_id,
            metadata=metadata,
        ):
            yield payload

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

    @staticmethod
    def serialize_stream_event(
        event: StreamEvent, *, validate_message: ValidateMessageFn
    ) -> dict[str, Any]:
        from app.core.config import settings

        resolved: Any
        if isinstance(event, tuple):
            resolved = event[1] if event[1] else event[0]
        else:
            resolved = event

        if isinstance(resolved, dict):
            payload = dict(resolved)
        else:
            payload = resolved.model_dump(exclude_none=True)
        stream_payloads.coerce_message_event_to_artifact_update(payload)
        if settings.debug:
            payload["validation_errors"] = validate_message(payload)
        return payload

    @staticmethod
    def _analyze_stream_chunk_contract(
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        return stream_payloads.analyze_stream_chunk_contract(payload)

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
        payload["seq"] = event_sequence
        stream_payloads.coerce_message_event_to_artifact_update(payload)
        if (
            payload.get("kind") != "artifact-update"
            and stream_payloads.extract_stream_chunk_from_serialized_event(payload)
            is not None
        ):
            payload["kind"] = "artifact-update"
        if payload.get("kind") != "artifact-update":
            return

        artifact = as_dict(payload.get("artifact"))
        artifact_metadata: dict[str, Any] = {}
        if artifact:
            artifact["seq"] = event_sequence
            artifact_metadata = as_dict(artifact.get("metadata"))
            artifact_metadata["seq"] = event_sequence
            artifact["metadata"] = artifact_metadata
            payload["artifact"] = artifact
        root_metadata = as_dict(payload.get("metadata"))
        shared_stream = StreamTextAccumulator._extract_shared_stream_metadata(
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
        if message_id:
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

    @classmethod
    def _split_missing_param_names(cls, value: str) -> list[str]:
        return [
            item.strip()
            for item in re.split(r"[/,]", value)
            if item.strip() and cls._normalize_error_code(item.strip()) is not None
        ]

    @classmethod
    def _coerce_missing_params(cls, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, str):
            return [
                {"name": name, "required": True}
                for name in cls._split_missing_param_names(value)
            ]

        if isinstance(value, dict):
            name = None
            for key in ("name", "field", "param", "id"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    name = candidate.strip()
                    break
            if not name:
                return []
            required = value.get("required")
            return [
                {
                    "name": name,
                    "required": required if isinstance(required, bool) else True,
                }
            ]

        if not isinstance(value, list):
            return []

        items: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for item in value:
            for resolved in cls._coerce_missing_params(item):
                name = resolved.get("name")
                if not isinstance(name, str) or name in seen_names:
                    continue
                seen_names.add(name)
                items.append(resolved)
        return items

    @classmethod
    def _sanitize_upstream_error_data(
        cls,
        value: Any,
        *,
        depth: int = 0,
    ) -> Any:
        if depth >= 3:
            return None
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            sanitized_items = [
                cls._sanitize_upstream_error_data(item, depth=depth + 1)
                for item in value
            ]
            return [item for item in sanitized_items if item is not None] or None
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                if key not in cls._SAFE_UPSTREAM_DATA_KEYS:
                    continue
                resolved = cls._sanitize_upstream_error_data(item, depth=depth + 1)
                if resolved is not None:
                    sanitized[key] = resolved
            return sanitized or None
        return None

    @classmethod
    def _build_stream_error_payload(
        cls,
        exc: BaseException,
    ) -> StreamErrorPayload:
        if not isinstance(exc, A2APeerProtocolError):
            return StreamErrorPayload(
                message=cls._STREAM_ERROR_MESSAGE,
                error_code=(
                    cls._extract_error_code_from_exception(exc)
                    or cls._STREAM_ERROR_CODE
                ),
            )
        error_details = build_upstream_error_details_from_protocol_error(
            exc,
            default_error_code=cls._STREAM_ERROR_CODE,
        )
        return StreamErrorPayload(
            message=cls._STREAM_ERROR_MESSAGE,
            error_code=error_details.error_code,
            source=error_details.source,
            jsonrpc_code=error_details.jsonrpc_code,
            missing_params=error_details.missing_params,
            upstream_error=error_details.upstream_error,
        )

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

        async def _next_stream_event() -> StreamEvent:
            return await stream_iter.__anext__()

        next_event_task: asyncio.Task[StreamEvent] = asyncio.create_task(
            _next_stream_event()
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

                next_event_task = asyncio.create_task(_next_stream_event())
                yield event
        finally:
            if not next_event_task.done():
                next_event_task.cancel()
                with suppress(asyncio.CancelledError):
                    await next_event_task
            else:
                with suppress(StopAsyncIteration, asyncio.CancelledError):
                    _ = next_event_task.result()

    def stream_sse(
        self,
        *,
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
        return service_streaming_transport.stream_sse(
            self,
            accumulator_factory=StreamTextAccumulator,
            gateway=gateway,
            invoke_session=invoke_session,
            resolved=resolved,
            query=query,
            context_id=context_id,
            metadata=metadata,
            validate_message=validate_message,
            logger=logger,
            log_extra=log_extra,
            on_complete=on_complete,
            on_complete_metadata=on_complete_metadata,
            on_error=on_error,
            on_event=on_event,
            on_finalized=on_finalized,
            on_session_started=on_session_started,
            resume_from_sequence=resume_from_sequence,
            cache_key=cache_key,
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
        on_session_started: StreamSessionStartedCallbackFn | None = None,
        send_stream_end: bool = True,
        resume_from_sequence: int | None = None,
        cache_key: str | None = None,
    ) -> None:
        await service_streaming_transport.stream_ws(
            self,
            accumulator_factory=StreamTextAccumulator,
            websocket=websocket,
            gateway=gateway,
            resolved=resolved,
            query=query,
            context_id=context_id,
            metadata=metadata,
            validate_message=validate_message,
            logger=logger,
            log_extra=log_extra,
            on_complete=on_complete,
            on_complete_metadata=on_complete_metadata,
            on_error=on_error,
            on_event=on_event,
            on_error_metadata=on_error_metadata,
            on_finalized=on_finalized,
            on_session_started=on_session_started,
            send_stream_end=send_stream_end,
            resume_from_sequence=resume_from_sequence,
            cache_key=cache_key,
        )

    async def consume_stream(
        self,
        *,
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
        return await service_streaming_consume.consume_stream(
            self,
            accumulator_factory=StreamTextAccumulator,
            gateway=gateway,
            invoke_session=invoke_session,
            resolved=resolved,
            query=query,
            context_id=context_id,
            metadata=metadata,
            validate_message=validate_message,
            logger=logger,
            log_extra=log_extra,
            on_complete=on_complete,
            on_complete_metadata=on_complete_metadata,
            on_error=on_error,
            on_event=on_event,
            on_error_metadata=on_error_metadata,
            on_finalized=on_finalized,
            on_session_started=on_session_started,
            idle_timeout_seconds=idle_timeout_seconds,
            total_timeout_seconds=total_timeout_seconds,
        )
