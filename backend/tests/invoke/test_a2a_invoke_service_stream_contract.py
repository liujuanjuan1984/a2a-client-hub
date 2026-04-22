from __future__ import annotations

from tests.invoke.a2a_invoke_service_support import (
    _DumpableEvent,
    a2a_invoke_service,
    coerce_payload_to_dict,
    logging,
    pytest,
    settings,
)


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
        def model_dump(self, **kwargs):
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

    a2a_invoke_service._ensure_outbound_stream_contract(
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
        def model_dump(self, **kwargs):
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
        def model_dump(self, exclude_none=True):
            _ = exclude_none
            raise ValueError("Cannot serialize this mock payload")

    payload = MockUnserializablePayload()
    with pytest.raises(ValueError, match="Payload serialization failed"):
        with caplog.at_level(logging.ERROR):
            coerce_payload_to_dict(payload)

    assert "Failed to dump A2A payload" in caplog.text
