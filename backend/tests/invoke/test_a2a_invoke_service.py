from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress

import pytest
from fastapi import WebSocketDisconnect

from app.core.config import settings
from app.features.invoke.payload_analysis import coerce_payload_to_dict
from app.features.invoke.service import StreamFinishReason, a2a_invoke_service
from app.features.invoke.stream_diagnostics import build_artifact_update_log_sample
from app.integrations.a2a_client.errors import (
    A2APeerProtocolError,
    A2AUpstreamTimeoutError,
)


class _BrokenGateway:
    def stream(self, **kwargs):  # noqa: ARG002
        return _FailingAsyncIterator(RuntimeError("stream failed"))


class _DumpableEvent:
    def __init__(self, payload: dict):
        self._payload = payload

    def model_dump(self, exclude_none: bool = True):  # noqa: ARG002
        _ = exclude_none
        return self._payload


class _GatewayWithEvents:
    def __init__(self, events: list[dict]):
        self._events = events

    async def stream(self, **kwargs):  # noqa: ARG002
        for event in self._events:
            yield _DumpableEvent(event)


class _GatewayWithDelayedEvents:
    def __init__(self, events: list[dict], delay_seconds: float):
        self._events = events
        self._delay_seconds = delay_seconds

    async def stream(self, **kwargs):  # noqa: ARG002
        for event in self._events:
            await asyncio.sleep(self._delay_seconds)
            yield _DumpableEvent(event)


class _GatewayWithSingleEventThenPending:
    def __init__(self, first_event: dict):
        self._first_event = first_event

    async def stream(self, **kwargs):  # noqa: ARG002
        yield _DumpableEvent(self._first_event)
        await asyncio.Future()


class _DummyWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)


class _DisconnectingWebSocket:
    async def send_text(self, payload: str) -> None:  # noqa: ARG002
        raise WebSocketDisconnect(code=1001)


class _ClosedWebSocket:
    async def send_text(self, payload: str) -> None:  # noqa: ARG002
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
    def stream(self, **kwargs):  # noqa: ARG001
        return _FailingAsyncIterator(
            _SessionNotFoundError("session not found", "session_not_found")
        )


class _GatewayWithUnstructuredError:
    def stream(self, **kwargs):  # noqa: ARG001
        return _FailingAsyncIterator(RuntimeError("session missing"))


class _GatewayWithStructuredProtocolError:
    def stream(self, **kwargs):  # noqa: ARG001
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
    def stream(self, **kwargs):  # noqa: ARG001
        return _FailingAsyncIterator(
            A2AUpstreamTimeoutError("Timed out before completing the request")
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
    metadata: dict[str, str] = {}
    if block_type or source or message_id or event_id:
        artifact_key = artifact_id.replace(":", "-").replace("/", "-")
        if block_type:
            metadata["block_type"] = block_type
        if source:
            metadata["source"] = source
        metadata["message_id"] = message_id or f"msg-{artifact_key}"
        metadata["event_id"] = event_id or f"evt-{artifact_key}"

    payload: dict = {
        "kind": "artifact-update",
        "artifact": {
            "artifact_id": artifact_id,
            "parts": [{"kind": "text", "text": text}],
            "metadata": metadata,
        },
    }
    if append is not None:
        payload["append"] = append
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
    metadata: dict[str, str] = {}
    artifact_key = artifact_id.replace(":", "-").replace("/", "-")
    metadata["block_type"] = block_type
    if source:
        metadata["source"] = source
    metadata["message_id"] = message_id or f"msg-{artifact_key}"
    metadata["event_id"] = event_id or f"evt-{artifact_key}"

    payload: dict = {
        "kind": "artifact-update",
        "artifact": {
            "artifact_id": artifact_id,
            "parts": [{"kind": "data", "data": data}],
            "metadata": metadata,
        },
    }
    if append is not None:
        payload["append"] = append
    return payload


@pytest.mark.asyncio
async def test_sse_error_event_contains_unified_error_code():
    response = a2a_invoke_service.stream_sse(
        gateway=_BrokenGateway(),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    payload = "".join(chunks)
    assert "event: error" in payload
    error_data_line = next(
        line for line in payload.splitlines() if line.startswith("data: {")
    )
    error_data = json.loads(error_data_line.removeprefix("data: "))
    assert error_data["message"] == "Upstream streaming failed"
    assert error_data["error_code"] == "upstream_stream_error"


@pytest.mark.asyncio
async def test_sse_error_event_exposes_structured_upstream_payload():
    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithStructuredProtocolError(),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    payload = "".join(chunks)
    error_data_line = next(
        line for line in payload.splitlines() if line.startswith("data: {")
    )
    error_data = json.loads(error_data_line.removeprefix("data: "))
    assert error_data["error_code"] == "invalid_params"
    assert error_data["source"] == "upstream_a2a"
    assert error_data["jsonrpc_code"] == -32602
    assert error_data["missing_params"] == [
        {"name": "project_id", "required": True},
        {"name": "channel_id", "required": True},
    ]
    assert error_data["upstream_error"] == {
        "message": "project_id/channel_id required",
        "data": {"missing_params": ["project_id", "channel_id"]},
    }


@pytest.mark.asyncio
async def test_sse_error_event_preserves_timeout_error_code():
    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithTimeoutError(),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    payload = "".join(chunks)
    error_data_line = next(
        line for line in payload.splitlines() if line.startswith("data: {")
    )
    error_data = json.loads(error_data_line.removeprefix("data: "))
    assert error_data["message"] == "Upstream streaming failed"
    assert error_data["error_code"] == "timeout"


@pytest.mark.asyncio
async def test_sse_on_complete_uses_typed_text_blocks_for_response_content():
    completed: list[str] = []

    async def _on_complete(text: str):
        completed.append(text)

    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                _artifact_event(
                    artifact_id="task-1:stream:reasoning",
                    text="thinking",
                    block_type="reasoning",
                ),
                _artifact_event(
                    artifact_id="task-1:stream:tool_call",
                    text="run_tool()",
                    block_type="tool_call",
                ),
                _artifact_event(
                    artifact_id="task-1:stream",
                    text="Hello ",
                    block_type="text",
                    append=True,
                ),
                _artifact_event(
                    artifact_id="task-1:stream",
                    text="world",
                    block_type="text",
                    append=True,
                ),
                _artifact_event(
                    artifact_id="task-1:stream",
                    text="Hello world",
                    block_type="text",
                    source="final_snapshot",
                    append=False,
                ),
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_complete=_on_complete,
    )
    async for _ in response.body_iterator:
        pass

    assert completed == ["Hello world"]


@pytest.mark.asyncio
async def test_sse_on_complete_metadata_is_empty_dict():
    metadata_payloads: list[dict] = []

    async def _on_complete_metadata(payload: dict):
        metadata_payloads.append(payload)

    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                _artifact_event(
                    artifact_id="task-1:stream:reasoning",
                    text="thinking",
                    block_type="reasoning",
                ),
                _artifact_event(
                    artifact_id="task-1:stream:tool_call",
                    text="run_tool()",
                    block_type="tool_call",
                ),
                _artifact_event(
                    artifact_id="task-1:stream",
                    text="done",
                    block_type="text",
                ),
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_complete_metadata=_on_complete_metadata,
    )
    async for _ in response.body_iterator:
        pass

    assert metadata_payloads == [{}]


@pytest.mark.asyncio
async def test_sse_invokes_complete_metadata_before_complete():
    callback_order: list[str] = []

    async def _on_complete(_: str):
        callback_order.append("complete")

    async def _on_complete_metadata(_: dict):
        callback_order.append("metadata")

    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                _artifact_event(
                    artifact_id="task-1:stream:reasoning",
                    text="thinking",
                    block_type="reasoning",
                ),
                _artifact_event(
                    artifact_id="task-1:stream",
                    text="done",
                    block_type="text",
                ),
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_complete=_on_complete,
        on_complete_metadata=_on_complete_metadata,
    )
    async for _ in response.body_iterator:
        pass

    assert callback_order == ["metadata", "complete"]


@pytest.mark.asyncio
async def test_sse_on_complete_ignores_non_typed_events():
    completed: list[str] = []

    async def _on_complete(text: str):
        completed.append(text)

    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "artifact-update",
                    "artifact": {
                        "parts": [{"kind": "unsupported_kind", "value": "foo"}]
                    },
                },
                {"content": "bar"},
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_complete=_on_complete,
    )
    async for _ in response.body_iterator:
        pass

    assert completed == [""]


@pytest.mark.asyncio
async def test_sse_on_complete_respects_append_false_overwrite_then_append():
    completed: list[str] = []

    async def _on_complete(text: str):
        completed.append(text)

    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                _artifact_event(
                    artifact_id="task-2:stream",
                    text="first",
                    block_type="text",
                    append=True,
                ),
                _artifact_event(
                    artifact_id="task-2:stream",
                    text="reset",
                    block_type="text",
                    append=False,
                ),
                _artifact_event(
                    artifact_id="task-2:stream",
                    text="!",
                    block_type="text",
                    append=True,
                ),
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_complete=_on_complete,
    )
    async for _ in response.body_iterator:
        pass

    assert completed == ["reset!"]


@pytest.mark.asyncio
async def test_sse_on_complete_supports_block_type():
    completed: list[str] = []

    async def _on_complete(text: str):
        completed.append(text)

    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "artifact-update",
                    "task_id": "task-block-type",
                    "artifact": {
                        "artifact_id": "task-block-type:stream",
                        "parts": [{"kind": "text", "text": "Hello alias"}],
                        "metadata": {
                            "block_type": "text",
                            "message_id": "msg-block-type",
                            "event_id": "evt-block-type-1",
                        },
                    },
                }
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_complete=_on_complete,
    )
    async for _ in response.body_iterator:
        pass

    assert completed == ["Hello alias"]


@pytest.mark.asyncio
async def test_sse_on_complete_accepts_text_parts_without_block_type():
    completed: list[str] = []

    async def _on_complete(text: str):
        completed.append(text)

    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "artifact-update",
                    "artifact": {
                        "artifact_id": "task-generic:stream",
                        "parts": [{"kind": "text", "text": "Hello generic"}],
                        "metadata": {},
                    },
                }
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_complete=_on_complete,
    )
    async for _ in response.body_iterator:
        pass

    assert completed == ["Hello generic"]


@pytest.mark.asyncio
async def test_sse_on_complete_ignores_artifact_updates_without_parts():
    completed: list[str] = []

    async def _on_complete(text: str):
        completed.append(text)

    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "artifact-update",
                    "artifact": {
                        "metadata": {
                            "block_type": "text",
                            "message_id": "msg-legacy-no-parts",
                            "event_id": "evt-legacy-no-parts",
                        },
                        "content": "legacy-content-should-be-ignored",
                    },
                }
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_complete=_on_complete,
    )
    async for _ in response.body_iterator:
        pass

    assert completed == [""]


@pytest.mark.asyncio
async def test_sse_drops_invalid_artifact_update_events():
    completed: list[str] = []
    observed_events: list[dict] = []

    async def _on_complete(text: str):
        completed.append(text)

    async def _on_event(payload: dict):
        observed_events.append(payload)

    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                _artifact_event(
                    artifact_id="task-invalid:stream",
                    text="dropped",
                    block_type="text",
                ),
                _artifact_event(
                    artifact_id="task-valid:stream",
                    text="kept",
                    block_type="text",
                ),
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda payload: (
            ["invalid artifact event"]
            if payload.get("kind") == "artifact-update"
            and payload.get("artifact", {}).get("artifact_id") == "task-invalid:stream"
            else []
        ),
        logger=logging.getLogger(__name__),
        log_extra={},
        on_complete=_on_complete,
        on_event=_on_event,
    )
    async for _ in response.body_iterator:
        pass

    assert completed == ["kept"]
    assert observed_events == [
        {
            "kind": "artifact-update",
            "seq": 1,
            "message_id": "msg-task-valid-stream",
            "event_id": "evt-task-valid-stream",
            "artifact": {
                "artifact_id": "task-valid:stream",
                "seq": 1,
                "parts": [{"kind": "text", "text": "kept"}],
                "metadata": {
                    "block_type": "text",
                    "message_id": "msg-task-valid-stream",
                    "event_id": "evt-task-valid-stream",
                    "seq": 1,
                },
            },
        }
    ]


@pytest.mark.asyncio
async def test_sse_warns_non_contract_artifact_update_once_per_reason(caplog):
    completed: list[str] = []

    async def _on_complete(text: str):
        completed.append(text)

    caplog.set_level(logging.WARNING)
    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "artifact-update",
                    "artifact": {
                        "metadata": {
                            "block_type": "text",
                            "message_id": "msg-legacy-1",
                            "event_id": "evt-legacy-1",
                        },
                        "content": "legacy-1",
                    },
                },
                {
                    "kind": "artifact-update",
                    "artifact": {
                        "metadata": {
                            "block_type": "text",
                            "message_id": "msg-legacy-2",
                            "event_id": "evt-legacy-2",
                        },
                        "content": "legacy-2",
                    },
                },
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_complete=_on_complete,
    )
    async for _ in response.body_iterator:
        pass

    assert completed == [""]
    warning_records = [
        record
        for record in caplog.records
        if record.levelname == "WARNING"
        and record.message == "Dropped non-contract artifact-update event"
    ]
    assert len(warning_records) == 1
    assert getattr(warning_records[0], "drop_reason", None) == "missing_text_parts"
    assert getattr(warning_records[0], "artifact_update_sample", None) == {
        "kind": "artifact-update",
        "artifact": {
            "metadata": {
                "block_type": "text",
                "message_id": "msg-legacy-1",
                "event_id": "evt-legacy-1",
            },
            "content": "legacy-1",
        },
    }


@pytest.mark.asyncio
async def test_sse_warns_missing_text_parts_when_identity_ids_absent(caplog):
    completed: list[str] = []

    async def _on_complete(text: str):
        completed.append(text)

    caplog.set_level(logging.WARNING)
    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "artifact-update",
                    "artifact": {
                        "metadata": {
                            "block_type": "text",
                        },
                        "content": "legacy",
                    },
                }
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_complete=_on_complete,
    )
    async for _ in response.body_iterator:
        pass

    assert completed == [""]
    warning_records = [
        record
        for record in caplog.records
        if record.levelname == "WARNING"
        and record.message == "Dropped non-contract artifact-update event"
    ]
    assert len(warning_records) == 1
    assert getattr(warning_records[0], "drop_reason", None) == "missing_text_parts"
    assert getattr(warning_records[0], "artifact_update_sample", None) == {
        "kind": "artifact-update",
        "artifact": {
            "metadata": {
                "block_type": "text",
            },
            "content": "legacy",
        },
    }


@pytest.mark.asyncio
async def test_sse_accepts_tool_call_data_parts_without_non_contract_warning(caplog):
    caplog.set_level(logging.WARNING)
    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                _artifact_data_event(
                    artifact_id="task-tool:stream",
                    block_type="tool_call",
                    source="tool_part_update",
                    data={
                        "call_id": "call-1",
                        "tool": "read",
                        "status": "pending",
                        "input": {},
                    },
                ),
                {"kind": "status-update", "final": True},
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )
    frames: list[str] = []
    async for chunk in response.body_iterator:
        frames.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    warning_records = [
        record
        for record in caplog.records
        if record.levelname == "WARNING"
        and record.message == "Dropped non-contract artifact-update event"
    ]
    assert warning_records == []
    payload = "".join(frames)
    assert '"kind": "artifact-update"' in payload
    assert '"block_type": "tool_call"' in payload


@pytest.mark.asyncio
async def test_sse_cache_replays_mutated_event_payload_from_on_event():
    from app.features.invoke.stream_cache.memory_cache import global_stream_cache

    cache_key = "test-cache-on-event-mutation"
    upstream_event = {
        "kind": "artifact-update",
        "message_id": "msg-upstream-1",
        "artifact": {
            "artifact_id": "task-cache:stream:text",
            "parts": [{"kind": "text", "text": "hello"}],
            "metadata": {
                "block_type": "text",
                "event_id": "evt-cache-1",
                "message_id": "msg-upstream-1",
            },
        },
    }

    async def _rewrite_message_id(payload: dict) -> None:
        payload["message_id"] = "msg-local-1"

    initial = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents([upstream_event]),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_event=_rewrite_message_id,
        cache_key=cache_key,
    )
    initial_frames: list[str] = []
    async for chunk in initial.body_iterator:
        initial_frames.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    artifact_lines = [
        line
        for line in "".join(initial_frames).splitlines()
        if line.startswith("data: ") and '"kind": "artifact-update"' in line
    ]
    assert artifact_lines
    initial_payload = json.loads(artifact_lines[0].removeprefix("data: "))
    assert initial_payload["message_id"] == "msg-local-1"
    assert initial_payload["seq"] == 1
    assert initial_payload["event_id"] == "evt-cache-1"

    replay = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents([]),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        resume_from_sequence=0,
        cache_key=cache_key,
    )
    replay_frames: list[str] = []
    async for chunk in replay.body_iterator:
        replay_frames.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    replay_artifact_lines = [
        line
        for line in "".join(replay_frames).splitlines()
        if line.startswith("data: ") and '"kind": "artifact-update"' in line
    ]
    assert replay_artifact_lines
    replay_payload = json.loads(replay_artifact_lines[0].removeprefix("data: "))
    assert replay_payload["message_id"] == "msg-local-1"
    assert replay_payload["seq"] == 1
    assert replay_payload["event_id"] == "evt-cache-1"

    await global_stream_cache.mark_completed(cache_key)


@pytest.mark.asyncio
async def test_sse_normalizes_outbound_seq_to_monotonic_event_cursor():
    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "artifact-update",
                    "seq": 9,
                    "artifact": {
                        "artifact_id": "task-sse:stream:text:1",
                        "parts": [{"kind": "text", "text": "hello"}],
                        "metadata": {
                            "block_type": "text",
                            "event_id": "evt-sse-1",
                            "message_id": "msg-sse-1",
                        },
                    },
                },
                {
                    "kind": "artifact-update",
                    "seq": 12,
                    "artifact": {
                        "artifact_id": "task-sse:stream:text:2",
                        "parts": [{"kind": "text", "text": " world"}],
                        "metadata": {
                            "block_type": "text",
                            "event_id": "evt-sse-2",
                            "message_id": "msg-sse-1",
                        },
                    },
                },
                {"kind": "status-update", "final": True},
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )
    frames: list[str] = []
    async for chunk in response.body_iterator:
        frames.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in "".join(frames).splitlines()
        if line.startswith("data: ")
        and ('"kind": "artifact-update"' in line or '"kind": "status-update"' in line)
    ]
    artifact_payloads = [
        payload for payload in payloads if payload.get("kind") == "artifact-update"
    ]
    assert [payload["seq"] for payload in artifact_payloads] == [1, 2]
    assert artifact_payloads[0]["artifact"]["seq"] == 1
    assert artifact_payloads[1]["artifact"]["seq"] == 2
    assert payloads[-1]["kind"] == "status-update"
    assert payloads[-1]["seq"] == 3


@pytest.mark.asyncio
async def test_sse_emits_canonical_artifact_update_for_upstream_message_events():
    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "message",
                    "messageId": "msg-upstream-sse-1",
                    "role": "agent",
                    "parts": [{"kind": "text", "text": "hello from raw message"}],
                },
                {"kind": "status-update", "final": True},
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )
    frames: list[str] = []
    async for chunk in response.body_iterator:
        frames.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in "".join(frames).splitlines()
        if line.startswith("data: ")
        and ('"kind": "artifact-update"' in line or '"kind": "status-update"' in line)
    ]
    artifact_payload = next(
        payload for payload in payloads if payload.get("kind") == "artifact-update"
    )
    assert artifact_payload["message_id"] == "msg-upstream-sse-1"
    assert artifact_payload["append"] is False
    assert artifact_payload["artifact"]["parts"] == [
        {"kind": "text", "text": "hello from raw message"}
    ]
    assert "messageId" not in artifact_payload
    assert "parts" not in artifact_payload
    assert "role" not in artifact_payload


@pytest.mark.asyncio
async def test_sse_breaks_stream_after_terminal_status_update():
    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "status-update",
                    "status": {"state": "input_required"},
                    "final": True,
                },
                {"content": "should-not-be-forwarded"},
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    payload = "".join(chunks)
    assert '"kind": "status-update"' in payload
    assert "should-not-be-forwarded" not in payload
    assert "event: stream_end" in payload


@pytest.mark.asyncio
async def test_sse_emits_persisted_completion_ack_before_stream_end():
    async def _on_finalized(_outcome):
        return {
            "kind": "status-update",
            "final": True,
            "status": {"state": "completed"},
            "message_id": "msg-persisted-sse-1",
            "metadata": {
                "shared": {
                    "stream": {
                        "message_id": "msg-persisted-sse-1",
                        "completion_phase": "persisted",
                    }
                }
            },
        }

    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                _artifact_event(
                    artifact_id="task-persisted-sse:stream",
                    text="ok",
                    block_type="text",
                ),
                {
                    "kind": "status-update",
                    "status": {"state": "completed"},
                    "final": True,
                },
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_finalized=_on_finalized,
    )

    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    payload = "".join(chunks)
    persisted_index = payload.index('"completion_phase": "persisted"')
    stream_end_index = payload.index("event: stream_end")
    assert persisted_index < stream_end_index


@pytest.mark.asyncio
async def test_ws_breaks_stream_after_terminal_status_update():
    websocket = _DummyWebSocket()
    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "status-update",
                    "status": {"state": "input_required"},
                    "final": True,
                },
                {"content": "should-not-be-forwarded"},
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )

    payloads = [json.loads(item) for item in websocket.sent]
    assert payloads[0]["kind"] == "status-update"
    assert payloads[-1]["event"] == "stream_end"
    assert not any(
        item.get("content") == "should-not-be-forwarded" for item in payloads
    )


@pytest.mark.asyncio
async def test_ws_emits_canonical_artifact_update_for_upstream_message_events():
    websocket = _DummyWebSocket()

    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "message",
                    "messageId": "msg-upstream-ws-1",
                    "role": "agent",
                    "parts": [{"kind": "text", "text": "hello from raw message"}],
                },
                {"kind": "status-update", "final": True},
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )

    payloads = [
        json.loads(item)
        for item in websocket.sent
        if item.startswith("{")
        and ('"kind": "artifact-update"' in item or '"kind": "status-update"' in item)
    ]
    artifact_payload = next(
        payload for payload in payloads if payload.get("kind") == "artifact-update"
    )
    assert artifact_payload["message_id"] == "msg-upstream-ws-1"
    assert artifact_payload["append"] is False
    assert artifact_payload["artifact"]["parts"] == [
        {"kind": "text", "text": "hello from raw message"}
    ]
    assert "messageId" not in artifact_payload
    assert "parts" not in artifact_payload
    assert "role" not in artifact_payload


@pytest.mark.asyncio
async def test_ws_emits_persisted_completion_ack_before_stream_end():
    websocket = _DummyWebSocket()

    async def _on_finalized(_outcome):
        return {
            "kind": "status-update",
            "final": True,
            "status": {"state": "completed"},
            "message_id": "msg-persisted-ws-1",
            "metadata": {
                "shared": {
                    "stream": {
                        "message_id": "msg-persisted-ws-1",
                        "completion_phase": "persisted",
                    }
                }
            },
        }

    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_GatewayWithEvents(
            [
                _artifact_event(
                    artifact_id="task-persisted-ws:stream",
                    text="ok",
                    block_type="text",
                ),
                {
                    "kind": "status-update",
                    "status": {"state": "completed"},
                    "final": True,
                },
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_finalized=_on_finalized,
    )

    payloads = [json.loads(item) for item in websocket.sent]
    persisted_index = next(
        index
        for index, item in enumerate(payloads)
        if item.get("kind") == "status-update"
        and item.get("metadata", {})
        .get("shared", {})
        .get("stream", {})
        .get("completion_phase")
        == "persisted"
    )
    stream_end_index = next(
        index
        for index, item in enumerate(payloads)
        if item.get("event") == "stream_end"
    )
    assert persisted_index < stream_end_index


@pytest.mark.asyncio
async def test_ws_assigns_fallback_seq_and_event_id_after_on_event_mutation():
    websocket = _DummyWebSocket()

    async def _rewrite_message_id(payload: dict[str, object]) -> None:
        payload["message_id"] = "msg-local-ws-1"

    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "artifact-update",
                    "artifact": {
                        "artifact_id": "task-ws:stream:text",
                        "parts": [{"kind": "text", "text": "hello"}],
                        "metadata": {"block_type": "text"},
                    },
                },
                {"kind": "status-update", "final": True},
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_event=_rewrite_message_id,
    )

    payloads = [
        json.loads(item)
        for item in websocket.sent
        if item.startswith("{") and '"kind": "artifact-update"' in item
    ]
    assert payloads
    assert payloads[0]["message_id"] == "msg-local-ws-1"
    assert payloads[0]["seq"] == 1
    assert payloads[0]["event_id"] == "msg-local-ws-1:1"


@pytest.mark.asyncio
async def test_ws_normalizes_outbound_seq_to_monotonic_event_cursor():
    websocket = _DummyWebSocket()

    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "artifact-update",
                    "seq": 9,
                    "artifact": {
                        "artifact_id": "task-ws:stream:text:1",
                        "parts": [{"kind": "text", "text": "hello"}],
                        "metadata": {
                            "block_type": "text",
                            "event_id": "evt-ws-1",
                            "message_id": "msg-ws-1",
                        },
                    },
                },
                {
                    "kind": "artifact-update",
                    "seq": 12,
                    "artifact": {
                        "artifact_id": "task-ws:stream:text:2",
                        "parts": [{"kind": "text", "text": " world"}],
                        "metadata": {
                            "block_type": "text",
                            "event_id": "evt-ws-2",
                            "message_id": "msg-ws-1",
                        },
                    },
                },
                {"kind": "status-update", "final": True},
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )

    payloads = [
        json.loads(item)
        for item in websocket.sent
        if item.startswith("{")
        and ('"kind": "artifact-update"' in item or '"kind": "status-update"' in item)
    ]
    artifact_payloads = [
        payload for payload in payloads if payload.get("kind") == "artifact-update"
    ]
    assert [payload["seq"] for payload in artifact_payloads] == [1, 2]
    assert artifact_payloads[0]["artifact"]["seq"] == 1
    assert artifact_payloads[1]["artifact"]["seq"] == 2
    assert payloads[-1]["kind"] == "status-update"
    assert payloads[-1]["seq"] == 3


@pytest.mark.asyncio
async def test_ws_warns_non_contract_artifact_update_once_per_reason(caplog):
    websocket = _DummyWebSocket()
    caplog.set_level(logging.WARNING)
    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "artifact-update",
                    "artifact": {
                        "metadata": {
                            "block_type": "text",
                            "message_id": "msg-legacy-ws-1",
                            "event_id": "evt-legacy-ws-1",
                        },
                        "content": "legacy-1",
                    },
                },
                {
                    "kind": "artifact-update",
                    "artifact": {
                        "metadata": {
                            "block_type": "text",
                            "message_id": "msg-legacy-ws-2",
                            "event_id": "evt-legacy-ws-2",
                        },
                        "content": "legacy-2",
                    },
                },
                {"kind": "status-update", "final": True},
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )

    warning_records = [
        record
        for record in caplog.records
        if record.levelname == "WARNING"
        and record.message == "Dropped non-contract artifact-update event"
    ]
    assert len(warning_records) == 1
    assert getattr(warning_records[0], "drop_reason", None) == "missing_text_parts"
    assert getattr(warning_records[0], "artifact_update_sample", None) == {
        "kind": "artifact-update",
        "artifact": {
            "metadata": {
                "block_type": "text",
                "message_id": "msg-legacy-ws-1",
                "event_id": "evt-legacy-ws-1",
            },
            "content": "legacy-1",
        },
    }


@pytest.mark.asyncio
async def test_ws_error_metadata_callback_receives_session_not_found_code():
    websocket = _DummyWebSocket()
    observed: dict[str, object] = {}

    async def _on_error_metadata(payload: dict[str, object]) -> None:
        observed.update(payload)

    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_BrokenGatewayWithSessionNotFound(),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_error_metadata=_on_error_metadata,
    )

    payloads = [json.loads(item) for item in websocket.sent]
    assert observed["error_code"] == "session_not_found"
    assert payloads[-2]["event"] == "error"
    assert payloads[-2]["data"]["error_code"] == "session_not_found"


@pytest.mark.asyncio
async def test_ws_error_metadata_callback_falls_back_to_default_code_for_unstructured_error():
    websocket = _DummyWebSocket()
    observed: dict[str, object] = {}

    async def _on_error_metadata(payload: dict[str, object]) -> None:
        observed.update(payload)

    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_GatewayWithUnstructuredError(),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_error_metadata=_on_error_metadata,
    )

    payloads = [json.loads(item) for item in websocket.sent]
    assert observed["error_code"] == "upstream_stream_error"
    assert payloads[-2]["event"] == "error"
    assert payloads[-2]["data"]["error_code"] == "upstream_stream_error"


@pytest.mark.asyncio
async def test_ws_error_metadata_callback_exposes_structured_upstream_payload():
    websocket = _DummyWebSocket()
    observed: dict[str, object] = {}

    async def _on_error_metadata(payload: dict[str, object]) -> None:
        observed.update(payload)

    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_GatewayWithStructuredProtocolError(),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_error_metadata=_on_error_metadata,
    )

    payloads = [json.loads(item) for item in websocket.sent]
    assert observed["error_code"] == "invalid_params"
    assert observed["source"] == "upstream_a2a"
    assert observed["jsonrpc_code"] == -32602
    assert observed["missing_params"] == [
        {"name": "project_id", "required": True},
        {"name": "channel_id", "required": True},
    ]
    assert payloads[-2]["data"]["upstream_error"] == {
        "message": "project_id/channel_id required",
        "data": {"missing_params": ["project_id", "channel_id"]},
    }


@pytest.mark.asyncio
async def test_sse_emits_keepalive_heartbeat_when_upstream_is_idle(monkeypatch):
    monkeypatch.setattr(settings, "a2a_stream_heartbeat_interval", 0.01)
    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithDelayedEvents(
            [{"content": "late-event"}],
            delay_seconds=0.03,
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    payload = "".join(chunks)
    assert ": keep-alive" in payload
    assert '"content": "late-event"' in payload
    assert "event: stream_end" in payload


@pytest.mark.asyncio
async def test_ws_emits_keepalive_heartbeat_when_upstream_is_idle(monkeypatch):
    monkeypatch.setattr(settings, "a2a_stream_heartbeat_interval", 0.01)
    websocket = _DummyWebSocket()
    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_GatewayWithDelayedEvents(
            [{"content": "late-event"}],
            delay_seconds=0.03,
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )

    payloads = [json.loads(item) for item in websocket.sent]
    assert any(item.get("event") == "heartbeat" for item in payloads)
    assert any(item.get("content") == "late-event" for item in payloads)
    assert payloads[-1]["event"] == "stream_end"


@pytest.mark.asyncio
async def test_ws_stream_ignores_client_disconnect_without_sending_error() -> None:
    websocket = _DisconnectingWebSocket()
    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_GatewayWithDelayedEvents(
            [{"content": "late-event"}],
            delay_seconds=0.02,
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )


@pytest.mark.asyncio
async def test_sse_stream_reports_client_disconnect_to_finalized_callback() -> None:
    finalized_outcomes = []
    first_chunk_seen = asyncio.Event()

    async def _on_finalized(outcome):
        finalized_outcomes.append(outcome)

    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithSingleEventThenPending(
            first_event=_artifact_event(
                artifact_id="task-client-disconnect:stream",
                text="partial text",
                block_type="text",
            )
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        on_finalized=_on_finalized,
    )

    async def _consume_stream() -> None:
        async for _ in response.body_iterator:
            first_chunk_seen.set()

    consume_task = asyncio.create_task(_consume_stream())
    await asyncio.wait_for(first_chunk_seen.wait(), timeout=1.0)
    consume_task.cancel()
    with suppress(asyncio.CancelledError):
        await consume_task

    assert len(finalized_outcomes) == 1
    finalized = finalized_outcomes[0]
    assert finalized.success is False
    assert finalized.finish_reason == StreamFinishReason.CLIENT_DISCONNECT
    assert finalized.final_text == "partial text"
    assert finalized.error_code is None
    assert finalized.error_message is None


@pytest.mark.asyncio
async def test_consume_stream_finalized_callback_failure_is_isolated(caplog):
    async def _on_finalized(_outcome):
        raise RuntimeError("persist failed")

    with caplog.at_level(logging.WARNING):
        result = await a2a_invoke_service.consume_stream(
            gateway=_GatewayWithEvents(
                [
                    _artifact_event(
                        artifact_id="task-finalized:stream",
                        text="ok",
                        block_type="text",
                    ),
                    {"kind": "status-update", "final": True},
                ]
            ),
            resolved=object(),
            query="hello",
            context_id=None,
            metadata=None,
            validate_message=lambda _: [],
            logger=logging.getLogger(__name__),
            log_extra={},
            on_finalized=_on_finalized,
        )

    assert result.success is True
    assert result.final_text == "ok"
    assert any(
        "A2A consume stream finalized callback failed" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_consume_stream_accepts_single_blocking_message_payload() -> None:
    result = await a2a_invoke_service.consume_stream(
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "message",
                    "message_id": "msg-blocking-1",
                    "task_id": "task-blocking-1",
                    "parts": [{"type": "text", "text": "blocking-result"}],
                    "metadata": {
                        "event_id": "evt-blocking-1",
                        "block_type": "text",
                    },
                }
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )

    assert result.success is True
    assert result.finish_reason == StreamFinishReason.SUCCESS
    assert result.final_text == "blocking-result"
    assert result.terminal_event_seen is False


@pytest.mark.asyncio
async def test_send_ws_error_ignores_closed_socket_runtime_error() -> None:
    websocket = _ClosedWebSocket()
    await a2a_invoke_service.send_ws_error(
        websocket,
        message="Upstream streaming failed",
        error_code="upstream_stream_error",
    )


@pytest.mark.asyncio
async def test_consume_stream_treats_heartbeat_as_activity(monkeypatch):
    monkeypatch.setattr(settings, "a2a_stream_heartbeat_interval", 0.1)
    result = await a2a_invoke_service.consume_stream(
        gateway=_GatewayWithDelayedEvents(
            [
                _artifact_event(
                    artifact_id="task-heartbeat:stream",
                    text="late-event",
                    block_type="text",
                ),
                {"kind": "status-update", "final": True},
            ],
            delay_seconds=0.5,
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        idle_timeout_seconds=0.2,
        total_timeout_seconds=2.0,
    )
    assert result.success is True
    assert result.finish_reason == StreamFinishReason.SUCCESS
    assert result.final_text == "late-event"


@pytest.mark.asyncio
async def test_consume_stream_warns_non_contract_artifact_update_once_per_reason(
    caplog,
):
    caplog.set_level(logging.WARNING)
    result = await a2a_invoke_service.consume_stream(
        gateway=_GatewayWithEvents(
            [
                {
                    "kind": "artifact-update",
                    "artifact": {
                        "metadata": {
                            "block_type": "text",
                            "message_id": "msg-legacy-consume-1",
                            "event_id": "evt-legacy-consume-1",
                        },
                        "content": "legacy-1",
                    },
                },
                {
                    "kind": "artifact-update",
                    "artifact": {
                        "metadata": {
                            "block_type": "text",
                            "message_id": "msg-legacy-consume-2",
                            "event_id": "evt-legacy-consume-2",
                        },
                        "content": "legacy-2",
                    },
                },
                {"kind": "status-update", "final": True},
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )
    assert result.success is True
    assert result.final_text == ""
    warning_records = [
        record
        for record in caplog.records
        if record.levelname == "WARNING"
        and record.message == "Dropped non-contract artifact-update event"
    ]
    assert len(warning_records) == 1
    assert getattr(warning_records[0], "drop_reason", None) == "missing_text_parts"
    assert getattr(warning_records[0], "artifact_update_sample", None) == {
        "kind": "artifact-update",
        "artifact": {
            "metadata": {
                "block_type": "text",
                "message_id": "msg-legacy-consume-1",
                "event_id": "evt-legacy-consume-1",
            },
            "content": "legacy-1",
        },
    }


def test_build_artifact_update_log_sample_redacts_sensitive_fields_and_truncates():
    sample = build_artifact_update_log_sample(
        {
            "kind": "artifact-update",
            "metadata": {
                "Authorization": "Bearer secret-token-value",
                "nested": {
                    "access_token": "super-secret-token-value",
                },
            },
            "artifact": {
                "parts": [
                    {
                        "kind": "text",
                        "text": "x" * 200,
                    }
                ]
            },
        }
    )

    assert sample["metadata"]["Authorization"].startswith("Bearer")
    assert "secret-token-value" not in sample["metadata"]["Authorization"]
    assert sample["metadata"]["nested"]["access_token"] != "super-secret-token-value"
    truncated_text = sample["artifact"]["parts"][0]["text"]
    assert truncated_text.startswith("x" * 160)
    assert truncated_text.endswith("...<truncated:40 chars>")


@pytest.mark.asyncio
async def test_consume_stream_reports_total_timeout_with_partial_content(monkeypatch):
    monkeypatch.setattr(settings, "a2a_stream_heartbeat_interval", 0.01)
    monotonic_values = [0.0, 0.0, 0.01, 0.06, 0.06, 0.06, 0.06, 0.06]
    monotonic_index = {"value": 0}

    def _fake_monotonic() -> float:
        index = monotonic_index["value"]
        monotonic_index["value"] = min(index + 1, len(monotonic_values) - 1)
        return monotonic_values[index]

    wait_for_calls = {"value": 0}

    async def _fake_wait_for(awaitable, _timeout):
        wait_for_calls["value"] += 1
        if wait_for_calls["value"] == 1:
            return await awaitable
        timeout_task = asyncio.create_task(awaitable)
        timeout_task.cancel()
        with suppress(asyncio.CancelledError):
            await timeout_task
        raise asyncio.TimeoutError()

    monkeypatch.setattr("app.features.invoke.service.time.monotonic", _fake_monotonic)
    monkeypatch.setattr("app.features.invoke.service.asyncio.wait_for", _fake_wait_for)
    result = await a2a_invoke_service.consume_stream(
        gateway=_GatewayWithSingleEventThenPending(
            first_event=_artifact_event(
                artifact_id="task-total-timeout:stream",
                text="partial result",
                block_type="text",
            )
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        total_timeout_seconds=0.05,
        idle_timeout_seconds=1.0,
    )
    assert result.success is False
    assert result.finish_reason == StreamFinishReason.TIMEOUT_TOTAL
    assert result.error_code == "timeout"
    assert result.final_text == "partial result"


@pytest.mark.asyncio
async def test_consume_stream_reports_idle_timeout_with_partial_content(monkeypatch):
    monkeypatch.setattr(settings, "a2a_stream_heartbeat_interval", 0.0)
    monotonic_values = [0.0, 0.0, 0.01, 0.03, 0.04, 0.05, 0.06, 0.06, 0.06]
    monotonic_index = {"value": 0}

    def _fake_monotonic() -> float:
        index = monotonic_index["value"]
        monotonic_index["value"] = min(index + 1, len(monotonic_values) - 1)
        return monotonic_values[index]

    wait_for_calls = {"value": 0}

    async def _fake_wait_for(awaitable, _timeout):
        wait_for_calls["value"] += 1
        if wait_for_calls["value"] == 1:
            return await awaitable
        timeout_task = asyncio.create_task(awaitable)
        timeout_task.cancel()
        with suppress(asyncio.CancelledError):
            await timeout_task
        raise asyncio.TimeoutError()

    monkeypatch.setattr("app.features.invoke.service.time.monotonic", _fake_monotonic)
    monkeypatch.setattr("app.features.invoke.service.asyncio.wait_for", _fake_wait_for)
    result = await a2a_invoke_service.consume_stream(
        gateway=_GatewayWithSingleEventThenPending(
            first_event=_artifact_event(
                artifact_id="task-idle-timeout:stream",
                text="partial text",
                block_type="text",
            )
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        total_timeout_seconds=1.0,
        idle_timeout_seconds=0.05,
    )
    assert result.success is False
    assert result.finish_reason == StreamFinishReason.TIMEOUT_IDLE
    assert result.error_code == "timeout"
    assert result.final_text == "partial text"


def test_extract_binding_hints_from_serialized_event():
    (
        context_id,
        metadata,
    ) = a2a_invoke_service.extract_binding_hints_from_serialized_event(
        {
            "contextId": "ctx-1",
            "metadata": {
                "provider": "OpenCode",
                "shared": {
                    "session": {
                        "id": "upstream-1",
                    }
                },
            },
        }
    )
    assert context_id == "ctx-1"
    assert metadata["provider"] == "opencode"
    assert metadata["externalSessionId"] == "upstream-1"


def test_extract_binding_hints_from_invoke_result_merges_raw_payload():
    class _RawPayload:
        def model_dump(self, **kwargs):
            return {
                "contextId": "ctx-from-raw",
                "metadata": {
                    "provider": "opencode",
                    "shared": {
                        "session": {
                            "id": "raw-upstream",
                        }
                    },
                },
            }

    context_id, metadata = a2a_invoke_service.extract_binding_hints_from_invoke_result(
        {
            "success": True,
            "content": "ok",
            "contextId": "ctx-from-result",
            "metadata": {"externalSessionId": "result-upstream"},
            "raw": _RawPayload(),
        }
    )
    assert context_id == "ctx-from-raw"
    assert metadata["provider"] == "opencode"
    assert metadata["externalSessionId"] == "raw-upstream"


def test_extract_binding_hints_ignores_session_id_aliases():
    context_id, metadata = a2a_invoke_service.extract_binding_hints_from_invoke_result(
        {
            "success": True,
            "content": "ok",
            "result": {
                "provider": "OpenCode",
                "session_id": "alias-upstream-session",
            },
        }
    )
    assert context_id is None
    assert metadata["provider"] == "opencode"


def test_extract_binding_hints_falls_back_to_legacy_root_session_metadata():
    context_id, metadata = (
        a2a_invoke_service.extract_binding_hints_from_serialized_event(
            {
                "contextId": "ctx-legacy",
                "metadata": {
                    "provider": "OpenCode",
                    "externalSessionId": "legacy-upstream-1",
                },
            }
        )
    )
    assert context_id == "ctx-legacy"
    assert metadata["provider"] == "opencode"
    assert metadata["externalSessionId"] == "legacy-upstream-1"


def test_extract_binding_hints_extracts_canonical_shared_session_id():
    context_id, metadata = a2a_invoke_service.extract_binding_hints_from_invoke_result(
        {
            "success": True,
            "content": "ok",
            "metadata": {
                "provider": "OpenCode",
                "shared": {
                    "session": {
                        "id": "nested-upstream-session",
                    }
                },
            },
        }
    )
    assert context_id is None
    assert metadata["provider"] == "opencode"
    assert metadata["externalSessionId"] == "nested-upstream-session"


def test_extract_binding_hints_ignores_legacy_flat_opencode_session_id():
    context_id, metadata = a2a_invoke_service.extract_binding_hints_from_invoke_result(
        {
            "success": True,
            "content": "ok",
            "metadata": {
                "opencode_session_id": "legacy-flat-session-id",
            },
        }
    )
    assert context_id is None
    assert "provider" not in metadata
    assert "externalSessionId" not in metadata


def test_extract_binding_hints_ignores_legacy_flat_external_session_id_aliases():
    context_id, metadata = a2a_invoke_service.extract_binding_hints_from_invoke_result(
        {
            "success": True,
            "content": "ok",
            "metadata": {
                "external_session_id": "legacy-flat-session-id",
                "upstream_session_id": "legacy-upstream-session-id",
            },
        }
    )
    assert context_id is None
    assert "provider" not in metadata
    assert "externalSessionId" not in metadata


def test_extract_readable_content_prefers_raw_history_agent_message():
    readable = a2a_invoke_service.extract_readable_content_from_invoke_result(
        {
            "success": True,
            "content": '{"content":"opaque"}',
            "raw": {
                "history": [
                    {"role": "user", "parts": [{"kind": "text", "text": "Hi"}]},
                    {
                        "role": "agent",
                        "parts": [{"kind": "text", "text": "Hello from agent"}],
                    },
                ]
            },
        }
    )
    assert readable == "Hello from agent"


def test_extract_readable_content_parses_json_string_content():
    readable = a2a_invoke_service.extract_readable_content_from_invoke_result(
        {
            "success": True,
            "content": (
                '{"history":[{"role":"user","parts":[{"text":"Q"}]},'
                '{"role":"assistant","parts":[{"text":"A"}]}]}'
            ),
        }
    )
    assert readable == "A"


def test_extract_stream_identity_hints_from_serialized_event():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
        {
            "seq": 9,
            "artifact": {
                "metadata": {
                    "message_id": "msg-1",
                    "event_id": "evt-1",
                },
            },
        }
    )
    assert hints == {
        "upstream_message_id": "msg-1",
        "upstream_event_id": "evt-1",
        "upstream_event_seq": 9,
    }


def test_extract_stream_identity_hints_reads_seq_and_task_id_from_analysis():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
        {
            "metadata": {"taskId": "task-from-root"},
            "artifact": {
                "metadata": {
                    "message_id": "msg-1",
                    "event_id": "evt-1",
                    "seq": 99,
                },
            },
        }
    )
    assert hints == {
        "upstream_message_id": "msg-1",
        "upstream_event_id": "evt-1",
        "upstream_event_seq": 99,
        "upstream_task_id": "task-from-root",
    }


def test_extract_stream_identity_hints_from_invoke_result_prefers_raw_payload():
    class _RawPayload:
        def model_dump(self, **kwargs):  # noqa: ARG002
            return {
                "seq": 12,
                "metadata": {
                    "event_id": "evt-from-raw",
                    "message_id": "msg-from-raw",
                },
            }

    hints = a2a_invoke_service.extract_stream_identity_hints_from_invoke_result(
        {
            "seq": 2,
            "metadata": {
                "event_id": "evt-from-result",
                "message_id": "msg-from-result",
            },
            "raw": _RawPayload(),
        }
    )
    assert hints == {
        "upstream_message_id": "msg-from-raw",
        "upstream_event_id": "evt-from-raw",
        "upstream_event_seq": 12,
    }


def test_extract_stream_identity_hints_from_status_metadata_message_id():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_invoke_result(
        {
            "status": {
                "metadata": {
                    "message_id": "msg-from-status-message",
                }
            }
        }
    )
    assert hints["upstream_message_id"] == "msg-from-status-message"


def test_extract_stream_identity_hints_includes_upstream_task_id():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
        {
            "task": {
                "id": "task-abc",
            },
            "status": {
                "metadata": {
                    "message_id": "msg-1",
                    "event_id": "evt-1",
                }
            },
        }
    )

    assert hints["upstream_task_id"] == "task-abc"


def test_extract_stream_identity_hints_includes_nested_status_task_fallback():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
        {
            "status": {"task": {"id": "task-from-status"}},
            "artifact": {
                "metadata": {
                    "message_id": "msg-1",
                    "event_id": "evt-1",
                }
            },
        }
    )
    assert hints["upstream_task_id"] == "task-from-status"


def test_extract_stream_identity_hints_reads_shared_stream_metadata():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
        {
            "kind": "artifact-update",
            "artifact": {
                "parts": [{"kind": "text", "text": "noop"}],
                "metadata": {
                    "shared": {
                        "stream": {
                            "message_id": "msg-shared-stream",
                            "event_id": "evt-shared-stream",
                            "sequence": 12,
                        }
                    }
                },
            },
        }
    )

    assert hints["upstream_message_id"] == "msg-shared-stream"
    assert hints["upstream_event_id"] == "evt-shared-stream"
    assert hints["upstream_event_seq"] == 12


def test_extract_stream_chunk_reads_canonical_event_and_message_ids():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "kind": "artifact-update",
            "artifact": {
                "parts": [{"kind": "text", "text": "hello"}],
                "metadata": {
                    "block_type": "text",
                    "event_id": "evt-nested",
                    "message_id": "msg-nested",
                    "source": "stream",
                },
            },
        }
    )

    assert chunk is not None
    assert chunk["event_id"] == "evt-nested"
    assert chunk["message_id"] == "msg-nested"
    assert chunk["block_type"] == "text"
    assert chunk["content"] == "hello"
    assert chunk["append"] is True
    assert chunk["is_finished"] is False
    assert chunk["source"] == "stream"


def test_extract_stream_chunk_consumes_optional_seq_append_and_last_chunk():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "kind": "artifact-update",
            "seq": 8,
            "append": False,
            "lastChunk": True,
            "artifact": {
                "parts": [{"kind": "text", "text": "done"}],
                "metadata": {
                    "block_type": "text",
                    "event_id": "evt-opt",
                    "message_id": "msg-opt",
                },
            },
        }
    )

    assert chunk is not None
    assert chunk["seq"] == 8
    assert chunk["append"] is False
    assert chunk["is_finished"] is True


def test_extract_stream_chunk_accepts_artifact_level_last_chunk_alias():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "kind": "artifact-update",
            "artifact": {
                "last_chunk": True,
                "parts": [{"kind": "text", "text": "done"}],
                "metadata": {
                    "block_type": "text",
                    "event_id": "evt-artifact-last",
                    "message_id": "msg-artifact-last",
                },
            },
        }
    )

    assert chunk is not None
    assert chunk["is_finished"] is True


def test_extract_stream_chunk_accepts_missing_canonical_identity_metadata():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "kind": "artifact-update",
            "artifact": {
                "parts": [{"kind": "text", "text": "hello"}],
                "metadata": {
                    "block_type": "text",
                    "event_id": "evt-nested",
                },
            },
        }
    )

    assert chunk is not None
    assert chunk["event_id"] == "evt-nested"
    assert chunk["message_id"] is None


def test_extract_stream_chunk_accepts_message_payloads_with_root_parts():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "kind": "message",
            "messageId": "msg-root-1",
            "taskId": "task-root-1",
            "parts": [{"kind": "text", "text": "hello from message"}],
            "role": "agent",
            "metadata": {
                "shared": {
                    "stream": {
                        "event_id": "evt-root-1",
                        "source": "assistant_text",
                    }
                }
            },
        }
    )

    assert chunk is not None
    assert chunk["event_id"] == "evt-root-1"
    assert chunk["message_id"] == "msg-root-1"
    assert chunk["block_type"] == "text"
    assert chunk["content"] == "hello from message"
    assert chunk["append"] is False
    assert chunk["source"] == "assistant_text"


def test_ensure_outbound_stream_contract_normalizes_message_payloads():
    payload = {
        "kind": "message",
        "messageId": "msg-root-2",
        "parts": [{"kind": "text", "text": "render me"}],
        "role": "agent",
    }

    a2a_invoke_service._ensure_outbound_stream_contract(  # noqa: SLF001
        payload,
        event_sequence=4,
    )

    assert payload["kind"] == "artifact-update"
    assert payload["seq"] == 4
    assert payload["message_id"] == "msg-root-2"
    assert payload["event_id"] == "msg-root-2:4"
    assert payload["append"] is False
    assert payload["artifact"]["parts"] == [{"kind": "text", "text": "render me"}]
    assert payload["artifact"]["metadata"]["seq"] == 4
    assert "messageId" not in payload
    assert "parts" not in payload
    assert "role" not in payload


def test_serialize_stream_event_normalizes_message_payload_before_validation(
    monkeypatch: pytest.MonkeyPatch,
):
    seen_payloads: list[dict[str, object]] = []

    def _validate(payload: dict[str, object]) -> list[object]:
        seen_payloads.append(dict(payload))
        return []

    monkeypatch.setattr(settings, "debug", True)

    serialized = a2a_invoke_service.serialize_stream_event(
        _DumpableEvent(
            {
                "kind": "message",
                "messageId": "msg-serialize-1",
                "role": "agent",
                "parts": [{"kind": "text", "text": "hello"}],
            }
        ),
        validate_message=_validate,
    )

    assert serialized["kind"] == "artifact-update"
    assert serialized["append"] is False
    assert serialized["artifact"]["parts"] == [{"kind": "text", "text": "hello"}]
    assert "messageId" not in serialized
    assert "parts" not in serialized
    assert "role" not in serialized
    assert seen_payloads[0]["kind"] == "artifact-update"


def test_extract_stream_chunk_rejects_unsupported_explicit_block_type():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "kind": "artifact-update",
            "artifact": {
                "artifact_id": "task-generic:stream",
                "parts": [{"kind": "text", "text": "hello generic"}],
                "metadata": {"block_type": "custom_phase"},
            },
        }
    )

    assert chunk is None


def test_extract_stream_chunk_ignores_non_artifact_payloads():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {"content": "legacy-content"}
    )
    assert chunk is None


def test_extract_usage_hints_from_serialized_event():
    usage = a2a_invoke_service.extract_usage_hints_from_serialized_event(
        {
            "kind": "status-update",
            "final": True,
            "metadata": {
                "shared": {
                    "usage": {
                        "input_tokens": 120,
                        "outputTokens": "30",
                        "total_tokens": 150,
                        "reasoning_tokens": 12,
                        "cache_tokens": 6,
                        "cost": "0.0125",
                    },
                },
            },
        }
    )
    assert usage == {
        "input_tokens": 120,
        "output_tokens": 30,
        "total_tokens": 150,
        "reasoning_tokens": 12,
        "cache_tokens": 6,
        "cost": 0.0125,
    }


def test_extract_usage_hints_from_invoke_result_prefers_raw_payload():
    class _RawPayload:
        def model_dump(self, **kwargs):  # noqa: ARG002
            return {
                "metadata": {
                    "shared": {
                        "usage": {
                            "input_tokens": 66,
                            "output_tokens": 11,
                            "total_tokens": 77,
                            "cost": 0.0077,
                        },
                    },
                }
            }

    usage = a2a_invoke_service.extract_usage_hints_from_invoke_result(
        {
            "metadata": {
                "shared": {
                    "usage": {
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                        "cost": 0.0002,
                    },
                },
            },
            "raw": _RawPayload(),
        }
    )
    assert usage == {
        "input_tokens": 66,
        "output_tokens": 11,
        "total_tokens": 77,
        "cost": 0.0077,
    }


def test_extract_usage_hints_from_serialized_event_falls_back_to_legacy_metadata():
    usage = a2a_invoke_service.extract_usage_hints_from_serialized_event(
        {
            "kind": "status-update",
            "final": True,
            "metadata": {
                "usage": {
                    "input_tokens": 9,
                    "output_tokens": 3,
                    "total_tokens": 12,
                },
            },
        }
    )
    assert usage == {
        "input_tokens": 9,
        "output_tokens": 3,
        "total_tokens": 12,
    }


def test_coerce_payload_to_dict_raises_exception(caplog):
    class MockUnserializablePayload:
        def model_dump(self, exclude_none=True):  # noqa: ARG002
            _ = exclude_none
            raise ValueError("Cannot serialize this mock payload")

    payload = MockUnserializablePayload()
    with pytest.raises(ValueError, match="Payload serialization failed"):
        with caplog.at_level(logging.ERROR):
            coerce_payload_to_dict(payload)

    assert "Failed to dump A2A payload" in caplog.text
