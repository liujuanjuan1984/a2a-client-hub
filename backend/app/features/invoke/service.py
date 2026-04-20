"""Shared helpers for invoking A2A agents across different catalogs.

The hub (admin-managed) and user-managed A2A routes should share streaming
transport logic to keep behavior consistent and reduce drift.
"""

from __future__ import annotations

import asyncio as asyncio_module
import time as time_module
from typing import Any, AsyncIterator

from fastapi import WebSocket
from fastapi.responses import StreamingResponse

from app.features.invoke import stream_payloads
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
from app.features.invoke.service_streaming import A2AInvokeStreamingRuntime
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

asyncio = asyncio_module
time = time_module


class A2AInvokeService:
    """Facade for invoke payload analysis and stream transport helpers."""

    def __init__(self) -> None:
        self._streaming = A2AInvokeStreamingRuntime()

    @classmethod
    def analyze_payload(cls, payload: dict[str, Any]) -> PayloadAnalysis:
        return analyze_payload_object(payload)

    @classmethod
    def _extract_stream_sequence_from_serialized_event(
        cls, payload: dict[str, Any]
    ) -> int | None:
        return stream_payloads.extract_stream_sequence_from_serialized_event(payload)

    @staticmethod
    def _pick_non_empty_str(
        payload: dict[str, Any],
        keys: tuple[str, ...],
    ) -> str | None:
        return A2AInvokeStreamingRuntime._pick_non_empty_str(payload, keys)

    @staticmethod
    def _pick_int(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
        return A2AInvokeStreamingRuntime._pick_int(payload, keys)

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
        return stream_payloads.extract_interrupt_lifecycle_from_serialized_event(
            payload
        )

    @classmethod
    def extract_stream_chunk_from_serialized_event(
        cls, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        return stream_payloads.extract_stream_chunk_from_serialized_event(payload)

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
        resolved = stream_payloads.extract_stream_text_from_parts(parts)
        return resolved or None

    @classmethod
    def extract_readable_content_from_invoke_result(
        cls, result: dict[str, Any]
    ) -> str | None:
        return extract_readable_content_from_result(result)

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
        return A2AInvokeStreamingRuntime.build_ws_error_event(
            message=message,
            error_code=error_code,
            source=source,
            jsonrpc_code=jsonrpc_code,
            missing_params=missing_params,
            upstream_error=upstream_error,
        )

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
        await self._streaming.send_ws_error(
            websocket,
            message=message,
            error_code=error_code,
            source=source,
            jsonrpc_code=jsonrpc_code,
            missing_params=missing_params,
            upstream_error=upstream_error,
        )

    async def send_ws_stream_end(self, websocket: WebSocket) -> None:
        await self._streaming.send_ws_stream_end(websocket)

    @staticmethod
    def _is_client_disconnect_error(exc: Exception) -> bool:
        return A2AInvokeStreamingRuntime._is_client_disconnect_error(exc)

    @staticmethod
    async def _call_callback(
        callback: Any,
        value: Any,
    ) -> Any | None:
        return await A2AInvokeStreamingRuntime._call_callback(callback, value)

    @staticmethod
    async def _call_callback_safely(
        callback: Any,
        value: Any,
        *,
        logger: Any,
        log_extra: dict[str, Any],
        warning_message: str,
    ) -> Any | None:
        return await A2AInvokeStreamingRuntime._call_callback_safely(
            callback,
            value,
            logger=logger,
            log_extra=log_extra,
            warning_message=warning_message,
        )

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
        async for payload in A2AInvokeStreamingRuntime._iter_gateway_stream(
            gateway=gateway,
            invoke_session=invoke_session,
            resolved=resolved,
            query=query,
            context_id=context_id,
            metadata=metadata,
            on_session_started=on_session_started,
        ):
            yield payload

    @staticmethod
    def serialize_stream_event(
        event: StreamEvent, *, validate_message: ValidateMessageFn
    ) -> dict[str, Any]:
        return A2AInvokeStreamingRuntime.serialize_stream_event(
            event, validate_message=validate_message
        )

    @staticmethod
    def _analyze_stream_chunk_contract(
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        return A2AInvokeStreamingRuntime._analyze_stream_chunk_contract(payload)

    @staticmethod
    def _is_terminal_status_event(payload: dict[str, Any]) -> bool:
        return A2AInvokeStreamingRuntime._is_terminal_status_event(payload)

    @classmethod
    def _ensure_outbound_stream_contract(
        cls,
        payload: dict[str, Any],
        *,
        event_sequence: int,
    ) -> None:
        A2AInvokeStreamingRuntime._ensure_outbound_stream_contract(
            payload, event_sequence=event_sequence
        )

    @staticmethod
    def _stream_heartbeat_interval_seconds() -> float:
        return A2AInvokeStreamingRuntime._stream_heartbeat_interval_seconds()

    @classmethod
    def _extract_error_code_from_exception(cls, exc: BaseException) -> str | None:
        return A2AInvokeStreamingRuntime._extract_error_code_from_exception(exc)

    @classmethod
    def _normalize_error_code(cls, value: Any) -> str | None:
        return A2AInvokeStreamingRuntime._normalize_error_code(value)

    @classmethod
    def _split_missing_param_names(cls, value: str) -> list[str]:
        return A2AInvokeStreamingRuntime._split_missing_param_names(value)

    @classmethod
    def _coerce_missing_params(cls, value: Any) -> list[dict[str, Any]]:
        return A2AInvokeStreamingRuntime._coerce_missing_params(value)

    @classmethod
    def _sanitize_upstream_error_data(
        cls,
        value: Any,
        *,
        depth: int = 0,
    ) -> Any:
        return A2AInvokeStreamingRuntime._sanitize_upstream_error_data(
            value, depth=depth
        )

    @classmethod
    def _build_stream_error_payload(
        cls,
        exc: BaseException,
    ) -> StreamErrorPayload:
        return A2AInvokeStreamingRuntime._build_stream_error_payload(exc)

    @staticmethod
    def _extract_internal_error_message(exc: BaseException) -> str | None:
        return A2AInvokeStreamingRuntime._extract_internal_error_message(exc)

    async def _iter_stream_events_with_heartbeat(
        self,
        stream: AsyncIterator[StreamEvent],
        *,
        heartbeat_interval_seconds: float,
    ) -> AsyncIterator[StreamEvent | None]:
        async for payload in self._streaming._iter_stream_events_with_heartbeat(
            stream,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        ):
            yield payload

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
        return self._streaming.stream_sse(
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
        await self._streaming.stream_ws(
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
        return await self._streaming.consume_stream(
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


a2a_invoke_service = A2AInvokeService()
