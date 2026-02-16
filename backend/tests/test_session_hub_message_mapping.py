from __future__ import annotations

import json
from datetime import datetime, timezone

from app.services.session_hub import _map_opencode_message


def test_map_opencode_message_uses_minimal_blocks_without_raw_metadata() -> None:
    item = {
        "kind": "message",
        "messageId": "msg-1",
        "metadata": {
            "opencode": {
                "raw": {
                    "info": {
                        "id": "msg-1",
                        "role": "assistant",
                        "time": {"created": 1771222605384},
                    },
                    "parts": [
                        {"type": "reasoning", "text": "thinking"},
                        {"type": "tool", "callID": "call-1", "tool": "bash"},
                        {"type": "text", "text": "final answer"},
                    ],
                }
            }
        },
    }

    mapped = _map_opencode_message(item, 0)

    assert mapped["id"] == "msg-1"
    assert mapped["role"] == "agent"
    assert mapped["content"] == "final answer"
    assert mapped["created_at"] == datetime.fromtimestamp(
        1771222605384 / 1000.0, tz=timezone.utc
    )
    assert "raw" not in mapped["metadata"]
    assert mapped["metadata"]["message_blocks"] == [
        {
            "id": "history-block-1",
            "type": "reasoning",
            "content": "thinking",
            "is_finished": True,
        },
        {
            "id": "history-block-2",
            "type": "tool_call",
            "content": '{"call_id": "call-1", "tool": "bash"}',
            "is_finished": True,
        },
        {
            "id": "history-block-3",
            "type": "text",
            "content": "final answer",
            "is_finished": True,
        },
    ]


def test_map_opencode_message_parses_json_content_envelope() -> None:
    item = {
        "id": "msg-2",
        "role": "assistant",
        "content": json.dumps(
            {
                "kind": "message",
                "parts": [
                    {"kind": "reasoning", "text": "calc"},
                    {"kind": "text", "text": "done"},
                ],
            },
            ensure_ascii=False,
        ),
    }

    mapped = _map_opencode_message(item, 1)

    assert mapped["id"] == "msg-2"
    assert mapped["role"] == "agent"
    assert mapped["content"] == "done"
    assert mapped["metadata"]["message_blocks"] == [
        {
            "id": "history-block-1",
            "type": "reasoning",
            "content": "calc",
            "is_finished": True,
        },
        {
            "id": "history-block-2",
            "type": "text",
            "content": "done",
            "is_finished": True,
        },
    ]


def test_map_opencode_message_keeps_plain_text_content() -> None:
    item = {
        "id": "msg-3",
        "role": "assistant",
        "content": "plain response",
    }

    mapped = _map_opencode_message(item, 2)

    assert mapped["id"] == "msg-3"
    assert mapped["role"] == "agent"
    assert mapped["content"] == "plain response"
    assert mapped["metadata"] == {}
