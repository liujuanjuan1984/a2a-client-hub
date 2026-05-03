from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.db.models.conversation_upstream_task import ConversationUpstreamTask
from app.features.invoke.service_types import StreamFinishReason, StreamOutcome
from app.features.invoke.stream_persistence import (
    InvokePersistenceRequest,
    attach_local_stream_contract_context,
    build_stream_metadata_from_outcome,
    ensure_local_message_headers,
    flush_stream_buffer,
    persist_local_outcome,
    persist_stream_block_update,
    resolve_invoke_idempotency_key,
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


def test_attach_local_stream_contract_context_stores_internal_overlay() -> None:
    payload = {
        "artifactUpdate": {
            "artifact": {"metadata": {}, "parts": [{"text": "draft"}]},
        }
    }

    attach_local_stream_contract_context(
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

    assert payload["artifactUpdate"] == {
        "artifact": {"metadata": {}, "parts": [{"text": "draft"}]},
    }
    assert payload["__hub_local_stream"] == {
        "message_id": "msg-local-1",
        "event_id": "evt-local-1",
        "seq": 7,
        "block_id": "block-text-main",
        "lane_id": "primary_text",
        "op": "replace",
        "base_seq": 6,
    }


class _SessionContext:
    def __init__(self, session: Any) -> None:
        self._session = session

    async def __aenter__(self) -> Any:
        return self._session

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        return None


def _build_request(
    *,
    user_id: UUID,
    agent_id: UUID | None = None,
    agent_source: Literal["personal", "shared"] = "personal",
    query: str = "hello",
    transport: Literal["http_json", "http_sse", "scheduled", "ws"] = "http_sse",
    stream_enabled: bool = True,
    user_sender: Literal["user", "automation"] = "user",
    extra_persisted_metadata: dict[str, Any] | None = None,
) -> InvokePersistenceRequest:
    return InvokePersistenceRequest(
        user_id=user_id,
        agent_id=agent_id or uuid4(),
        agent_source=agent_source,
        query=query,
        transport=transport,
        stream_enabled=stream_enabled,
        user_sender=user_sender,
        extra_persisted_metadata=dict(extra_persisted_metadata or {}),
    )


@pytest.mark.asyncio
async def test_persist_local_outcome_keeps_typed_blocks_after_stream_completion(
    async_db_session,
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

    async def _commit(_db) -> None:
        await async_db_session.flush()

    async def _ensure_headers_adapter(**kwargs) -> None:
        await ensure_local_message_headers(
            **kwargs,
            session_factory=_session_factory,
            commit_fn=_commit,
            session_hub=session_hub_service,
        )

    reasoning_event = {
        "artifactUpdate": {
            "op": "append",
            "artifact": {
                "parts": [{"text": "thinking"}],
                "metadata": {
                    "shared": {
                        "stream": {
                            "blockType": "reasoning",
                            "messageId": "msg-stream-1",
                            "eventId": "evt-reasoning-1",
                            "seq": 1,
                        }
                    }
                },
            },
        }
    }
    tool_event = {
        "artifactUpdate": {
            "op": "append",
            "artifact": {
                "parts": [
                    {
                        "data": {
                            "call_id": "call-1",
                            "tool": "bash",
                            "status": "completed",
                            "output": "pwd",
                        }
                    }
                ],
                "metadata": {
                    "shared": {
                        "stream": {
                            "blockType": "tool_call",
                            "messageId": "msg-stream-1",
                            "eventId": "evt-tool-1",
                            "seq": 2,
                        }
                    }
                },
            },
        }
    }
    text_event = {
        "artifactUpdate": {
            "op": "append",
            "artifact": {
                "parts": [{"text": "draft"}],
                "metadata": {
                    "shared": {
                        "stream": {
                            "blockType": "text",
                            "messageId": "msg-stream-1",
                            "eventId": "evt-text-1",
                            "seq": 3,
                        }
                    }
                },
            },
        }
    }
    snapshot_event = {
        "artifactUpdate": {
            "op": "replace",
            "artifact": {
                "parts": [{"text": "final answer"}],
                "metadata": {
                    "shared": {
                        "stream": {
                            "blockType": "text",
                            "source": "final_snapshot",
                            "messageId": "msg-stream-1",
                            "eventId": "evt-text-2",
                            "seq": 4,
                        }
                    }
                },
                "lastChunk": True,
            },
        }
    }

    for event_payload in (
        reasoning_event,
        tool_event,
        text_event,
        snapshot_event,
    ):
        await persist_stream_block_update(
            state=state,
            event_payload=event_payload,
            request=_build_request(user_id=user.id),
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
        request=_build_request(user_id=user.id),
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


@pytest.mark.asyncio
async def test_persist_local_outcome_records_upstream_task_binding(
    async_db_session,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent_id = uuid4()
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent_id,
        agent_source="personal",
        title="Task Binding Stream",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    state = _FakeState(
        local_session_id=thread.id,
        local_source="manual",
        context_id="ctx-task-binding",
        metadata={},
        stream_identity={"upstream_task_id": "task-stream-1"},
        stream_usage={},
    )

    def _session_factory() -> _SessionContext:
        return _SessionContext(async_db_session)

    async def _commit(_db) -> None:
        await async_db_session.flush()

    async def _ensure_headers_adapter(**kwargs) -> None:
        await ensure_local_message_headers(
            **kwargs,
            session_factory=_session_factory,
            commit_fn=_commit,
            session_hub=session_hub_service,
        )

    await persist_local_outcome(
        state=state,
        outcome=StreamOutcome(
            success=True,
            finish_reason=StreamFinishReason.SUCCESS,
            final_text="done",
            error_message=None,
            error_code=None,
            elapsed_seconds=1.0,
            idle_seconds=0.1,
            terminal_event_seen=True,
        ),
        request=_build_request(user_id=user.id, agent_id=agent_id),
        session_factory=_session_factory,
        commit_fn=_commit,
        session_hub=session_hub_service,
        ensure_headers_fn=_ensure_headers_adapter,
    )

    binding = await async_db_session.scalar(
        select(ConversationUpstreamTask).where(
            ConversationUpstreamTask.conversation_id == thread.id,
            ConversationUpstreamTask.upstream_task_id == "task-stream-1",
        )
    )
    assert binding is not None
    assert binding.user_id == user.id
    assert binding.agent_id == agent_id
    assert binding.source == "final_metadata"
    assert binding.status_hint == "done"
    assert binding.latest_message_id == state.message_refs["agent_message_id"]


@pytest.mark.asyncio
async def test_persist_stream_block_update_accepts_status_message_content(
    async_db_session,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Status Message Stream",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    state = _FakeState(
        local_session_id=thread.id,
        local_source="manual",
        context_id="ctx-status-message",
        metadata={},
        stream_identity={},
        stream_usage={},
        next_event_seq=1,
    )

    def _session_factory() -> _SessionContext:
        return _SessionContext(async_db_session)

    async def _commit(_db) -> None:
        await async_db_session.flush()

    async def _ensure_headers_adapter(**kwargs) -> None:
        await ensure_local_message_headers(
            **kwargs,
            session_factory=_session_factory,
            commit_fn=_commit,
            session_hub=session_hub_service,
        )

    event_payload = {
        "statusUpdate": {
            "status": {
                "state": "TASK_STATE_WORKING",
                "message": {
                    "messageId": "msg-status-stream-1",
                    "taskId": "task-status-stream-1",
                    "parts": [{"text": "hello from status message"}],
                    "role": "ROLE_AGENT",
                },
            },
            "metadata": {
                "shared": {
                    "stream": {
                        "eventId": "evt-status-stream-1",
                        "seq": 1,
                        "source": "assistant_text",
                    }
                }
            },
        }
    }

    await persist_stream_block_update(
        state=state,
        event_payload=event_payload,
        request=_build_request(user_id=user.id),
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
    assert [block.block_type for block in persisted_blocks] == ["text"]
    assert persisted_blocks[0].content == "hello from status message"


@pytest.mark.asyncio
async def test_persist_stream_block_update_accepts_snake_case_stream_hints(
    async_db_session,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Snake Case Stream Hints",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    state = _FakeState(
        local_session_id=thread.id,
        local_source="manual",
        context_id="ctx-stream-snake",
        metadata={},
        stream_identity={},
        stream_usage={},
        next_event_seq=1,
    )

    def _session_factory() -> _SessionContext:
        return _SessionContext(async_db_session)

    async def _commit(_db) -> None:
        await async_db_session.flush()

    async def _ensure_headers_adapter(**kwargs) -> None:
        await ensure_local_message_headers(
            **kwargs,
            session_factory=_session_factory,
            commit_fn=_commit,
            session_hub=session_hub_service,
        )

    event_payload = {
        "artifactUpdate": {
            "artifact": {
                "parts": [{"text": "thinking"}],
                "metadata": {
                    "shared": {
                        "stream": {
                            "block_type": "reasoning",
                            "message_id": "msg-stream-snake-1",
                            "event_id": "evt-stream-snake-1",
                            "sequence": 1,
                            "op": "append",
                            "source": "reasoning_part_update",
                        }
                    }
                },
            }
        }
    }

    await persist_stream_block_update(
        state=state,
        event_payload=event_payload,
        request=_build_request(user_id=user.id),
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
    assert [block.block_type for block in persisted_blocks] == ["reasoning"]
    assert persisted_blocks[0].content == "thinking"


@pytest.mark.asyncio
async def test_persist_local_outcome_keeps_typed_blocks_when_upstream_reuses_artifact_id(
    async_db_session,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Shared Artifact Identity",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.flush()

    state = _FakeState(
        local_session_id=thread.id,
        local_source="manual",
        context_id="ctx-shared-artifact",
        metadata={},
        stream_identity={},
        stream_usage={},
        next_event_seq=1,
    )

    def _session_factory() -> _SessionContext:
        return _SessionContext(async_db_session)

    async def _commit(_db) -> None:
        await async_db_session.flush()

    async def _ensure_headers_adapter(**kwargs) -> None:
        await ensure_local_message_headers(
            **kwargs,
            session_factory=_session_factory,
            commit_fn=_commit,
            session_hub=session_hub_service,
        )

    shared_artifact_id = "task-shared:stream"
    events = (
        {
            "artifactUpdate": {
                "op": "append",
                "artifact": {
                    "artifactId": shared_artifact_id,
                    "parts": [{"text": "thinking"}],
                    "metadata": {
                        "shared": {
                            "stream": {
                                "blockType": "reasoning",
                                "messageId": "msg-stream-shared",
                                "eventId": "evt-shared-1",
                                "seq": 1,
                            }
                        }
                    },
                },
            }
        },
        {
            "artifactUpdate": {
                "op": "append",
                "artifact": {
                    "artifactId": shared_artifact_id,
                    "parts": [
                        {
                            "data": {
                                "call_id": "call-1",
                                "tool": "bash",
                                "status": "completed",
                                "output": "pwd",
                            }
                        }
                    ],
                    "metadata": {
                        "shared": {
                            "stream": {
                                "blockType": "tool_call",
                                "messageId": "msg-stream-shared",
                                "eventId": "evt-shared-2",
                                "seq": 2,
                            }
                        }
                    },
                },
            }
        },
        {
            "artifactUpdate": {
                "op": "replace",
                "lastChunk": True,
                "artifact": {
                    "artifactId": shared_artifact_id,
                    "parts": [{"text": "final answer"}],
                    "metadata": {
                        "shared": {
                            "stream": {
                                "blockType": "text",
                                "source": "final_snapshot",
                                "messageId": "msg-stream-shared",
                                "eventId": "evt-shared-3",
                                "seq": 3,
                            }
                        }
                    },
                },
            }
        },
    )

    for event_payload in events:
        await persist_stream_block_update(
            state=state,
            event_payload=event_payload,
            request=_build_request(user_id=user.id),
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
        request=_build_request(user_id=user.id),
        session_factory=_session_factory,
        commit_fn=_commit,
        session_hub=session_hub_service,
        ensure_headers_fn=_ensure_headers_adapter,
    )

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
