from __future__ import annotations

from app.features.invoke.stream_payloads import resolve_stream_content_envelope
from tests.invoke.a2a_invoke_service_support import (
    _DumpableEvent,
    a2a_invoke_service,
    coerce_payload_to_dict,
    logging,
    pytest,
    settings,
)


def test_resolve_stream_content_envelope_prefers_nested_status_message_content():
    envelope = resolve_stream_content_envelope(
        {
            "statusUpdate": {
                "status": {
                    "state": "TASK_STATE_WORKING",
                    "message": {
                        "messageId": "msg-status-envelope",
                        "parts": [{"text": "hello"}],
                        "role": "ROLE_AGENT",
                    },
                },
                "metadata": {"shared": {"stream": {"eventId": "evt-status-envelope"}}},
            }
        }
    )

    assert envelope.event_kind == "status-update"
    assert envelope.content_source_kind == "status_message"
    assert envelope.status_message["messageId"] == "msg-status-envelope"
    assert envelope.artifact["parts"] == [{"text": "hello"}]
    assert envelope.shared_stream["eventId"] == "evt-status-envelope"


def test_extract_stream_identity_hints_from_serialized_event():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {"parts": [{"text": "noop"}]},
                "metadata": {
                    "shared": {
                        "stream": {
                            "messageId": "msg-1",
                            "eventId": "evt-1",
                            "seq": 9,
                        }
                    }
                },
            }
        }
    )
    assert hints == {
        "upstream_message_id": "msg-1",
        "upstream_event_id": "evt-1",
        "upstream_event_seq": 9,
    }


def test_extract_stream_identity_hints_accepts_snake_case_stream_fields():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {"parts": [{"text": "noop"}]},
                "metadata": {
                    "shared": {
                        "stream": {
                            "message_id": "msg-snake-1",
                            "event_id": "evt-snake-1",
                            "sequence": 13,
                        }
                    }
                },
            }
        }
    )
    assert hints == {
        "upstream_message_id": "msg-snake-1",
        "upstream_event_id": "evt-snake-1",
        "upstream_event_seq": 13,
    }


def test_extract_stream_identity_hints_reads_seq_and_task_id_from_analysis():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
        {
            "artifactUpdate": {
                "taskId": "task-from-root",
                "artifact": {"parts": [{"text": "noop"}]},
                "metadata": {
                    "shared": {
                        "stream": {
                            "messageId": "msg-1",
                            "eventId": "evt-1",
                            "seq": 99,
                        }
                    },
                },
            }
        }
    )
    assert hints == {
        "upstream_message_id": "msg-1",
        "upstream_event_id": "evt-1",
        "upstream_event_seq": 99,
        "upstream_task_id": "task-from-root",
    }


def test_extract_stream_identity_hints_ignores_legacy_metadata_task_id_alias():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {"parts": [{"text": "noop"}]},
                "metadata": {
                    "taskId": "task-from-metadata",
                    "shared": {
                        "stream": {
                            "messageId": "msg-1",
                            "eventId": "evt-1",
                            "seq": 99,
                        }
                    },
                },
            }
        }
    )
    assert "upstream_task_id" not in hints


def test_extract_stream_identity_hints_from_invoke_result_prefers_raw_payload():
    class _RawPayload:
        def model_dump(self, **kwargs):
            return {
                "statusUpdate": {
                    "status": {"state": "TASK_STATE_WORKING"},
                    "metadata": {
                        "shared": {
                            "stream": {
                                "eventId": "evt-from-raw",
                                "messageId": "msg-from-raw",
                                "seq": 12,
                            }
                        }
                    },
                },
            }

    hints = a2a_invoke_service.extract_stream_identity_hints_from_invoke_result(
        {
            "statusUpdate": {
                "status": {"state": "TASK_STATE_WORKING"},
                "metadata": {
                    "shared": {
                        "stream": {
                            "eventId": "evt-from-result",
                            "messageId": "msg-from-result",
                            "seq": 2,
                        }
                    }
                },
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
            "statusUpdate": {
                "status": {"state": "TASK_STATE_WORKING"},
                "metadata": {
                    "shared": {"stream": {"messageId": "msg-from-status-message"}},
                },
            }
        }
    )
    assert hints["upstream_message_id"] == "msg-from-status-message"


def test_extract_stream_identity_hints_from_nested_status_message_fields():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
        {
            "statusUpdate": {
                "status": {
                    "state": "TASK_STATE_WORKING",
                    "message": {
                        "messageId": "msg-from-nested-status",
                        "taskId": "task-from-nested-status",
                        "parts": [{"text": "hello"}],
                    },
                }
            }
        }
    )
    assert hints["upstream_message_id"] == "msg-from-nested-status"
    assert hints["upstream_task_id"] == "task-from-nested-status"


def test_extract_stream_identity_hints_includes_upstream_task_id():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
        {
            "task": {
                "id": "task-abc",
                "status": {
                    "state": "TASK_STATE_WORKING",
                    "metadata": {
                        "shared": {
                            "stream": {
                                "messageId": "msg-1",
                                "eventId": "evt-1",
                            }
                        }
                    },
                },
            },
        }
    )

    assert hints["upstream_task_id"] == "task-abc"


def test_extract_stream_identity_hints_includes_nested_status_task_fallback():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
        {
            "statusUpdate": {
                "status": {
                    "state": "TASK_STATE_WORKING",
                    "task": {"id": "task-from-status"},
                },
                "metadata": {
                    "shared": {
                        "stream": {
                            "messageId": "msg-1",
                            "eventId": "evt-1",
                        }
                    }
                },
            },
        }
    )
    assert hints["upstream_task_id"] == "task-from-status"


def test_extract_stream_identity_hints_reads_shared_stream_metadata():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {"parts": [{"text": "noop"}]},
                "metadata": {
                    "shared": {
                        "stream": {
                            "messageId": "msg-shared-stream",
                            "eventId": "evt-shared-stream",
                            "seq": 12,
                        }
                    }
                },
            }
        }
    )

    assert hints["upstream_message_id"] == "msg-shared-stream"
    assert hints["upstream_event_id"] == "evt-shared-stream"
    assert hints["upstream_event_seq"] == 12


def test_extract_stream_identity_hints_accepts_sequence_alias():
    hints = a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {"parts": [{"text": "noop"}]},
                "metadata": {
                    "shared": {
                        "stream": {
                            "messageId": "msg-legacy-sequence",
                            "eventId": "evt-legacy-sequence",
                            "sequence": 12,
                        }
                    }
                },
            }
        }
    )

    assert hints["upstream_message_id"] == "msg-legacy-sequence"
    assert hints["upstream_event_id"] == "evt-legacy-sequence"
    assert hints["upstream_event_seq"] == 12


def test_extract_stream_chunk_reads_canonical_event_and_message_ids():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {"parts": [{"text": "hello"}]},
                "metadata": {
                    "shared": {
                        "stream": {
                            "blockType": "text",
                            "op": "append",
                            "eventId": "evt-nested",
                            "messageId": "msg-nested",
                            "source": "stream",
                        }
                    },
                },
            }
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
            "artifactUpdate": {
                "lastChunk": True,
                "artifact": {"parts": [{"text": "done"}]},
                "metadata": {
                    "shared": {
                        "stream": {
                            "blockType": "text",
                            "op": "replace",
                            "eventId": "evt-opt",
                            "messageId": "msg-opt",
                            "seq": 8,
                        }
                    },
                },
            }
        }
    )

    assert chunk is not None
    assert chunk["seq"] == 8
    assert chunk["append"] is False
    assert chunk["is_finished"] is True


def test_extract_stream_chunk_ignores_artifact_level_last_chunk_without_finalize():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {
                    "lastChunk": True,
                    "parts": [{"text": "done"}],
                },
                "metadata": {
                    "shared": {
                        "stream": {
                            "blockType": "text",
                            "op": "append",
                            "eventId": "evt-artifact-last",
                            "messageId": "msg-artifact-last",
                        }
                    }
                },
            }
        }
    )

    assert chunk is not None
    assert chunk["is_finished"] is False


def test_extract_stream_chunk_accepts_missing_canonical_identity_metadata():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {"parts": [{"text": "hello"}]},
                "metadata": {
                    "shared": {
                        "stream": {
                            "blockType": "text",
                            "op": "append",
                            "eventId": "evt-nested",
                        }
                    }
                },
            }
        }
    )

    assert chunk is not None
    assert chunk["event_id"] == "evt-nested"
    assert chunk["message_id"] is None


def test_extract_stream_chunk_inferrs_message_payloads_without_explicit_block_contract():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "message": {
                "messageId": "msg-root-1",
                "taskId": "task-root-1",
                "parts": [{"text": "hello from message"}],
                "role": "ROLE_AGENT",
                "metadata": {
                    "shared": {
                        "stream": {
                            "eventId": "evt-root-1",
                            "source": "assistant_text",
                        }
                    }
                },
            }
        }
    )

    assert chunk is not None
    assert chunk["event_id"] == "evt-root-1"
    assert chunk["message_id"] == "msg-root-1"
    assert chunk["block_type"] == "text"
    assert chunk["op"] == "replace"
    assert chunk["content"] == "hello from message"
    assert chunk["source"] == "assistant_text"


def test_extract_stream_chunk_inferrs_status_message_payloads_without_explicit_block_contract():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "statusUpdate": {
                "status": {
                    "state": "TASK_STATE_WORKING",
                    "message": {
                        "messageId": "msg-status-1",
                        "taskId": "task-status-1",
                        "parts": [{"text": "hello from status message"}],
                        "role": "ROLE_AGENT",
                    },
                },
                "metadata": {
                    "shared": {
                        "stream": {
                            "eventId": "evt-status-1",
                            "source": "assistant_text",
                        }
                    }
                },
            }
        }
    )

    assert chunk is not None
    assert chunk["event_id"] == "evt-status-1"
    assert chunk["message_id"] == "msg-status-1"
    assert chunk["artifact_id"] == "msg-status-1:text"
    assert chunk["block_type"] == "text"
    assert chunk["op"] == "replace"
    assert chunk["content"] == "hello from status message"
    assert chunk["source"] == "assistant_text"


def test_extract_stream_chunk_inferrs_artifact_text_payloads_without_explicit_block_contract():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "artifactUpdate": {
                "taskId": "task-artifact-1",
                "append": True,
                "lastChunk": False,
                "artifact": {
                    "artifactId": "task-artifact-1:stream:text",
                    "parts": [{"text": "hello from artifact"}],
                },
                "metadata": {
                    "shared": {
                        "stream": {
                            "eventId": "stream:4",
                            "seq": 4,
                        }
                    }
                },
            }
        }
    )

    assert chunk is not None
    assert chunk["event_id"] == "stream:4"
    assert chunk["seq"] == 4
    assert chunk["message_id"] == "task:task-artifact-1"
    assert chunk["artifact_id"] == "task-artifact-1:stream:text"
    assert chunk["block_id"] == "task:task-artifact-1:primary_text"
    assert chunk["block_type"] == "text"
    assert chunk["op"] == "append"
    assert chunk["append"] is True
    assert chunk["content"] == "hello from artifact"
    assert chunk["is_finished"] is False


def test_ensure_outbound_stream_contract_adds_nested_shared_stream_metadata():
    payload = {
        "message": {
            "messageId": "msg-root-2",
            "parts": [{"text": "render me"}],
            "role": "ROLE_AGENT",
        }
    }

    a2a_invoke_service._ensure_outbound_stream_contract(
        payload,
        event_sequence=4,
    )

    shared_stream = payload["message"]["metadata"]["shared"]["stream"]
    assert shared_stream["seq"] == 4
    assert shared_stream["eventId"] == "msg-root-2:4"
    assert shared_stream["blockType"] == "text"
    assert shared_stream["op"] == "replace"
    assert payload["message"]["parts"] == [{"text": "render me"}]
    assert payload["message"]["role"] == "ROLE_AGENT"
    assert payload["message"]["messageId"] == "msg-root-2"
    assert payload["hub"]["version"] == "v1"
    assert payload["hub"]["eventKind"] == "message"
    assert payload["hub"]["streamBlock"]["messageId"] == "msg-root-2"
    assert payload["hub"]["streamBlock"]["blockType"] == "text"
    assert payload["hub"]["streamBlock"]["op"] == "replace"


def test_ensure_outbound_stream_contract_adds_shared_stream_metadata_for_status_message():
    payload = {
        "statusUpdate": {
            "status": {
                "state": "TASK_STATE_WORKING",
                "message": {
                    "messageId": "msg-status-2",
                    "parts": [{"text": "render status message"}],
                    "role": "ROLE_AGENT",
                },
            }
        }
    }

    a2a_invoke_service._ensure_outbound_stream_contract(
        payload,
        event_sequence=5,
    )

    shared_stream = payload["statusUpdate"]["metadata"]["shared"]["stream"]
    assert shared_stream["seq"] == 5
    assert shared_stream["messageId"] == "msg-status-2"
    assert shared_stream["eventId"] == "msg-status-2:5"
    assert shared_stream["blockType"] == "text"
    assert shared_stream["op"] == "replace"
    assert payload["statusUpdate"]["status"]["message"]["parts"] == [
        {"text": "render status message"}
    ]
    assert payload["hub"]["version"] == "v1"
    assert payload["hub"]["eventKind"] == "status-update"
    assert payload["hub"]["streamBlock"]["messageId"] == "msg-status-2"
    assert payload["hub"]["runtimeStatus"]["state"] == "working"
    assert payload["hub"]["runtimeStatus"]["isFinal"] is False


def test_ensure_outbound_stream_contract_exposes_fallback_message_identity_in_hub():
    payload = {
        "artifactUpdate": {
            "taskId": "task-fallback-1",
            "append": True,
            "artifact": {
                "artifactId": "task-fallback-1:stream:text",
                "parts": [{"text": "hello"}],
            },
        }
    }

    a2a_invoke_service._ensure_outbound_stream_contract(
        payload,
        event_sequence=6,
    )

    assert payload["hub"]["streamBlock"]["messageId"] == "task:task-fallback-1"
    assert payload["hub"]["streamBlock"]["messageIdSource"] == "task_fallback"
    assert payload["hub"]["streamBlock"]["eventIdSource"] == "fallback_seq"


def test_serialize_stream_event_keeps_canonical_message_payload_before_validation(
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
                "message": {
                    "messageId": "msg-serialize-1",
                    "role": "ROLE_AGENT",
                    "parts": [{"text": "hello"}],
                }
            }
        ),
        validate_message=_validate,
    )

    assert serialized["message"]["messageId"] == "msg-serialize-1"
    assert serialized["message"]["parts"] == [{"text": "hello"}]
    assert serialized["message"]["role"] == "ROLE_AGENT"
    assert seen_payloads[0]["message"]["messageId"] == "msg-serialize-1"


def test_extract_stream_chunk_rejects_unsupported_explicit_block_type():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {
                    "artifactId": "task-generic:stream",
                    "parts": [{"text": "hello generic"}],
                },
                "metadata": {
                    "shared": {
                        "stream": {
                            "blockType": "custom_phase",
                            "op": "append",
                        }
                    }
                },
            }
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
            "statusUpdate": {
                "status": {"state": "TASK_STATE_COMPLETED"},
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
                "statusUpdate": {
                    "status": {"state": "TASK_STATE_COMPLETED"},
                    "metadata": {
                        "shared": {
                            "usage": {
                                "input_tokens": 66,
                                "output_tokens": 11,
                                "total_tokens": 77,
                                "cost": 0.0077,
                            },
                        },
                    },
                }
            }

    usage = a2a_invoke_service.extract_usage_hints_from_invoke_result(
        {
            "statusUpdate": {
                "status": {"state": "TASK_STATE_COMPLETED"},
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


def test_extract_usage_hints_from_serialized_event_ignores_legacy_root_metadata():
    usage = a2a_invoke_service.extract_usage_hints_from_serialized_event(
        {
            "statusUpdate": {
                "status": {"state": "TASK_STATE_COMPLETED"},
                "metadata": {
                    "usage": {
                        "input_tokens": 9,
                        "output_tokens": 3,
                        "total_tokens": 12,
                    },
                },
            }
        }
    )
    assert usage == {}


def test_extract_binding_hints_from_nested_status_message_metadata():
    context_id, metadata = (
        a2a_invoke_service.extract_binding_hints_from_serialized_event(
            {
                "statusUpdate": {
                    "status": {
                        "state": "TASK_STATE_WORKING",
                        "message": {
                            "messageId": "msg-status-binding",
                            "parts": [{"text": "hello"}],
                            "metadata": {
                                "contextId": "ctx-status-binding",
                                "shared": {
                                    "session": {
                                        "id": "sess-status-binding",
                                        "provider": "status-provider",
                                    }
                                },
                            },
                        },
                    }
                }
            }
        )
    )
    assert context_id == "ctx-status-binding"
    assert metadata["shared"]["session"] == {
        "id": "sess-status-binding",
        "provider": "status-provider",
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
