from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.services.a2a_invoke_service import StreamFinishReason, StreamOutcome
from app.services.invoke_stream_persistence import (
    build_stream_metadata_from_outcome,
    resolve_invoke_idempotency_key,
)
from app.utils.idempotency_key import IDEMPOTENCY_KEY_MAX_LENGTH


@dataclass
class _FakeState:
    local_session_id: UUID | None = None
    local_source: str | None = None
    context_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    stream_identity: dict[str, Any] = field(default_factory=dict)
    stream_usage: dict[str, Any] = field(default_factory=dict)
    user_message_id: str | None = None
    agent_message_id: str | None = None
    message_refs: dict[str, UUID] | None = None
    persisted_response_content: str | None = None
    persisted_success: bool | None = None
    persisted_error_code: str | None = None
    persisted_finish_reason: str | None = None
    idempotency_key: str | None = None
    next_event_seq: int = 1
    persisted_block_count: int = 0
    chunk_buffer: list[dict[str, Any]] = field(default_factory=list)
    current_block_type: str | None = None


def test_resolve_invoke_idempotency_key_hashes_overlong_value() -> None:
    state = _FakeState(user_message_id="m" * 512)

    resolved = resolve_invoke_idempotency_key(state=state, transport="scheduled")

    assert resolved is not None
    assert len(resolved) == IDEMPOTENCY_KEY_MAX_LENGTH
    assert ":h:" in resolved


def test_build_stream_metadata_from_outcome_keeps_identity_and_usage() -> None:
    state = _FakeState(
        stream_identity={"message_blocks": 2, "upstream_task_id": "task-1"},
        stream_usage={"input_tokens": 10, "output_tokens": 5},
    )

    metadata = build_stream_metadata_from_outcome(
        state=state,
        outcome=StreamOutcome(
            success=False,
            finish_reason=StreamFinishReason.TIMEOUT_TOTAL,
            final_text="partial",
            error_message="timeout",
            error_code="timeout",
            elapsed_seconds=60.0,
            idle_seconds=0.1,
            terminal_event_seen=False,
        ),
        response_metadata={"existing": True},
    )

    assert metadata == {
        "existing": True,
        "message_blocks": 2,
        "upstream_task_id": "task-1",
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "stream": {
            "schema_version": 1,
            "finish_reason": "timeout_total",
            "error": {"message": "timeout", "error_code": "timeout"},
        },
    }
