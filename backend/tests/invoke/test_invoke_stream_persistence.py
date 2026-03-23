from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.features.invoke.service import (
    StreamFinishReason,
    StreamOutcome,
    a2a_invoke_service,
)
from app.features.invoke.stream_persistence import (
    build_stream_metadata_from_outcome,
    ensure_local_message_headers,
    flush_stream_buffer,
    persist_local_outcome,
    persist_stream_block_update,
    resolve_invoke_idempotency_key,
    rewrite_stream_event_contract,
)
from app.features.sessions.service import session_hub_service
from app.utils.idempotency_key import IDEMPOTENCY_KEY_MAX_LENGTH
from app.utils.timezone_util import utc_now
from tests.support.utils import create_user


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


def test_rewrite_stream_event_contract_copies_canonical_block_fields() -> None:
    payload = {
        "kind": "artifact-update",
        "artifact": {"metadata": {}, "parts": [{"kind": "text", "text": "draft"}]},
    }

    rewrite_stream_event_contract(
        payload,
        local_message_id="msg-local-1",
        event_id="evt-local-1",
        seq=7,
        stream_block={
            "block_id": "block-text-main",
            "lane_id": "primary_text",
            "op": "replace",
            "base_seq": 6,
        },
    )

    assert payload["message_id"] == "msg-local-1"
    assert payload["event_id"] == "evt-local-1"
    assert payload["seq"] == 7
    assert payload["block_id"] == "block-text-main"
    assert payload["lane_id"] == "primary_text"
    assert payload["op"] == "replace"
    assert payload["base_seq"] == 6
    artifact = payload["artifact"]
    assert artifact["message_id"] == "msg-local-1"
    assert artifact["event_id"] == "evt-local-1"
    assert artifact["seq"] == 7
    assert artifact["metadata"]["block_id"] == "block-text-main"
    assert artifact["metadata"]["lane_id"] == "primary_text"
    assert artifact["metadata"]["op"] == "replace"
    assert artifact["metadata"]["base_seq"] == 6


class _SessionContext:
    def __init__(self, session: Any) -> None:
        self._session = session

    async def __aenter__(self) -> Any:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("include_kind", [True, False])
async def test_persist_local_outcome_keeps_typed_blocks_after_stream_completion(
    async_db_session,
    include_kind: bool,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Typed Stream Completion",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    state = _FakeState(
        local_session_id=thread.id,
        local_source="manual",
        context_id="ctx-stream-typed",
        metadata={},
        stream_identity={},
        stream_usage={},
        next_event_seq=1,
    )

    def _session_factory() -> _SessionContext:
        return _SessionContext(async_db_session)

    async def _commit(_db) -> None:  # noqa: ANN001
        await async_db_session.flush()

    async def _ensure_headers_adapter(**kwargs) -> None:  # noqa: ANN001
        await ensure_local_message_headers(
            **kwargs,
            session_factory=_session_factory,
            commit_fn=_commit,
            session_hub=session_hub_service,
        )

    reasoning_event = {
        "artifact": {
            "parts": [{"kind": "text", "text": "thinking"}],
            "metadata": {
                "shared": {
                    "stream": {
                        "block_type": "reasoning",
                        "message_id": "msg-stream-1",
                        "event_id": "evt-reasoning-1",
                        "sequence": 1,
                    }
                }
            },
        },
    }
    tool_event = {
        "artifact": {
            "parts": [
                {
                    "kind": "data",
                    "data": {
                        "call_id": "call-1",
                        "tool": "bash",
                        "status": "completed",
                        "output": "pwd",
                    },
                }
            ],
            "metadata": {
                "shared": {
                    "stream": {
                        "block_type": "tool_call",
                        "message_id": "msg-stream-1",
                        "event_id": "evt-tool-1",
                        "sequence": 2,
                    }
                }
            },
        },
    }
    text_event = {
        "artifact": {
            "parts": [{"kind": "text", "text": "draft"}],
            "metadata": {
                "shared": {
                    "stream": {
                        "block_type": "text",
                        "message_id": "msg-stream-1",
                        "event_id": "evt-text-1",
                        "sequence": 3,
                    }
                }
            },
        },
    }
    snapshot_event = {
        "append": False,
        "artifact": {
            "parts": [{"kind": "text", "text": "final answer"}],
            "metadata": {
                "shared": {
                    "stream": {
                        "block_type": "text",
                        "source": "final_snapshot",
                        "message_id": "msg-stream-1",
                        "event_id": "evt-text-2",
                        "sequence": 4,
                    }
                }
            },
            "lastChunk": True,
        },
    }

    if include_kind:
        for event_payload in (
            reasoning_event,
            tool_event,
            text_event,
            snapshot_event,
        ):
            event_payload["kind"] = "artifact-update"

    for event_payload in (
        reasoning_event,
        tool_event,
        text_event,
        snapshot_event,
    ):
        await persist_stream_block_update(
            state=state,
            event_payload=event_payload,
            user_id=user.id,
            agent_id=uuid4(),
            agent_source="personal",
            query="hello",
            transport="http_sse",
            stream_enabled=True,
            stream_service=a2a_invoke_service,
            session_factory=_session_factory,
            commit_fn=_commit,
            session_hub=session_hub_service,
            ensure_headers_fn=_ensure_headers_adapter,
        )

    await flush_stream_buffer(
        state=state,
        user_id=user.id,
        session_factory=_session_factory,
        commit_fn=_commit,
        session_hub=session_hub_service,
    )
    await persist_local_outcome(
        state=state,
        outcome=StreamOutcome(
            success=True,
            finish_reason=StreamFinishReason.SUCCESS,
            final_text="final answer",
            error_message=None,
            error_code=None,
            elapsed_seconds=1.0,
            idle_seconds=0.1,
            terminal_event_seen=True,
        ),
        user_id=user.id,
        agent_id=uuid4(),
        agent_source="personal",
        query="hello",
        transport="http_sse",
        stream_enabled=True,
        session_factory=_session_factory,
        commit_fn=_commit,
        session_hub=session_hub_service,
        ensure_headers_fn=_ensure_headers_adapter,
    )

    agent_message = await async_db_session.scalar(
        select(AgentMessage).where(
            AgentMessage.conversation_id == thread.id,
            AgentMessage.sender == "agent",
        )
    )
    assert agent_message is not None

    persisted_blocks = list(
        (
            await async_db_session.scalars(
                select(AgentMessageBlock)
                .where(AgentMessageBlock.message_id == agent_message.id)
                .order_by(AgentMessageBlock.block_seq.asc())
            )
        ).all()
    )
    assert [block.block_type for block in persisted_blocks] == [
        "reasoning",
        "tool_call",
        "text",
    ]
    assert persisted_blocks[2].content == "final answer"

    items, _, _ = await session_hub_service.list_messages(
        async_db_session,
        user_id=user.id,
        conversation_id=str(thread.id),
        before=None,
        limit=8,
    )
    agent_item = next(item for item in items if item["role"] == "agent")
    assert [block["type"] for block in agent_item["blocks"]] == [
        "reasoning",
        "tool_call",
        "text",
    ]
    assert agent_item["content"] == "final answer"
