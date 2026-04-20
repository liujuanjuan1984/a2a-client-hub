from __future__ import annotations

from tests.invoke.a2a_invoke_service_support import (
    StreamFinishReason,
    _artifact_data_event,
    _artifact_event,
    _BrokenGateway,
    _BrokenGatewayWithSessionNotFound,
    _ClosedWebSocket,
    _DisconnectingWebSocket,
    _DummyWebSocket,
    _GatewayWithDelayedEvents,
    _GatewayWithEvents,
    _GatewayWithSingleEventThenPending,
    _GatewayWithStructuredProtocolError,
    _GatewayWithTimeoutError,
    _GatewayWithUnstructuredError,
    a2a_invoke_service,
    asyncio,
    build_artifact_update_log_sample,
    json,
    logging,
    pytest,
    settings,
    suppress,
)


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
