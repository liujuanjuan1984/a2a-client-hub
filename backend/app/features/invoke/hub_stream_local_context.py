"""Internal local stream identity overlay for Hub stream normalization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_LOCAL_STREAM_CONTEXT_KEY = "__hub_local_stream"


def attach_local_stream_context(
    payload: dict[str, Any],
    *,
    local_message_id: str,
    event_id: str,
    seq: int | None,
    stream_block: dict[str, Any] | None = None,
) -> None:
    context: dict[str, Any] = {
        "message_id": local_message_id,
        "event_id": event_id,
        "seq": seq if isinstance(seq, int) and seq > 0 else None,
    }
    if isinstance(stream_block, Mapping):
        for source_name in ("block_id", "lane_id", "op", "base_seq"):
            value = stream_block.get(source_name)
            if value is not None:
                context[source_name] = value
    payload[_LOCAL_STREAM_CONTEXT_KEY] = context


def consume_local_stream_context(payload: dict[str, Any]) -> dict[str, Any] | None:
    candidate = payload.pop(_LOCAL_STREAM_CONTEXT_KEY, None)
    if not isinstance(candidate, Mapping):
        return None
    resolved = dict(candidate)
    message_id = resolved.get("message_id")
    event_id = resolved.get("event_id")
    if not isinstance(message_id, str) or not message_id.strip():
        return None
    if not isinstance(event_id, str) or not event_id.strip():
        return None
    return resolved
