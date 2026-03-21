from app.features.invoke.service import a2a_invoke_service


def test_extract_stream_chunk_falls_back_to_text_if_parts_exist():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "kind": "artifact-update",
            "artifact": {"parts": [{"kind": "text", "text": "hello"}], "metadata": {}},
        }
    )
    assert chunk is not None
    assert chunk["block_type"] == "text"
    assert chunk["content"] == "hello"


def test_extract_stream_chunk_prefers_standard_metadata_block_type():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "kind": "artifact-update",
            "artifact": {
                "parts": [{"kind": "text", "text": "thinking"}],
                "metadata": {"block_type": "reasoning"},
            },
        }
    )
    assert chunk is not None
    assert chunk["block_type"] == "reasoning"
    assert chunk["content"] == "thinking"


def test_extract_stream_chunk_accepts_type_and_content_parts_shape():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "kind": "artifact-update",
            "artifact": {
                "parts": [{"type": "text", "content": "hello"}],
                "metadata": {},
            },
        }
    )
    assert chunk is not None
    assert chunk["block_type"] == "text"
    assert chunk["content"] == "hello"


def test_extract_stream_chunk_reads_root_metadata_hints():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "kind": "artifact-update",
            "metadata": {
                "block_type": "text",
                "message_id": "msg-root",
                "event_id": "evt-root",
            },
            "artifact": {
                "parts": [{"kind": "text", "text": "hello"}],
                "metadata": {},
            },
        }
    )
    assert chunk is not None
    assert chunk["block_type"] == "text"
    assert chunk["message_id"] == "msg-root"
    assert chunk["event_id"] == "evt-root"


def test_extract_stream_chunk_prefers_shared_stream_block_type_over_text_part_kind():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "kind": "artifact-update",
            "artifact": {
                "parts": [{"kind": "text", "text": '{"tool":"bash"}'}],
                "metadata": {
                    "shared": {
                        "stream": {
                            "block_type": "tool_call",
                            "source": "tool_part_update",
                            "message_id": "msg-shared",
                            "event_id": "evt-shared",
                            "sequence": 7,
                        }
                    }
                },
            },
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
            "kind": "artifact-update",
            "artifact": {
                "parts": [
                    {
                        "kind": "data",
                        "data": {
                            "call_id": "call-1",
                            "tool": "read",
                            "status": "pending",
                            "input": {},
                        },
                    }
                ],
                "metadata": {
                    "shared": {
                        "stream": {
                            "block_type": "tool_call",
                            "source": "tool_part_update",
                            "message_id": "msg-data",
                            "event_id": "evt-data",
                            "sequence": 8,
                        }
                    }
                },
            },
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
