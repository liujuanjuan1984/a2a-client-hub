import json
from pathlib import Path

from app.features.invoke.stream_payloads import (
    extract_stream_chunk_from_serialized_event,
)

_CANONICAL_CASES = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "docs/contracts/stream-block-operation-canonical-cases.json"
    ).read_text(encoding="utf-8")
)


def _normalize_stream_chunk(
    parsed: dict[str, object] | None,
) -> dict[str, object] | None:
    if parsed is None:
        return None
    return {
        "event_id": parsed.get("event_id"),
        "seq": parsed.get("seq"),
        "message_id": parsed.get("message_id"),
        "artifact_id": parsed.get("artifact_id"),
        "block_id": parsed.get("block_id"),
        "lane_id": parsed.get("lane_id"),
        "block_type": parsed.get("block_type"),
        "op": parsed.get("op"),
        "content": parsed.get("content"),
        "base_seq": parsed.get("base_seq"),
        "is_finished": parsed.get("is_finished"),
        "source": parsed.get("source"),
    }


def test_extract_stream_chunk_matches_shared_block_operation_contract_cases() -> None:
    for case in _CANONICAL_CASES:
        parsed = extract_stream_chunk_from_serialized_event(case["payload"])
        assert _normalize_stream_chunk(parsed) == case["expected"]
