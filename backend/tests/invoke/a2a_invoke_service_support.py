from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from app.core.config import settings
from app.features.invoke.payload_analysis import (
    coerce_payload_to_dict,
    extract_binding_hints_from_invoke_result,
    extract_binding_hints_from_serialized_event,
    extract_readable_content_from_invoke_result,
    extract_stream_identity_hints_from_invoke_result,
    extract_stream_identity_hints_from_serialized_event,
    extract_usage_hints_from_invoke_result,
    extract_usage_hints_from_serialized_event,
)
from app.features.invoke.service_streaming import (
    A2AInvokeStreamingRuntime,
    a2a_invoke_streaming_runtime,
)
from app.features.invoke.service_types import StreamFinishReason
from app.features.invoke.stream_diagnostics import build_artifact_update_log_sample
from app.features.invoke.stream_payloads import (
    extract_interrupt_lifecycle_from_serialized_event,
    extract_stream_chunk_from_serialized_event,
)
from app.integrations.a2a_client.errors import (
    A2APeerProtocolError,
    A2AUpstreamTimeoutError,
)


class _BrokenGateway:
    def stream(self, **kwargs):
        return _FailingAsyncIterator(RuntimeError("stream failed"))


class _DumpableEvent:
    def __init__(self, payload: dict):
        self._payload = payload

    def model_dump(self, exclude_none: bool = True):
        _ = exclude_none
        return self._payload


class _GatewayWithEvents:
    def __init__(self, events: list[dict]):
        self._events = events

    async def stream(self, **kwargs):
        for event in self._events:
            yield _DumpableEvent(event)


class _GatewayWithDelayedEvents:
    def __init__(self, events: list[dict], delay_seconds: float):
        self._events = events
        self._delay_seconds = delay_seconds

    async def stream(self, **kwargs):
        for event in self._events:
            await asyncio.sleep(self._delay_seconds)
            yield _DumpableEvent(event)


class _GatewayWithSingleEventThenPending:
    def __init__(self, first_event: dict):
        self._first_event = first_event

    async def stream(self, **kwargs):
        yield _DumpableEvent(self._first_event)
        await asyncio.Future()


class _DummyWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)


class _DisconnectingWebSocket:
    async def send_text(self, payload: str) -> None:
        raise WebSocketDisconnect(code=1001)


class _ClosedWebSocket:
    async def send_text(self, payload: str) -> None:
        raise RuntimeError('Cannot call "send" once a close message has been sent.')


class _SessionNotFoundError(RuntimeError):
    def __init__(self, message: str, error_code: str):
        super().__init__(message)
        self.error_code = error_code


class _FailingAsyncIterator:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise self._error


class _BrokenGatewayWithSessionNotFound:
    def stream(self, **kwargs):
        return _FailingAsyncIterator(
            _SessionNotFoundError("session not found", "session_not_found")
        )


class _GatewayWithUnstructuredError:
    def stream(self, **kwargs):
        return _FailingAsyncIterator(RuntimeError("session missing"))


class _GatewayWithStructuredProtocolError:
    def stream(self, **kwargs):
        return _FailingAsyncIterator(
            A2APeerProtocolError(
                "project_id/channel_id required",
                error_code="invalid_params",
                rpc_code=-32602,
                data={
                    "missing_params": ["project_id", "channel_id"],
                    "details": {"token": "secret"},
                },
            )
        )


class _GatewayWithTimeoutError:
    def stream(self, **kwargs):
        return _FailingAsyncIterator(
            A2AUpstreamTimeoutError("Timed out before completing the request")
        )


a2a_invoke_service = SimpleNamespace(
    consume_stream=a2a_invoke_streaming_runtime.consume_stream,
    extract_binding_hints_from_invoke_result=extract_binding_hints_from_invoke_result,
    extract_binding_hints_from_serialized_event=(
        extract_binding_hints_from_serialized_event
    ),
    extract_interrupt_lifecycle_from_serialized_event=(
        extract_interrupt_lifecycle_from_serialized_event
    ),
    extract_readable_content_from_invoke_result=(
        extract_readable_content_from_invoke_result
    ),
    extract_stream_chunk_from_serialized_event=(
        extract_stream_chunk_from_serialized_event
    ),
    extract_stream_identity_hints_from_invoke_result=(
        extract_stream_identity_hints_from_invoke_result
    ),
    extract_stream_identity_hints_from_serialized_event=(
        extract_stream_identity_hints_from_serialized_event
    ),
    extract_usage_hints_from_invoke_result=extract_usage_hints_from_invoke_result,
    extract_usage_hints_from_serialized_event=(
        extract_usage_hints_from_serialized_event
    ),
    send_ws_error=a2a_invoke_streaming_runtime.send_ws_error,
    serialize_stream_event=A2AInvokeStreamingRuntime.serialize_stream_event,
    stream_sse=a2a_invoke_streaming_runtime.stream_sse,
    stream_ws=a2a_invoke_streaming_runtime.stream_ws,
    _ensure_outbound_stream_contract=(
        A2AInvokeStreamingRuntime._ensure_outbound_stream_contract
    ),
)


def _artifact_event(
    *,
    artifact_id: str,
    text: str,
    block_type: str | None = None,
    source: str | None = None,
    append: bool | None = None,
    message_id: str | None = None,
    event_id: str | None = None,
) -> dict:
    shared_stream: dict[str, str] = {}
    if block_type or source or message_id or event_id:
        artifact_key = artifact_id.replace(":", "-").replace("/", "-")
        if block_type:
            shared_stream["blockType"] = block_type
        if source:
            shared_stream["source"] = source
        shared_stream["messageId"] = message_id or f"msg-{artifact_key}"
        shared_stream["eventId"] = event_id or f"evt-{artifact_key}"

    metadata = {"shared": {"stream": shared_stream}} if shared_stream else {}
    payload: dict = {
        "artifactUpdate": {
            "op": (
                "append" if append else "replace" if append is not None else "replace"
            ),
            "artifact": {
                "artifactId": artifact_id,
                "parts": [{"text": text}],
                "metadata": metadata,
            },
        }
    }
    return payload


def _artifact_data_event(
    *,
    artifact_id: str,
    data: dict,
    block_type: str,
    source: str | None = None,
    append: bool | None = None,
    message_id: str | None = None,
    event_id: str | None = None,
) -> dict:
    shared_stream: dict[str, str] = {}
    artifact_key = artifact_id.replace(":", "-").replace("/", "-")
    shared_stream["blockType"] = block_type
    if source:
        shared_stream["source"] = source
    shared_stream["messageId"] = message_id or f"msg-{artifact_key}"
    shared_stream["eventId"] = event_id or f"evt-{artifact_key}"

    payload: dict = {
        "artifactUpdate": {
            "op": (
                "append" if append else "replace" if append is not None else "replace"
            ),
            "artifact": {
                "artifactId": artifact_id,
                "parts": [{"data": data}],
                "metadata": {"shared": {"stream": shared_stream}},
            },
        }
    }
    return payload


__all__ = [
    "StreamFinishReason",
    "_BrokenGateway",
    "_BrokenGatewayWithSessionNotFound",
    "_ClosedWebSocket",
    "_DisconnectingWebSocket",
    "_DummyWebSocket",
    "_DumpableEvent",
    "_GatewayWithDelayedEvents",
    "_GatewayWithEvents",
    "_GatewayWithSingleEventThenPending",
    "_GatewayWithStructuredProtocolError",
    "_GatewayWithTimeoutError",
    "_GatewayWithUnstructuredError",
    "_artifact_data_event",
    "_artifact_event",
    "a2a_invoke_service",
    "asyncio",
    "build_artifact_update_log_sample",
    "coerce_payload_to_dict",
    "json",
    "logging",
    "pytest",
    "settings",
    "suppress",
]
