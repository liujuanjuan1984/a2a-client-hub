from app.services.a2a_invoke_service import a2a_invoke_service


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


def test_extract_stream_chunk_respects_opencode_block_type_as_fallback():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "kind": "artifact-update",
            "artifact": {
                "parts": [{"kind": "text", "text": "opencode-thinking"}],
                "metadata": {"opencode": {"block_type": "reasoning"}},
            },
        }
    )
    assert chunk is not None
    assert chunk["block_type"] == "reasoning"
    assert chunk["content"] == "opencode-thinking"


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


def test_extract_stream_chunk_reads_root_opencode_metadata_hints():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "kind": "artifact-update",
            "metadata": {
                "opencode": {
                    "block_type": "text",
                    "message_id": "msg-root",
                    "event_id": "evt-root",
                }
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
