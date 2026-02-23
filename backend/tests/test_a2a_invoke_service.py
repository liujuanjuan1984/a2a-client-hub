from __future__ import annotations

import asyncio
import json
import logging

import pytest

from app.core.config import settings
from app.services.a2a_invoke_service import a2a_invoke_service


class _BrokenGateway:
    async def stream(self, **kwargs):
        raise RuntimeError("stream failed")
        yield  # pragma: no cover


class _DumpableEvent:
    def __init__(self, payload: dict):
        self._payload = payload

    def model_dump(self, exclude_none: bool = True):  # noqa: ARG002
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


class _DummyWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)


class _SessionNotFoundError(RuntimeError):
    def __init__(self, message: str, error_code: str):
        super().__init__(message)
        self.error_code = error_code


class _BrokenGatewayWithSessionNotFound:
    async def stream(self, **kwargs):  # noqa: ARG001
        if False:
            yield  # pragma: no cover
        raise _SessionNotFoundError("session not found", "session_not_found")


class _GatewayWithUnstructuredError:
    async def stream(self, **kwargs):  # noqa: ARG001
        if False:
            yield  # pragma: no cover
        raise RuntimeError("session missing")


def _artifact_event(
    *,
    artifact_id: str,
    text: str,
    block_type: str | None = None,
    source: str | None = None,
    append: bool | None = None,
) -> dict:
    metadata: dict[str, dict[str, str]] = {}
    if block_type or source:
        opencode: dict[str, str] = {}
        if block_type:
            opencode["block_type"] = block_type
        if source:
            opencode["source"] = source
        metadata["opencode"] = opencode

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
async def test_sse_on_complete_metadata_includes_message_blocks():
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

    assert metadata_payloads == [
        {
            "message_blocks": [
                {
                    "id": "block-1",
                    "type": "reasoning",
                    "content": "thinking",
                    "is_finished": True,
                },
                {
                    "id": "block-2",
                    "type": "tool_call",
                    "content": "run_tool()",
                    "is_finished": True,
                },
                {
                    "id": "block-3",
                    "type": "text",
                    "content": "done",
                    "is_finished": False,
                },
            ]
        }
    ]


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
async def test_sse_complete_metadata_uses_configurable_max_chars(monkeypatch):
    original = settings.opencode_stream_metadata_max_chars
    monkeypatch.setattr(settings, "opencode_stream_metadata_max_chars", 5)

    metadata_payloads: list[dict] = []

    async def _on_complete_metadata(payload: dict):
        metadata_payloads.append(payload)

    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                _artifact_event(
                    artifact_id="task-1:stream:reasoning",
                    text="123456789",
                    block_type="reasoning",
                ),
                _artifact_event(
                    artifact_id="task-1:stream:tool_call",
                    text="abcdefghi",
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

    assert metadata_payloads == [
        {
            "message_blocks": [
                {
                    "id": "block-1",
                    "type": "reasoning",
                    "content": "12345",
                    "is_finished": True,
                },
                {
                    "id": "block-2",
                    "type": "tool_call",
                    "content": "abcde",
                    "is_finished": True,
                },
                {
                    "id": "block-3",
                    "type": "text",
                    "content": "done",
                    "is_finished": False,
                },
            ]
        }
    ]
    monkeypatch.setattr(
        settings, "opencode_stream_metadata_max_chars", original
    )  # explicit reset for safety


@pytest.mark.asyncio
async def test_sse_on_complete_falls_back_for_non_typed_events():
    completed: list[str] = []

    async def _on_complete(text: str):
        completed.append(text)

    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                _artifact_event(
                    artifact_id="legacy-stream",
                    text="foo",
                ),
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

    assert completed == ["foobar"]


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
                    "message_id": "msg-block-type",
                    "artifact": {
                        "artifact_id": "task-block-type:stream",
                        "parts": [{"kind": "text", "text": "Hello alias"}],
                        "metadata": {
                            "opencode": {
                                "block_type": "text",
                            }
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
                {"content": "kept"},
            ]
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda payload: (
            ["invalid artifact event"]
            if payload.get("kind") == "artifact-update"
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
    assert observed_events == [{"content": "kept"}]


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
async def test_consume_stream_treats_heartbeat_as_activity(monkeypatch):
    monkeypatch.setattr(settings, "a2a_stream_heartbeat_interval", 0.01)
    result = await a2a_invoke_service.consume_stream(
        gateway=_GatewayWithDelayedEvents(
            [{"content": "late-event"}, {"kind": "status-update", "final": True}],
            delay_seconds=0.05,
        ),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
        idle_timeout_seconds=0.02,
        total_timeout_seconds=0.2,
    )
    assert result["success"] is True
    assert result["content"] == "late-event"


def test_extract_binding_hints_from_serialized_event():
    (
        context_id,
        metadata,
    ) = a2a_invoke_service.extract_binding_hints_from_serialized_event(
        {
            "contextId": "ctx-1",
            "metadata": {
                "provider": "OpenCode",
                "externalSessionId": "upstream-1",
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
                    "externalSessionId": "raw-upstream",
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
    assert "externalSessionId" not in metadata


def test_extract_binding_hints_extracts_nested_opencode_session_id():
    context_id, metadata = a2a_invoke_service.extract_binding_hints_from_invoke_result(
        {
            "success": True,
            "content": "ok",
            "metadata": {
                "opencode": {
                    "session_id": "nested-upstream-session",
                }
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
            "event_id": "evt-1",
            "seq": 9,
            "artifact": {
                "message_id": "msg-1",
            },
        }
    )
    assert hints == {
        "upstream_message_id": "msg-1",
        "upstream_event_id": "evt-1",
        "upstream_event_seq": 9,
    }


def test_extract_stream_identity_hints_from_invoke_result_prefers_raw_payload():
    class _RawPayload:
        def model_dump(self, **kwargs):  # noqa: ARG002
            return {
                "event_id": "evt-from-raw",
                "seq": 12,
                "message_id": "msg-from-raw",
            }

    hints = a2a_invoke_service.extract_stream_identity_hints_from_invoke_result(
        {
            "event_id": "evt-from-result",
            "seq": 2,
            "message_id": "msg-from-result",
            "raw": _RawPayload(),
        }
    )
    assert hints == {
        "upstream_message_id": "msg-from-raw",
        "upstream_event_id": "evt-from-raw",
        "upstream_event_seq": 12,
    }


def test_extract_stream_identity_hints_from_status_message_message_id():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_invoke_result(
        {
            "status": {
                "message": {
                    "messageId": "msg-from-status-message",
                }
            }
        }
    )
    assert hints["upstream_message_id"] == "msg-from-status-message"


def test_extract_usage_hints_from_serialized_event():
    usage = a2a_invoke_service.extract_usage_hints_from_serialized_event(
        {
            "kind": "status-update",
            "final": True,
            "metadata": {
                "opencode": {
                    "usage": {
                        "input_tokens": 120,
                        "outputTokens": "30",
                        "total_tokens": 150,
                        "reasoning_tokens": 12,
                        "cache_tokens": 6,
                        "cost": "0.0125",
                    }
                }
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
                    "opencode": {
                        "usage": {
                            "input_tokens": 66,
                            "output_tokens": 11,
                            "total_tokens": 77,
                            "cost": 0.0077,
                        }
                    }
                }
            }

    usage = a2a_invoke_service.extract_usage_hints_from_invoke_result(
        {
            "metadata": {
                "opencode": {
                    "usage": {
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                        "cost": 0.0002,
                    }
                }
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


def test_extract_tool_calls_from_payload_supports_direct_tool_call():
    tool_calls = a2a_invoke_service.extract_tool_calls_from_payload(
        {
            "kind": "tool-call",
            "tool": {
                "name": "hub_invoke_agent",
                "arguments": '{"agent_id": "x", "prompt": "hi"}',
            },
            "toolCall": {
                "name": "ignored",
            },
            "tool_call_id": "tc-1",
        }
    )
    assert tool_calls == [
        {
            "tool_name": "hub_invoke_agent",
            "tool_call_id": "tc-1",
            "tool_args": {"agent_id": "x", "prompt": "hi"},
        }
    ]


def test_extract_tool_calls_from_payload_supports_nested_artifact_tool_parts():
    tool_calls = a2a_invoke_service.extract_tool_calls_from_payload(
        {
            "kind": "artifact-update",
            "artifact": {
                "parts": [
                    {
                        "kind": "text",
                        "text": '{"tool_name": "hub_invoke_agent", "tool_call_id": "tc-2", "tool_args": {"agent_id": "y", "prompt": "ok"}}',
                    },
                    {
                        "kind": "text",
                        "text": "ignored",
                    },
                ],
            },
            "metadata": {
                "tool": {
                    "name": "legacy",
                    "arguments": '{"tool_name": "legacy", "tool_call_id": "legacy", "tool_args": {}}',
                }
            },
        }
    )
    assert {
        "tool_name": "hub_invoke_agent",
        "tool_call_id": "tc-2",
        "tool_args": {"agent_id": "y", "prompt": "ok"},
    } in tool_calls
