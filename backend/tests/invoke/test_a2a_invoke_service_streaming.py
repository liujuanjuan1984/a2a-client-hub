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


def _status_update_event(
    *,
    state: str,
    metadata: dict | None = None,
) -> dict:
    payload: dict = {"statusUpdate": {"status": {"state": state}}}
    if metadata is not None:
        payload["statusUpdate"]["metadata"] = metadata
    return payload


def _message_event(
    *,
    message_id: str,
    text: str,
    metadata: dict | None = None,
) -> dict:
    payload: dict = {
        "message": {
            "messageId": message_id,
            "role": "ROLE_AGENT",
            "parts": [{"text": text}],
        }
    }
    if metadata is not None:
        payload["message"]["metadata"] = metadata
    return payload


def _extract_stream_payloads(frames: list[str]) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in "".join(frames).splitlines()
        if line.startswith("data: ")
        and (
            '"artifactUpdate"' in line
            or '"message"' in line
            or '"statusUpdate"' in line
        )
    ]


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
                _artifact_event(
                    artifact_id="task-block-type:stream",
                    text="Hello alias",
                    block_type="text",
                    message_id="msg-block-type",
                    event_id="evt-block-type-1",
                )
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
                _artifact_event(
                    artifact_id="task-generic:stream",
                    text="Hello generic",
                )
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
            if payload.get("artifactUpdate", {}).get("artifact", {}).get("artifactId")
            == "task-invalid:stream"
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
    assert len(observed_events) == 1
    assert observed_events[0]["artifactUpdate"]["artifact"]["artifactId"] == (
        "task-valid:stream"
    )
    assert observed_events[0]["artifactUpdate"]["artifact"]["parts"] == [
        {"text": "kept"}
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
                    "artifactUpdate": {
                        "artifact": {
                            "metadata": {
                                "shared": {
                                    "stream": {
                                        "block_type": "text",
                                        "messageId": "msg-legacy-1",
                                        "eventId": "evt-legacy-1",
                                    }
                                }
                            }
                        }
                    }
                },
                {
                    "artifactUpdate": {
                        "artifact": {
                            "metadata": {
                                "shared": {
                                    "stream": {
                                        "block_type": "text",
                                        "messageId": "msg-legacy-2",
                                        "eventId": "evt-legacy-2",
                                    }
                                }
                            }
                        }
                    }
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
    warning_sample = getattr(warning_records[0], "artifact_update_sample", None)
    assert isinstance(warning_sample, dict)
    assert (
        warning_sample["artifactUpdate"]["artifact"]["metadata"]["shared"]["stream"][
            "block_type"
        ]
        == "<max_depth_exceeded>"
    )


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
                    "artifactUpdate": {
                        "artifact": {
                            "metadata": {
                                "shared": {
                                    "stream": {
                                        "block_type": "text",
                                    }
                                }
                            }
                        }
                    }
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
    warning_sample = getattr(warning_records[0], "artifact_update_sample", None)
    assert isinstance(warning_sample, dict)
    assert (
        warning_sample["artifactUpdate"]["artifact"]["metadata"]["shared"]["stream"][
            "block_type"
        ]
        == "<max_depth_exceeded>"
    )


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
                _status_update_event(state="TASK_STATE_COMPLETED"),
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
    assert '"artifactUpdate"' in payload
    assert '"block_type": "tool_call"' in payload


@pytest.mark.asyncio
async def test_sse_cache_replays_mutated_event_payload_from_on_event():
    from app.features.invoke.stream_cache.memory_cache import global_stream_cache

    cache_key = "test-cache-on-event-mutation"
    upstream_event = {
        "artifactUpdate": {
            "artifact": {
                "artifactId": "task-cache:stream:text",
                "parts": [{"text": "hello"}],
                "metadata": {
                    "shared": {
                        "stream": {
                            "block_type": "text",
                            "eventId": "evt-cache-1",
                            "messageId": "msg-upstream-1",
                        }
                    }
                },
            }
        }
    }

    async def _rewrite_message_id(payload: dict) -> None:
        payload["artifactUpdate"]["artifact"]["metadata"]["shared"]["stream"][
            "messageId"
        ] = "msg-local-1"

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

    initial_payload = next(
        payload
        for payload in _extract_stream_payloads(initial_frames)
        if "artifactUpdate" in payload
    )
    initial_shared_stream = initial_payload["artifactUpdate"]["metadata"]["shared"][
        "stream"
    ]
    assert initial_shared_stream["messageId"] == "msg-local-1"
    assert initial_shared_stream["seq"] == 1
    assert initial_shared_stream["eventId"] == "evt-cache-1"

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

    replay_payload = next(
        payload
        for payload in _extract_stream_payloads(replay_frames)
        if "artifactUpdate" in payload
    )
    replay_shared_stream = replay_payload["artifactUpdate"]["metadata"]["shared"][
        "stream"
    ]
    assert replay_shared_stream["messageId"] == "msg-local-1"
    assert replay_shared_stream["seq"] == 1
    assert replay_shared_stream["eventId"] == "evt-cache-1"

    await global_stream_cache.mark_completed(cache_key)


@pytest.mark.asyncio
async def test_sse_normalizes_outbound_seq_to_monotonic_event_cursor():
    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                {
                    "artifactUpdate": {
                        "artifact": {
                            "artifactId": "task-sse:stream:text:1",
                            "parts": [{"text": "hello"}],
                            "metadata": {
                                "shared": {
                                    "stream": {
                                        "block_type": "text",
                                        "eventId": "evt-sse-1",
                                        "messageId": "msg-sse-1",
                                        "sequence": 9,
                                    }
                                }
                            },
                        }
                    }
                },
                {
                    "artifactUpdate": {
                        "artifact": {
                            "artifactId": "task-sse:stream:text:2",
                            "parts": [{"text": " world"}],
                            "metadata": {
                                "shared": {
                                    "stream": {
                                        "block_type": "text",
                                        "eventId": "evt-sse-2",
                                        "messageId": "msg-sse-1",
                                        "sequence": 12,
                                    }
                                }
                            },
                        }
                    }
                },
                _status_update_event(state="TASK_STATE_COMPLETED"),
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

    payloads = _extract_stream_payloads(frames)
    artifact_payloads = [payload for payload in payloads if "artifactUpdate" in payload]
    assert [
        payload["artifactUpdate"]["metadata"]["shared"]["stream"]["seq"]
        for payload in artifact_payloads
    ] == [1, 2]
    assert payloads[-1]["statusUpdate"]["metadata"]["shared"]["stream"]["seq"] == 3


@pytest.mark.asyncio
async def test_sse_preserves_canonical_message_payload_for_upstream_message_events():
    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                _message_event(
                    message_id="msg-upstream-sse-1",
                    text="hello from raw message",
                ),
                _status_update_event(state="TASK_STATE_COMPLETED"),
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

    payloads = _extract_stream_payloads(frames)
    message_payload = next(payload for payload in payloads if "message" in payload)
    assert message_payload["message"]["messageId"] == "msg-upstream-sse-1"
    assert message_payload["message"]["role"] == "ROLE_AGENT"
    assert message_payload["message"]["parts"] == [{"text": "hello from raw message"}]
    assert message_payload["message"]["metadata"]["shared"]["stream"] == {
        "seq": 1,
        "messageId": "msg-upstream-sse-1",
        "eventId": "msg-upstream-sse-1:1",
    }


@pytest.mark.asyncio
async def test_sse_breaks_stream_after_terminal_status_update():
    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                _status_update_event(state="TASK_STATE_INPUT_REQUIRED"),
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
    assert '"statusUpdate"' in payload
    assert "should-not-be-forwarded" not in payload
    assert "event: stream_end" in payload


@pytest.mark.asyncio
async def test_sse_emits_persisted_completion_ack_before_stream_end():
    async def _on_finalized(_outcome):
        return {
            "statusUpdate": {
                "status": {"state": "TASK_STATE_COMPLETED"},
                "metadata": {
                    "shared": {
                        "stream": {
                            "messageId": "msg-persisted-sse-1",
                            "completionPhase": "persisted",
                        }
                    }
                },
            }
        }

    response = a2a_invoke_service.stream_sse(
        gateway=_GatewayWithEvents(
            [
                _artifact_event(
                    artifact_id="task-persisted-sse:stream",
                    text="ok",
                    block_type="text",
                ),
                _status_update_event(state="TASK_STATE_COMPLETED"),
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
    persisted_index = payload.index('"completionPhase": "persisted"')
    stream_end_index = payload.index("event: stream_end")
    assert persisted_index < stream_end_index


@pytest.mark.asyncio
async def test_ws_breaks_stream_after_terminal_status_update():
    websocket = _DummyWebSocket()
    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_GatewayWithEvents(
            [
                _status_update_event(state="TASK_STATE_INPUT_REQUIRED"),
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
    assert "statusUpdate" in payloads[0]
    assert payloads[-1]["event"] == "stream_end"
    assert not any(
        item.get("content") == "should-not-be-forwarded" for item in payloads
    )


@pytest.mark.asyncio
async def test_ws_preserves_canonical_message_payload_for_upstream_message_events():
    websocket = _DummyWebSocket()

    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_GatewayWithEvents(
            [
                _message_event(
                    message_id="msg-upstream-ws-1",
                    text="hello from raw message",
                ),
                _status_update_event(state="TASK_STATE_COMPLETED"),
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
        and (
            '"artifactUpdate"' in item
            or '"message"' in item
            or '"statusUpdate"' in item
        )
    ]
    message_payload = next(payload for payload in payloads if "message" in payload)
    assert message_payload["message"]["messageId"] == "msg-upstream-ws-1"
    assert message_payload["message"]["role"] == "ROLE_AGENT"
    assert message_payload["message"]["parts"] == [{"text": "hello from raw message"}]
    assert message_payload["message"]["metadata"]["shared"]["stream"] == {
        "seq": 1,
        "messageId": "msg-upstream-ws-1",
        "eventId": "msg-upstream-ws-1:1",
    }


@pytest.mark.asyncio
async def test_ws_emits_persisted_completion_ack_before_stream_end():
    websocket = _DummyWebSocket()

    async def _on_finalized(_outcome):
        return {
            "statusUpdate": {
                "status": {"state": "TASK_STATE_COMPLETED"},
                "metadata": {
                    "shared": {
                        "stream": {
                            "messageId": "msg-persisted-ws-1",
                            "completionPhase": "persisted",
                        }
                    }
                },
            }
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
                _status_update_event(state="TASK_STATE_COMPLETED"),
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
        if item.get("statusUpdate", {})
        .get("metadata", {})
        .get("shared", {})
        .get("stream", {})
        .get("completionPhase")
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
        if "artifactUpdate" not in payload:
            return
        payload["artifactUpdate"]["artifact"]["metadata"]["shared"]["stream"][
            "messageId"
        ] = "msg-local-ws-1"

    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_GatewayWithEvents(
            [
                {
                    "artifactUpdate": {
                        "artifact": {
                            "artifactId": "task-ws:stream:text",
                            "parts": [{"text": "hello"}],
                            "metadata": {"shared": {"stream": {"block_type": "text"}}},
                        }
                    }
                },
                _status_update_event(state="TASK_STATE_COMPLETED"),
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
        if item.startswith("{") and '"artifactUpdate"' in item
    ]
    assert payloads
    assert payloads[0]["artifactUpdate"]["metadata"]["shared"]["stream"] == {
        "seq": 1,
        "messageId": "msg-local-ws-1",
        "eventId": "msg-local-ws-1:1",
    }


@pytest.mark.asyncio
async def test_ws_normalizes_outbound_seq_to_monotonic_event_cursor():
    websocket = _DummyWebSocket()

    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_GatewayWithEvents(
            [
                {
                    "artifactUpdate": {
                        "artifact": {
                            "artifactId": "task-ws:stream:text:1",
                            "parts": [{"text": "hello"}],
                            "metadata": {
                                "shared": {
                                    "stream": {
                                        "block_type": "text",
                                        "eventId": "evt-ws-1",
                                        "messageId": "msg-ws-1",
                                        "sequence": 9,
                                    }
                                }
                            },
                        }
                    }
                },
                {
                    "artifactUpdate": {
                        "artifact": {
                            "artifactId": "task-ws:stream:text:2",
                            "parts": [{"text": " world"}],
                            "metadata": {
                                "shared": {
                                    "stream": {
                                        "block_type": "text",
                                        "eventId": "evt-ws-2",
                                        "messageId": "msg-ws-1",
                                        "sequence": 12,
                                    }
                                }
                            },
                        }
                    }
                },
                _status_update_event(state="TASK_STATE_COMPLETED"),
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
        and ('"artifactUpdate"' in item or '"statusUpdate"' in item)
    ]
    artifact_payloads = [payload for payload in payloads if "artifactUpdate" in payload]
    assert [
        payload["artifactUpdate"]["metadata"]["shared"]["stream"]["seq"]
        for payload in artifact_payloads
    ] == [1, 2]
    assert payloads[-1]["statusUpdate"]["metadata"]["shared"]["stream"]["seq"] == 3


@pytest.mark.asyncio
async def test_ws_warns_non_contract_artifact_update_once_per_reason(caplog):
    websocket = _DummyWebSocket()
    caplog.set_level(logging.WARNING)
    await a2a_invoke_service.stream_ws(
        websocket=websocket,
        gateway=_GatewayWithEvents(
            [
                {
                    "artifactUpdate": {
                        "artifact": {
                            "metadata": {
                                "shared": {
                                    "stream": {
                                        "block_type": "text",
                                        "messageId": "msg-legacy-ws-1",
                                        "eventId": "evt-legacy-ws-1",
                                    }
                                }
                            }
                        }
                    }
                },
                {
                    "artifactUpdate": {
                        "artifact": {
                            "metadata": {
                                "shared": {
                                    "stream": {
                                        "block_type": "text",
                                        "messageId": "msg-legacy-ws-2",
                                        "eventId": "evt-legacy-ws-2",
                                    }
                                }
                            }
                        }
                    }
                },
                _status_update_event(state="TASK_STATE_COMPLETED"),
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
    warning_sample = getattr(warning_records[0], "artifact_update_sample", None)
    assert isinstance(warning_sample, dict)
    assert (
        warning_sample["artifactUpdate"]["artifact"]["metadata"]["shared"]["stream"][
            "block_type"
        ]
        == "<max_depth_exceeded>"
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
                    _status_update_event(state="TASK_STATE_COMPLETED"),
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
                    "message": {
                        "messageId": "msg-blocking-1",
                        "taskId": "task-blocking-1",
                        "role": "ROLE_AGENT",
                        "parts": [{"type": "text", "text": "blocking-result"}],
                        "metadata": {
                            "shared": {
                                "stream": {
                                    "eventId": "evt-blocking-1",
                                    "block_type": "text",
                                }
                            }
                        },
                    }
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
                _status_update_event(state="TASK_STATE_COMPLETED"),
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
                    "artifactUpdate": {
                        "artifact": {
                            "metadata": {
                                "shared": {
                                    "stream": {
                                        "block_type": "text",
                                        "messageId": "msg-legacy-consume-1",
                                        "eventId": "evt-legacy-consume-1",
                                    }
                                }
                            }
                        }
                    }
                },
                {
                    "artifactUpdate": {
                        "artifact": {
                            "metadata": {
                                "shared": {
                                    "stream": {
                                        "block_type": "text",
                                        "messageId": "msg-legacy-consume-2",
                                        "eventId": "evt-legacy-consume-2",
                                    }
                                }
                            }
                        }
                    }
                },
                _status_update_event(state="TASK_STATE_COMPLETED"),
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
    warning_sample = getattr(warning_records[0], "artifact_update_sample", None)
    assert isinstance(warning_sample, dict)
    assert (
        warning_sample["artifactUpdate"]["artifact"]["metadata"]["shared"]["stream"][
            "block_type"
        ]
        == "<max_depth_exceeded>"
    )


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
