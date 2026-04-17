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

from app.features.invoke.payload_analysis import (
    PayloadAnalysis,
)
from app.features.invoke.payload_analysis import (
    analyze_payload as analyze_payload_object,
)
from app.features.invoke.payload_analysis import (
    extract_binding_hints_from_invoke_result as extract_binding_hints_from_result,
)
from app.features.invoke.payload_analysis import (
    extract_binding_hints_from_serialized_event as extract_binding_hints_from_event,
)
from app.features.invoke.payload_analysis import (
    extract_readable_content_from_invoke_result as extract_readable_content_from_result,
)
from app.features.invoke.payload_analysis import (
    extract_stream_identity_hints_from_invoke_result as extract_stream_identity_hints_from_result,
)
from app.features.invoke.payload_analysis import (
    extract_stream_identity_hints_from_serialized_event as extract_stream_identity_hints_from_event,
)
from app.features.invoke.payload_analysis import (
    extract_usage_hints_from_invoke_result as extract_usage_hints_from_result,
)
from app.features.invoke.payload_analysis import (
    extract_usage_hints_from_serialized_event as extract_usage_hints_from_event,
)
from app.features.invoke.stream_diagnostics import (
    build_artifact_update_log_sample,
    build_validation_errors_log_sample,
    extract_artifact_validation_errors,
    warn_non_contract_artifact_update_once,
)
from app.features.invoke.stream_payloads import (
    analyze_stream_chunk_contract,
    coerce_message_event_to_artifact_update,
    extract_interrupt_lifecycle_from_serialized_event,
    extract_shared_stream_metadata,
    extract_stream_chunk_from_serialized_event,
    extract_stream_sequence_from_serialized_event,
    extract_stream_text_from_parts,
)
from app.integrations.a2a_client.errors import A2APeerProtocolError
from app.integrations.a2a_client.invoke_session import AgentResolutionPolicy
from app.integrations.a2a_error_contract import (
    build_upstream_error_details_from_protocol_error,
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
StreamSessionStartedCallbackFn = Callable[[Any], Any]


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
    source: str | None = None
    jsonrpc_code: int | None = None
    missing_params: tuple[dict[str, Any], ...] | None = None
    upstream_error: dict[str, Any] | None = None


@dataclass(frozen=True)
class StreamErrorPayload:
    message: str
    error_code: str | None
    source: str | None = None
    jsonrpc_code: int | None = None
    missing_params: tuple[dict[str, Any], ...] | None = None
    upstream_error: dict[str, Any] | None = None

    def as_event_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {"message": self.message}
        if self.error_code:
            data["error_code"] = self.error_code
        if self.source:
            data["source"] = self.source
        if self.jsonrpc_code is not None:
            data["jsonrpc_code"] = self.jsonrpc_code
        if self.missing_params:
            data["missing_params"] = [dict(item) for item in self.missing_params]
        if self.upstream_error:
            data["upstream_error"] = dict(self.upstream_error)
        return data


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
        if (
            isinstance(exc, RuntimeError)
            and "close message has been sent" in str(exc).lower()
        ):
            return True
        return False

    @staticmethod
    async def _call_callback(
        callback: Callable[[Any], Any] | None,
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
        callback: Callable[[Any], Any] | None,
        value: Any,
        *,
        logger: Any,
        log_extra: dict[str, Any],
        warning_message: str,
    ) -> Any | None:
        try:
            return await A2AInvokeService._call_callback(callback, value)
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
        def _is_word_char(value: str | None) -> bool:
            return bool(value and re.fullmatch(r"[\w]", value, flags=re.UNICODE))

        @staticmethod
        def _extract_text_from_parts(parts: Any) -> str:
            return extract_stream_text_from_parts(parts)

        @staticmethod
        def _extract_shared_stream_metadata(
            payload: dict[str, Any], artifact: dict[str, Any]
        ) -> dict[str, Any]:
            return extract_shared_stream_metadata(payload, artifact)

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
            append: bool,
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
                target["content"] = (
                    f"{current if isinstance(current, str) else ''}{delta}"
                )
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
                    A2AInvokeService.extract_stream_chunk_from_serialized_event(payload)
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
                append=bool(resolved_stream_block.get("append", True)),
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
        coerce_message_event_to_artifact_update(payload)
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
        payload["seq"] = event_sequence
        coerce_message_event_to_artifact_update(payload)
        if (
            payload.get("kind") != "artifact-update"
            and cls.extract_stream_chunk_from_serialized_event(payload) is not None
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
                # Consume terminal StopAsyncIteration from finished tasks so event loop
                # doesn't emit "Task exception was never retrieved" warnings.
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
        from app.features.invoke.stream_cache.memory_cache import global_stream_cache

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
                    self._iter_gateway_stream(
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

                    # Outbound seq is a local stream cursor for resume and ordering.
                    # It intentionally does not preserve any upstream chunk numbering.
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
                error_payload = self._build_stream_error_payload(exc)
                final_outcome = StreamOutcome(
                    success=False,
                    finish_reason=StreamFinishReason.UPSTREAM_ERROR,
                    final_text=stream_text_accumulator.result() or "",
                    error_message=self._STREAM_ERROR_MESSAGE,
                    error_code=error_payload.error_code,
                    elapsed_seconds=time.monotonic() - started_at,
                    idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                    terminal_event_seen=False,
                    source=error_payload.source,
                    jsonrpc_code=error_payload.jsonrpc_code,
                    missing_params=error_payload.missing_params,
                    upstream_error=error_payload.upstream_error,
                )
                await self._call_callback(on_error, self._STREAM_ERROR_MESSAGE)
                yield (
                    "event: error\n"
                    f"data: {json_dumps(error_payload.as_event_data(), ensure_ascii=False)}\n\n"
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
                finalization_event: dict[str, Any] | None = None
                if final_outcome is not None:
                    finalized_callback_result = await self._call_callback_safely(
                        on_finalized,
                        final_outcome,
                        logger=logger,
                        log_extra=log_extra,
                        warning_message="A2A SSE finalized callback failed",
                    )
                    if isinstance(finalized_callback_result, dict):
                        finalization_event = finalized_callback_result
                if finalization_event is not None and not client_disconnected:
                    yield (
                        f"data: {json_dumps(finalization_event, ensure_ascii=False)}\n\n"
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
        on_session_started: StreamSessionStartedCallbackFn | None = None,
        send_stream_end: bool = True,
        resume_from_sequence: int | None = None,
        cache_key: str | None = None,
    ) -> None:
        from app.features.invoke.stream_cache.memory_cache import global_stream_cache

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
                self._iter_gateway_stream(
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
            error_payload = self._build_stream_error_payload(exc)
            final_outcome = StreamOutcome(
                success=False,
                finish_reason=StreamFinishReason.UPSTREAM_ERROR,
                final_text=stream_text_accumulator.result() or "",
                error_message=self._STREAM_ERROR_MESSAGE,
                error_code=error_payload.error_code,
                elapsed_seconds=time.monotonic() - started_at,
                idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                terminal_event_seen=False,
                source=error_payload.source,
                jsonrpc_code=error_payload.jsonrpc_code,
                missing_params=error_payload.missing_params,
                upstream_error=error_payload.upstream_error,
            )
            await self._call_callback(on_error, self._STREAM_ERROR_MESSAGE)
            await self._call_callback(on_error_metadata, error_payload.as_event_data())
            await self.send_ws_error(
                websocket,
                message=error_payload.message,
                error_code=error_payload.error_code,
                source=error_payload.source,
                jsonrpc_code=error_payload.jsonrpc_code,
                missing_params=list(error_payload.missing_params or []),
                upstream_error=error_payload.upstream_error,
            )
        finally:
            if cache_key and self._is_terminal_status_event(serialized):
                await global_stream_cache.mark_completed(cache_key)
            finalization_event: dict[str, Any] | None = None
            if final_outcome is not None:
                finalized_callback_result = await self._call_callback_safely(
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
                await self.send_ws_stream_end(websocket)

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
        stream_text_accumulator = self._StreamTextAccumulator()
        log_warning = getattr(logger, "warning", None)
        log_info = getattr(logger, "info", None)
        non_contract_drop_reasons: set[str] = set()
        started_at = time.monotonic()
        last_event_at = started_at
        heartbeat_interval_seconds = self._stream_heartbeat_interval_seconds()
        stream_iter = self._iter_stream_events_with_heartbeat(
            self._iter_gateway_stream(
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
            error_payload = self._build_stream_error_payload(exc)
            partial_content = stream_text_accumulator.result()
            outcome = StreamOutcome(
                success=False,
                finish_reason=StreamFinishReason.UPSTREAM_ERROR,
                final_text=partial_content or "",
                error_message=self._STREAM_ERROR_MESSAGE,
                error_code=error_payload.error_code,
                elapsed_seconds=time.monotonic() - started_at,
                idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                terminal_event_seen=False,
                internal_error_message=self._extract_internal_error_message(exc),
                source=error_payload.source,
                jsonrpc_code=error_payload.jsonrpc_code,
                missing_params=error_payload.missing_params,
                upstream_error=error_payload.upstream_error,
            )
            await self._call_callback(on_error, self._STREAM_ERROR_MESSAGE)
            await self._call_callback(on_error_metadata, error_payload.as_event_data())
            await self._call_callback_safely(
                on_finalized,
                outcome,
                logger=logger,
                log_extra=log_extra,
                warning_message="A2A consume stream finalized callback failed",
            )
            return outcome


a2a_invoke_service = A2AInvokeService()
