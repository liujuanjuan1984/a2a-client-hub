from __future__ import annotations

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


def test_extract_binding_hints_accepts_session_id_aliases():
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
    assert metadata["externalSessionId"] == "alias-upstream-session"


def test_extract_binding_hints_from_opencode_namespace_session_id():
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
