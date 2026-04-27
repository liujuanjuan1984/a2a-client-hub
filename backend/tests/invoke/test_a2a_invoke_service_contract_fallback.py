from app.features.invoke.service import a2a_invoke_service


def test_extract_stream_chunk_falls_back_to_text_if_parts_exist():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {"parts": [{"text": "hello"}], "metadata": {}},
            }
        }
    )
    assert chunk is not None
    assert chunk["block_type"] == "text"
    assert chunk["content"] == "hello"


def test_extract_stream_chunk_prefers_standard_metadata_block_type():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {
                    "parts": [{"text": "thinking"}],
                    "metadata": {"block_type": "reasoning"},
                }
            }
        }
    )
    assert chunk is not None
    assert chunk["block_type"] == "reasoning"
    assert chunk["content"] == "thinking"


def test_extract_stream_chunk_accepts_type_and_content_parts_shape():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {
                    "parts": [{"type": "text", "content": "hello"}],
                    "metadata": {},
                }
            }
        }
    )
    assert chunk is not None
    assert chunk["block_type"] == "text"
    assert chunk["content"] == "hello"


def test_extract_stream_chunk_rejects_kindless_artifact_updates():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "artifact": {
                "parts": [{"text": "thinking"}],
                "metadata": {
                    "shared": {
                        "stream": {
                            "block_type": "reasoning",
                            "messageId": "msg-kindless",
                            "eventId": "evt-kindless",
                            "sequence": 4,
                        }
                    }
                },
            }
        }
    )
    assert chunk is None


def test_extract_stream_chunk_rejects_root_metadata_hints_outside_wrapper():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "metadata": {
                "block_type": "text",
                "messageId": "msg-root",
                "eventId": "evt-root",
            },
            "artifactUpdate": {
                "artifact": {"parts": [{"text": "hello"}], "metadata": {}},
            },
        }
    )
    assert chunk is not None
    assert chunk["block_type"] == "text"
    assert chunk["message_id"] is None
    assert chunk["event_id"] is None


def test_extract_stream_chunk_prefers_shared_stream_block_type_over_text_part_kind():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {
                    "parts": [{"text": '{"tool":"bash"}'}],
                    "metadata": {
                        "shared": {
                            "stream": {
                                "block_type": "tool_call",
                                "source": "tool_part_update",
                                "messageId": "msg-shared",
                                "eventId": "evt-shared",
                                "sequence": 7,
                            }
                        }
                    },
                }
            }
        }
    )
    assert chunk is not None
    assert chunk["block_type"] == "tool_call"
    assert chunk["message_id"] == "msg-shared"
    assert chunk["event_id"] == "evt-shared"
    assert chunk["seq"] == 7
    assert chunk["source"] == "tool_part_update"


def test_extract_stream_chunk_reads_tool_call_content_from_data_parts():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {
                    "parts": [
                        {
                            "data": {
                                "call_id": "call-1",
                                "tool": "read",
                                "status": "pending",
                                "input": {},
                            }
                        }
                    ],
                    "metadata": {
                        "shared": {
                            "stream": {
                                "block_type": "tool_call",
                                "source": "tool_part_update",
                                "messageId": "msg-data",
                                "eventId": "evt-data",
                                "sequence": 8,
                            }
                        }
                    },
                }
            }
        }
    )
    assert chunk is not None
    assert chunk["block_type"] == "tool_call"
    assert chunk["content"] == (
        '{"call_id":"call-1","input":{},"status":"pending","tool":"read"}'
    )
    assert chunk["message_id"] == "msg-data"
    assert chunk["event_id"] == "evt-data"
    assert chunk["seq"] == 8
    assert chunk["tool_call"] == {
        "name": "read",
        "status": "running",
        "callId": "call-1",
        "arguments": {},
        "result": None,
        "error": None,
    }


def test_extract_stream_chunk_uses_message_lane_identity_when_artifact_id_is_shared():
    reasoning = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {
                    "artifactId": "task-shared:stream",
                    "parts": [{"text": "thinking"}],
                    "metadata": {
                        "shared": {
                            "stream": {
                                "block_type": "reasoning",
                                "messageId": "msg-shared-lanes",
                            }
                        }
                    },
                }
            }
        }
    )
    text = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "artifactUpdate": {
                "artifact": {
                    "artifactId": "task-shared:stream",
                    "parts": [{"text": "final answer"}],
                    "metadata": {
                        "shared": {
                            "stream": {
                                "block_type": "text",
                                "messageId": "msg-shared-lanes",
                            }
                        }
                    },
                }
            }
        }
    )

    assert reasoning is not None
    assert text is not None
    assert reasoning["artifact_id"] == "task-shared:stream"
    assert text["artifact_id"] == "task-shared:stream"
    assert reasoning["block_id"] == "msg-shared-lanes:reasoning"
    assert text["block_id"] == "msg-shared-lanes:primary_text"


def test_ensure_outbound_stream_contract_ignores_kindless_artifact_updates():
    payload = {
        "artifact": {
            "parts": [{"text": "draft"}],
            "metadata": {
                "shared": {
                    "stream": {
                        "block_type": "text",
                        "messageId": "msg-kindless-outbound",
                        "eventId": "evt-kindless-outbound",
                    }
                }
            },
        }
    }

    a2a_invoke_service._ensure_outbound_stream_contract(payload, event_sequence=3)

    assert "artifactUpdate" not in payload
    assert "seq" not in payload
