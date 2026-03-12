import pytest
from app.services.a2a_invoke_service import a2a_invoke_service

def test_extract_stream_chunk_falls_back_to_text_if_parts_exist():
    chunk = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        {
            "kind": "artifact-update",
            "artifact": {
                "parts": [{"kind": "text", "text": "hello"}],
                "metadata": {}
            },
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
                "metadata": {
                    "block_type": "reasoning"
                }
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
                "metadata": {
                    "opencode": {
                        "block_type": "reasoning"
                    }
                }
            },
        }
    )
    assert chunk is not None
    assert chunk["block_type"] == "reasoning"
    assert chunk["content"] == "opencode-thinking"

