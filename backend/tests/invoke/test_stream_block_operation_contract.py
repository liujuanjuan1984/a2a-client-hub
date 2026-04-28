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
        "eventId": parsed.get("event_id"),
        "seq": parsed.get("seq"),
        "messageId": parsed.get("message_id"),
        "artifactId": parsed.get("artifact_id"),
        "blockId": parsed.get("block_id"),
        "laneId": parsed.get("lane_id"),
        "blockType": parsed.get("block_type"),
        "op": parsed.get("op"),
        "content": parsed.get("content"),
        "baseSeq": parsed.get("base_seq"),
        "isFinished": parsed.get("is_finished"),
        "source": parsed.get("source"),
    }


def test_extract_stream_chunk_matches_shared_block_operation_contract_cases() -> None:
    for case in _CANONICAL_CASES:
        parsed = extract_stream_chunk_from_serialized_event(case["payload"])
        assert _normalize_stream_chunk(parsed) == case["expected"]
