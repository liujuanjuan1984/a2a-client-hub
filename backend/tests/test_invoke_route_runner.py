from __future__ import annotations

import asyncio
import inspect
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app.schemas.a2a_invoke import A2AAgentInvokeRequest, A2AAgentInvokeResponse
from app.services import invoke_route_runner
from app.services.a2a_invoke_service import StreamFinishReason, StreamOutcome
from app.utils.idempotency_key import IDEMPOTENCY_KEY_MAX_LENGTH


async def _consume_stream(response: StreamingResponse) -> None:
    async for _ in response.body_iterator:
        pass


class _NoopWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_close_open_transaction_commits_read_only_session() -> None:
    class _ReadOnlySession:
        def __init__(self) -> None:
            self.committed = 0
            self.rolled_back = 0
            self.new = set()
            self.dirty = set()
            self.deleted = set()

        def in_transaction(self) -> bool:
            return True

        async def commit(self) -> None:
            self.committed += 1

        async def rollback(self) -> None:
            self.rolled_back += 1

    session = _ReadOnlySession()
    await invoke_route_runner._close_open_transaction(session)  # noqa: SLF001
    assert session.committed == 1
    assert session.rolled_back == 0


@pytest.mark.asyncio
async def test_close_open_transaction_does_not_commit_when_session_has_pending_writes() -> (
    None
):
    class _DirtySession:
        def __init__(self) -> None:
            self.committed = 0
            self.new = {object()}
            self.dirty = set()
            self.deleted = set()

        def in_transaction(self) -> bool:
            return True

        async def commit(self) -> None:
            self.committed += 1

    session = _DirtySession()
    await invoke_route_runner._close_open_transaction(session)  # noqa: SLF001
    assert session.committed == 0


@pytest.mark.asyncio
async def test_http_stream_guard_blocks_duplicate_request_until_stream_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoke_route_runner._invoke_inflight_keys.clear()
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_run_http_invoke(**kwargs):  # noqa: ARG001
        async def iterator():
            started.set()
            await release.wait()
            yield "data: {}\n\n"

        return StreamingResponse(iterator(), media_type="text/event-stream")

    monkeypatch.setattr(invoke_route_runner, "run_http_invoke", fake_run_http_invoke)

    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/a2a", name="Demo Agent")
    )

    async def runtime_builder():
        return runtime

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "run long task",
            "conversationId": str(uuid4()),
            "metadata": {},
        }
    )
    common_kwargs = {
        "db": None,
        "user_id": uuid4(),
        "agent_id": uuid4(),
        "agent_source": "shared",
        "payload": payload,
        "gateway": object(),
        "runtime_builder": runtime_builder,
        "runtime_not_found_errors": (RuntimeError,),
        "runtime_not_found_status_code": 404,
        "runtime_validation_errors": (ValueError,),
        "runtime_validation_status_code": 400,
        "validate_message": lambda _: [],
        "logger": SimpleNamespace(info=lambda *args, **kwargs: None),
        "invoke_log_message": "test invoke",
        "invoke_log_extra_builder": lambda request, runtime: {},  # noqa: ARG001
    }

    first_response = await invoke_route_runner.run_http_invoke_route(
        **common_kwargs,
        stream=True,
    )
    assert isinstance(first_response, StreamingResponse)
    consume_task = asyncio.create_task(_consume_stream(first_response))
    await asyncio.wait_for(started.wait(), timeout=1.0)

    with pytest.raises(HTTPException) as exc_info:
        await invoke_route_runner.run_http_invoke_route(
            **common_kwargs,
            stream=False,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "invoke_inflight"

    release.set()
    await asyncio.wait_for(consume_task, timeout=1.0)
    assert invoke_route_runner._invoke_inflight_keys == {}


@pytest.mark.asyncio
async def test_run_http_invoke_route_stream_maps_value_error_to_http_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoke_route_runner._invoke_inflight_keys.clear()

    async def fake_run_http_invoke_with_session_recovery(**kwargs):  # noqa: ARG001
        raise ValueError("message_id_conflict")

    monkeypatch.setattr(
        invoke_route_runner,
        "run_http_invoke_with_session_recovery",
        fake_run_http_invoke_with_session_recovery,
    )

    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/a2a", name="Demo Agent")
    )

    async def runtime_builder():
        return runtime

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "run long task",
            "conversationId": str(uuid4()),
            "metadata": {},
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        await invoke_route_runner.run_http_invoke_route(
            db=None,
            user_id=uuid4(),
            agent_id=uuid4(),
            agent_source="shared",
            payload=payload,
            stream=True,
            gateway=object(),
            runtime_builder=runtime_builder,
            runtime_not_found_errors=(RuntimeError,),
            runtime_not_found_status_code=404,
            runtime_validation_errors=(ValueError,),
            runtime_validation_status_code=400,
            validate_message=lambda _: [],
            logger=SimpleNamespace(info=lambda *args, **kwargs: None),
            invoke_log_message="test invoke",
            invoke_log_extra_builder=lambda request, runtime: {},  # noqa: ARG001
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "message_id_conflict"
    assert invoke_route_runner._invoke_inflight_keys == {}


@pytest.mark.asyncio
async def test_run_http_invoke_records_usage_metadata(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class _DummySessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

    async def fake_prepare_state(**kwargs):  # noqa: ARG001
        return invoke_route_runner._InvokeState(
            local_session_id=uuid4(),
            local_source="manual",
            context_id=None,
            metadata={},
            stream_identity={},
            stream_usage={},
            user_message_id=None,
        )

    async def fake_record_local_invoke_messages(
        db,  # noqa: ARG001
        *,
        response_metadata=None,
        **kwargs,  # noqa: ARG001
    ):
        captured["response_metadata"] = response_metadata

    async def fake_commit_safely(db):  # noqa: ARG001
        return None

    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages_by_local_session_id",
        fake_record_local_invoke_messages,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)
    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )

    class _Gateway:
        async def stream(self, **kwargs):  # noqa: ARG002
            yield {
                "kind": "artifact-update",
                "artifact": {
                    "parts": [{"kind": "text", "text": "ok"}],
                    "metadata": {
                        "opencode": {
                            "block_type": "text",
                            "message_id": "msg-usage-1",
                            "event_id": "evt-usage-1",
                            "usage": {
                                "input_tokens": 100,
                                "output_tokens": 20,
                                "total_tokens": 120,
                                "cost": 0.01,
                            },
                        }
                    },
                },
            }
            yield {"kind": "status-update", "final": True}

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {},
        }
    )
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )

    response = await invoke_route_runner.run_http_invoke(
        db=object(),
        gateway=_Gateway(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        stream=False,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={},
    )

    assert response.success is True
    response_metadata = captured["response_metadata"]
    assert isinstance(response_metadata, dict)
    assert response_metadata["usage"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "cost": 0.01,
    }


@pytest.mark.asyncio
async def test_build_consume_stream_callbacks_persists_outcome_content_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _DummySessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

    async def fake_record_local_invoke_messages(
        db,  # noqa: ARG001
        **kwargs,
    ) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "conversation_id": kwargs["local_session_id"],
            "user_message_id": uuid4(),
            "agent_message_id": uuid4(),
        }

    async def fake_commit_safely(db):  # noqa: ARG001
        return None

    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages_by_local_session_id",
        fake_record_local_invoke_messages,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    client_user_message_id = str(uuid4())
    client_agent_message_id = str(uuid4())
    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="scheduled",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        user_message_id=client_user_message_id,
        agent_message_id=client_agent_message_id,
    )
    on_event, on_finalized = invoke_route_runner._build_consume_stream_callbacks(
        state=state,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        query="hello",
        transport="scheduled",
        stream_enabled=True,
    )

    await on_event(
        {
            "kind": "artifact-update",
            "artifact": {
                "parts": [{"kind": "text", "text": "partial response"}],
                "metadata": {
                    "opencode": {
                        "block_type": "text",
                        "message_id": "msg-partial-1",
                        "event_id": "evt-partial-1",
                    }
                },
            },
        }
    )
    await on_finalized(
        StreamOutcome(
            success=False,
            finish_reason=StreamFinishReason.TIMEOUT_TOTAL,
            final_text="partial response",
            error_message="A2A stream total timeout after 60.0s",
            error_code="timeout",
            elapsed_seconds=60.0,
            idle_seconds=0.1,
            terminal_event_seen=False,
        )
    )

    assert captured["response_content"] == "partial response"
    assert captured["success"] is False
    response_metadata = captured["response_metadata"]
    assert isinstance(response_metadata, dict)
    stream_metadata = response_metadata["stream"]
    assert stream_metadata["schema_version"] == 1
    assert stream_metadata["finish_reason"] == "timeout_total"
    assert stream_metadata["error"]["message"] == "A2A stream total timeout after 60.0s"
    assert stream_metadata["error"]["error_code"] == "timeout"
    assert "message_blocks" not in response_metadata
    assert state.persisted_response_content == "partial response"
    assert state.persisted_error_code == "timeout"
    assert state.persisted_finish_reason == "timeout_total"
    assert captured["user_message_id"] == UUID(client_user_message_id)
    assert captured["agent_message_id"] == UUID(client_agent_message_id)


def test_resolve_invoke_idempotency_key_hashes_overlong_value() -> None:
    long_user_message_id = "m" * 512
    state = invoke_route_runner._InvokeState(
        local_session_id=None,
        local_source=None,
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        user_message_id=long_user_message_id,
    )

    resolved = invoke_route_runner._resolve_invoke_idempotency_key(
        state=state,
        transport="scheduled",
    )

    assert resolved is not None
    assert len(resolved) == IDEMPOTENCY_KEY_MAX_LENGTH
    assert ":h:" in resolved


def test_normalize_optional_message_id_validates_uuid_inputs() -> None:
    normalized = invoke_route_runner._normalize_optional_message_id(  # noqa: SLF001
        " 550e8400-e29b-41d4-a716-446655440000 "
    )
    assert normalized == "550e8400-e29b-41d4-a716-446655440000"
    assert (
        invoke_route_runner._normalize_optional_message_id(None) is None
    )  # noqa: SLF001
    assert (
        invoke_route_runner._normalize_optional_message_id(" ") is None
    )  # noqa: SLF001
    with pytest.raises(ValueError, match="invalid_message_id"):
        invoke_route_runner._normalize_optional_message_id("not-a-uuid")  # noqa: SLF001


@pytest.mark.asyncio
async def test_consume_stream_callbacks_bind_task_id_and_unregister_inflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_bind_inflight_task_id(
        *,
        user_id,  # noqa: ANN001, ARG001
        conversation_id,  # noqa: ANN001, ARG001
        token,  # noqa: ANN001
        task_id,  # noqa: ANN001
    ) -> bool:
        captured["bound_token"] = token
        captured["bound_task_id"] = task_id
        return True

    async def fake_unregister_inflight_invoke(
        *,
        user_id,  # noqa: ANN001, ARG001
        conversation_id,  # noqa: ANN001, ARG001
        token,  # noqa: ANN001
    ) -> bool:
        captured["unregistered_token"] = token
        return True

    async def fake_persist_local_outcome(**_kwargs):  # noqa: ANN001
        return None

    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "bind_inflight_task_id",
        fake_bind_inflight_task_id,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "unregister_inflight_invoke",
        fake_unregister_inflight_invoke,
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_persist_local_outcome",
        fake_persist_local_outcome,
    )

    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="manual",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        user_message_id=None,
        inflight_token="token-1",
    )
    on_event, on_finalized = invoke_route_runner._build_consume_stream_callbacks(
        state=state,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        query="hello",
        transport="http_json",
        stream_enabled=False,
    )

    await on_event({"task": {"id": "task-xyz"}})
    assert captured["bound_token"] == "token-1"
    assert captured["bound_task_id"] == "task-xyz"
    assert state.upstream_task_id == "task-xyz"

    await on_finalized(
        StreamOutcome(
            success=True,
            finish_reason=StreamFinishReason.SUCCESS,
            final_text="ok",
            error_message=None,
            error_code=None,
            elapsed_seconds=1.0,
            idle_seconds=0.1,
            terminal_event_seen=True,
        )
    )
    assert captured["unregistered_token"] == "token-1"
    assert state.inflight_token is None


@pytest.mark.asyncio
async def test_persist_stream_block_update_consumes_and_persists_optional_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _DummySession:
        async def scalar(self, *_args, **_kwargs):  # noqa: ANN001
            return object()

    class _DummySessionContext:
        async def __aenter__(self) -> _DummySession:
            return _DummySession()

        async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

    async def fake_append_agent_message_block_update(_db, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return object()

    async def fake_commit_safely(_db):  # noqa: ANN001
        return None

    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "append_agent_message_block_update",
        fake_append_agent_message_block_update,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="manual",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        user_message_id=None,
        message_refs={
            "user_message_id": str(uuid4()),
            "agent_message_id": str(uuid4()),
        },
        next_event_seq=3,
        persisted_block_count=0,
    )

    event_payload = {
        "kind": "artifact-update",
        "seq": 9,
        "append": False,
        "lastChunk": True,
        "artifact": {
            "parts": [{"kind": "text", "text": "chunk-body"}],
            "metadata": {
                "opencode": {
                    "block_type": "text",
                    "message_id": "msg-opt",
                    "event_id": "evt-opt",
                }
            },
        },
    }

    await invoke_route_runner._persist_stream_block_update(  # noqa: SLF001
        state=state,
        event_payload=event_payload,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        query="hello",
        transport="http_json",
        stream_enabled=True,
    )

    assert captured["seq"] == 9
    assert captured["append"] is False
    assert captured["is_finished"] is True
    assert state.next_event_seq == 10
    assert state.persisted_block_count == 1
    assert event_payload["message_id"] == str(state.message_refs["agent_message_id"])
    assert event_payload["event_id"] == "evt-opt"
    assert event_payload["seq"] == 9
    assert "messageId" not in event_payload
    assert "eventId" not in event_payload
    assert "eventSeq" not in event_payload
    assert "sequence" not in event_payload
    assert event_payload["artifact"]["metadata"]["opencode"]["message_id"] == str(
        state.message_refs["agent_message_id"]
    )
    assert event_payload["artifact"]["metadata"]["opencode"]["event_id"] == "evt-opt"
    assert event_payload["artifact"]["metadata"]["opencode"]["seq"] == 9


@pytest.mark.asyncio
async def test_persist_local_outcome_synthesizes_final_chunk_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_chunk: dict[str, object] = {}
    captured_outcome: dict[str, object] = {}

    class _DummySession:
        async def scalar(self, *_args, **_kwargs):  # noqa: ANN001
            return object()

    class _DummySessionContext:
        async def __aenter__(self) -> _DummySession:
            return _DummySession()

        async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

    async def fake_has_agent_message_blocks(_db, **_kwargs) -> bool:  # noqa: ANN001
        return False

    async def fake_append_agent_message_block_update(
        _db, **kwargs
    ) -> object:  # noqa: ANN001
        captured_chunk.update(kwargs)
        return object()

    async def fake_record_local_invoke_messages(
        _db, **kwargs  # noqa: ANN001
    ) -> dict[str, object]:
        captured_outcome.update(kwargs)
        return {
            "conversation_id": kwargs["local_session_id"],
            "user_message_id": kwargs["idempotency_key"] and uuid4(),
            "agent_message_id": uuid4(),
        }

    async def fake_commit_safely(_db):  # noqa: ANN001
        return None

    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "has_agent_message_blocks",
        fake_has_agent_message_blocks,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "append_agent_message_block_update",
        fake_append_agent_message_block_update,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages_by_local_session_id",
        fake_record_local_invoke_messages,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="manual",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        user_message_id=None,
        message_refs={
            "conversation_id": uuid4(),
            "user_message_id": uuid4(),
            "agent_message_id": uuid4(),
        },
        next_event_seq=1,
        persisted_block_count=0,
    )

    await invoke_route_runner._persist_local_outcome(  # noqa: SLF001
        state=state,
        outcome=StreamOutcome(
            success=True,
            finish_reason=StreamFinishReason.SUCCESS,
            final_text="non-stream final",
            error_message=None,
            error_code=None,
            elapsed_seconds=1.0,
            idle_seconds=0.1,
            terminal_event_seen=True,
        ),
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        query="hello",
        transport="http_json",
        stream_enabled=False,
    )

    assert captured_chunk["seq"] == 1
    assert captured_chunk["block_type"] == "text"
    assert captured_chunk["content"] == "non-stream final"
    assert captured_chunk["append"] is False
    assert captured_chunk["is_finished"] is True
    assert captured_chunk["source"] == "finalize_snapshot"
    assert captured_outcome["response_content"] == "non-stream final"
    assert state.persisted_block_count == 1
    assert state.next_event_seq == 2


@pytest.mark.asyncio
async def test_run_http_invoke_stream_uses_finalized_callback_for_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _DummySessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

    async def fake_prepare_state(**kwargs):  # noqa: ARG001
        return invoke_route_runner._InvokeState(
            local_session_id=uuid4(),
            local_source="manual",
            context_id=None,
            metadata={"run_id": "run-1"},
            stream_identity={},
            stream_usage={},
            user_message_id=None,
        )

    async def fake_record_local_invoke_messages(
        db,  # noqa: ARG001
        **kwargs,
    ) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "conversation_id": kwargs["local_session_id"],
            "user_message_id": uuid4(),
            "agent_message_id": uuid4(),
        }

    async def fake_commit_safely(db):  # noqa: ARG001
        return None

    def fake_stream_sse(**kwargs):
        finalized = kwargs.get("on_finalized")
        assert callable(finalized)

        async def _iterator():
            await finalized(
                StreamOutcome(
                    success=False,
                    finish_reason=StreamFinishReason.TIMEOUT_TOTAL,
                    final_text="partial sse",
                    error_message="timeout",
                    error_code="timeout",
                    elapsed_seconds=60.0,
                    idle_seconds=1.0,
                    terminal_event_seen=False,
                )
            )
            yield "event: stream_end\ndata: {}\n\n"

        return StreamingResponse(_iterator(), media_type="text/event-stream")

    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages_by_local_session_id",
        fake_record_local_invoke_messages,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)
    monkeypatch.setattr(
        invoke_route_runner.a2a_invoke_service, "stream_sse", fake_stream_sse
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )

    payload = A2AAgentInvokeRequest.model_validate(
        {"query": "hello", "conversationId": str(uuid4()), "metadata": {}}
    )
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )

    response = await invoke_route_runner.run_http_invoke(
        db=object(),
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        stream=True,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={},
    )

    assert isinstance(response, StreamingResponse)
    await _consume_stream(response)
    assert captured["response_content"] == "partial sse"
    stream_metadata = captured["response_metadata"]["stream"]
    assert stream_metadata["finish_reason"] == "timeout_total"


@pytest.mark.asyncio
async def test_run_ws_invoke_uses_finalized_callback_for_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _DummySessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

    async def fake_prepare_state(**kwargs):  # noqa: ARG001
        return invoke_route_runner._InvokeState(
            local_session_id=uuid4(),
            local_source="manual",
            context_id=None,
            metadata={"run_id": "run-2"},
            stream_identity={},
            stream_usage={},
            user_message_id=None,
        )

    async def fake_record_local_invoke_messages(
        db,  # noqa: ARG001
        **kwargs,
    ) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "conversation_id": kwargs["local_session_id"],
            "user_message_id": uuid4(),
            "agent_message_id": uuid4(),
        }

    async def fake_commit_safely(db):  # noqa: ARG001
        return None

    async def fake_stream_ws(**kwargs):
        finalized = kwargs.get("on_finalized")
        assert callable(finalized)
        await finalized(
            StreamOutcome(
                success=True,
                finish_reason=StreamFinishReason.SUCCESS,
                final_text="ws final",
                error_message=None,
                error_code=None,
                elapsed_seconds=1.0,
                idle_seconds=0.1,
                terminal_event_seen=True,
            )
        )

    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages_by_local_session_id",
        fake_record_local_invoke_messages,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)
    monkeypatch.setattr(
        invoke_route_runner.a2a_invoke_service, "stream_ws", fake_stream_ws
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )

    payload = A2AAgentInvokeRequest.model_validate(
        {"query": "hello", "conversationId": str(uuid4()), "metadata": {}}
    )
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )

    await invoke_route_runner.run_ws_invoke(
        websocket=_NoopWebSocket(),
        db=object(),
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={},
    )

    assert captured["response_content"] == "ws final"
    assert captured["response_metadata"]["stream"]["finish_reason"] == "success"


@pytest.mark.asyncio
async def test_run_http_invoke_route_retries_session_not_found_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    original_conversation_id = str(uuid4())
    rebound_conversation_id = str(uuid4())
    attempts: list[dict[str, str]] = []

    async def fake_run_http_invoke(**kwargs):  # noqa: ARG001
        payload = kwargs["payload"]
        attempts.append(
            {
                "conversationId": payload.conversation_id,
                "metadata": dict(payload.metadata or {}),
            }
        )
        if len(attempts) == 1:
            return A2AAgentInvokeResponse(
                success=False,
                error="session missing",
                error_code="session_not_found",
                agent_name="Demo Agent",
                agent_url="https://example.com",
            )
        return A2AAgentInvokeResponse(
            success=True,
            content="ok",
            error_code=None,
            agent_name="Demo Agent",
            agent_url="https://example.com",
        )

    async def fake_continue_session(
        *_,
        user_id: object,  # noqa: ARG002
        conversation_id: str,
        **__,  # noqa: ARG001
    ) -> tuple[dict[str, object], bool]:
        assert conversation_id == original_conversation_id
        return (
            {
                "conversationId": rebound_conversation_id,
                "source": "manual",
                "metadata": {
                    "provider": "opencode",
                    "externalSessionId": "upstream-sid-2",
                    "contextId": "ctx-2",
                },
            },
            True,
        )

    async def fake_commit_safely(_: object) -> None:
        return None

    monkeypatch.setattr(invoke_route_runner, "run_http_invoke", fake_run_http_invoke)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "continue_session",
        fake_continue_session,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    async def runtime_builder():
        return runtime

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "test invoke route",
            "conversationId": original_conversation_id,
            "metadata": {},
        }
    )

    response = await invoke_route_runner.run_http_invoke_route(
        db=object(),
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        stream=False,
        gateway=object(),
        runtime_builder=runtime_builder,
        runtime_not_found_errors=(RuntimeError,),
        runtime_not_found_status_code=404,
        runtime_validation_errors=(ValueError,),
        runtime_validation_status_code=400,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        invoke_log_message="test invoke",
        invoke_log_extra_builder=lambda req, runtime: {},  # noqa: ARG001
    )

    assert isinstance(response, A2AAgentInvokeResponse)
    assert response.success is True
    assert response.content == "ok"
    assert len(attempts) == 2
    assert attempts[0]["conversationId"] == original_conversation_id
    assert attempts[1]["conversationId"] == rebound_conversation_id
    assert attempts[1]["metadata"].get("provider") == "opencode"
    assert attempts[1]["metadata"].get("externalSessionId") == "upstream-sid-2"


@pytest.mark.asyncio
async def test_run_http_invoke_route_retries_once_for_session_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    attempt = 0

    async def fake_run_http_invoke(**kwargs):  # noqa: ARG001
        nonlocal attempt
        attempt += 1
        return A2AAgentInvokeResponse(
            success=False,
            error="session missing",
            error_code="session_not_found",
            agent_name="Demo Agent",
            agent_url="https://example.com",
        )

    async def fake_continue_session(
        *_,
        user_id: object,  # noqa: ARG002
        conversation_id: str,
        **__,  # noqa: ARG001
    ) -> tuple[dict[str, object], bool]:
        assert conversation_id
        return (
            {
                "conversationId": conversation_id,
                "source": "manual",
                "metadata": {
                    "provider": "opencode",
                    "externalSessionId": "upstream-sid-2",
                    "contextId": "ctx-2",
                },
            },
            True,
        )

    async def fake_commit_safely(_: object) -> None:
        return None

    monkeypatch.setattr(invoke_route_runner, "run_http_invoke", fake_run_http_invoke)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "continue_session",
        fake_continue_session,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    async def runtime_builder():
        return runtime

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "test invoke route",
            "conversationId": str(uuid4()),
            "metadata": {},
        }
    )

    response = await invoke_route_runner.run_http_invoke_route(
        db=object(),
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        stream=False,
        gateway=object(),
        runtime_builder=runtime_builder,
        runtime_not_found_errors=(RuntimeError,),
        runtime_not_found_status_code=404,
        runtime_validation_errors=(ValueError,),
        runtime_validation_status_code=400,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        invoke_log_message="test invoke",
        invoke_log_extra_builder=lambda req, runtime: {},  # noqa: ARG001
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 404
    response_payload = json.loads(response.body.decode())
    assert response_payload["success"] is False
    assert response_payload["error_code"] == "session_not_found"
    assert attempt == 2


@pytest.mark.asyncio
async def test_run_ws_invoke_route_retries_session_not_found_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    original_conversation_id = str(uuid4())
    rebound_conversation_id = str(uuid4())
    prepare_payloads: list[dict[str, object]] = []
    stream_calls = 0

    async def fake_prepare_state(**kwargs):  # noqa: ARG001
        payload = kwargs["payload"]
        prepare_payloads.append(
            {
                "conversationId": payload.conversation_id,
                "metadata": dict(payload.metadata or {}),
            }
        )
        return invoke_route_runner._InvokeState(
            local_session_id=uuid4(),
            local_source="manual",
            context_id=None,
            metadata={},
            stream_identity={},
            stream_usage={},
            user_message_id=None,
        )

    async def fake_stream_ws(*, on_error_metadata=None, **kwargs):  # noqa: ARG001
        nonlocal stream_calls
        stream_calls += 1
        if stream_calls == 1 and on_error_metadata:
            result = on_error_metadata(
                {
                    "message": "Upstream streaming failed",
                    "error_code": "session_not_found",
                }
            )
            if inspect.isawaitable(result):
                await result

    async def fake_continue_session(
        *_,
        user_id: object,  # noqa: ARG002
        conversation_id: str,
        **__,  # noqa: ARG001
    ) -> tuple[dict[str, object], bool]:
        assert conversation_id == original_conversation_id
        return (
            {
                "conversationId": rebound_conversation_id,
                "source": "manual",
                "metadata": {
                    "provider": "opencode",
                    "externalSessionId": "upstream-sid-2",
                    "contextId": "ctx-2",
                },
            },
            True,
        )

    async def fake_commit_safely(_: object) -> None:
        return None

    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)
    monkeypatch.setattr(
        invoke_route_runner.a2a_invoke_service,
        "stream_ws",
        fake_stream_ws,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "continue_session",
        fake_continue_session,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages_by_local_session_id",
        lambda **kwargs: None,  # noqa: ARG005
    )

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "test invoke route",
            "conversationId": original_conversation_id,
            "metadata": {},
        }
    )
    websocket = _NoopWebSocket()

    await invoke_route_runner.run_ws_invoke_with_session_recovery(
        websocket=websocket,
        db=object(),
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={
            "user_id": str(uuid4()),
            "agent_id": str(uuid4()),
        },
        max_recovery_attempts=1,
    )

    assert prepare_payloads == [
        {
            "conversationId": original_conversation_id,
            "metadata": {},
        },
        {
            "conversationId": rebound_conversation_id,
            "metadata": {
                "provider": "opencode",
                "externalSessionId": "upstream-sid-2",
            },
        },
    ]
    assert stream_calls == 2
    assert len(websocket.sent) == 1
    assert json.loads(websocket.sent[0]) == {"event": "stream_end", "data": {}}


@pytest.mark.asyncio
async def test_run_ws_invoke_route_retries_session_not_found_then_exhausts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    original_conversation_id = str(uuid4())
    rebound_conversation_id = str(uuid4())
    prepare_payloads: list[dict[str, object]] = []
    stream_calls = 0
    observed_error_codes: list[str] = []

    async def fake_prepare_state(**kwargs):  # noqa: ARG001
        payload = kwargs["payload"]
        prepare_payloads.append(
            {
                "conversationId": payload.conversation_id,
                "metadata": dict(payload.metadata or {}),
            }
        )
        return invoke_route_runner._InvokeState(
            local_session_id=uuid4(),
            local_source="manual",
            context_id=None,
            metadata={},
            stream_identity={},
            stream_usage={},
            user_message_id=None,
        )

    async def fake_stream_ws(*, on_error_metadata=None, **kwargs):  # noqa: ARG001
        nonlocal stream_calls
        stream_calls += 1
        if on_error_metadata:
            observed_error_codes.append("session_not_found")
            result = on_error_metadata(
                {
                    "message": "Upstream streaming failed",
                    "error_code": "session_not_found",
                }
            )
            if inspect.isawaitable(result):
                await result

    async def fake_continue_session(
        *_,
        user_id: object,  # noqa: ARG002
        conversation_id: str,
        **__,  # noqa: ARG001
    ) -> tuple[dict[str, object], bool]:
        assert conversation_id == original_conversation_id
        return (
            {
                "conversationId": rebound_conversation_id,
                "source": "manual",
                "metadata": {
                    "provider": "opencode",
                    "externalSessionId": "upstream-sid-2",
                    "contextId": "ctx-2",
                },
            },
            True,
        )

    async def fake_commit_safely(_: object) -> None:
        return None

    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)
    monkeypatch.setattr(
        invoke_route_runner.a2a_invoke_service,
        "stream_ws",
        fake_stream_ws,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "continue_session",
        fake_continue_session,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages_by_local_session_id",
        lambda **kwargs: None,  # noqa: ARG005
    )

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "test invoke route",
            "conversationId": original_conversation_id,
            "metadata": {},
        }
    )
    websocket = _NoopWebSocket()

    await invoke_route_runner.run_ws_invoke_with_session_recovery(
        websocket=websocket,
        db=object(),
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={
            "user_id": str(uuid4()),
            "agent_id": str(uuid4()),
        },
        max_recovery_attempts=1,
    )

    sent = [json.loads(item) for item in websocket.sent]
    error_events = [event for event in sent if event["event"] == "error"]
    assert prepare_payloads == [
        {
            "conversationId": original_conversation_id,
            "metadata": {},
        },
        {
            "conversationId": rebound_conversation_id,
            "metadata": {
                "provider": "opencode",
                "externalSessionId": "upstream-sid-2",
            },
        },
    ]
    assert stream_calls == 2
    assert observed_error_codes == ["session_not_found", "session_not_found"]
    assert prepare_payloads == [
        {
            "conversationId": original_conversation_id,
            "metadata": {},
        },
        {
            "conversationId": rebound_conversation_id,
            "metadata": {
                "provider": "opencode",
                "externalSessionId": "upstream-sid-2",
            },
        },
    ]
    assert len(error_events) == 1
    assert (
        error_events[0]["data"]["error_code"] == "session_not_found_recovery_exhausted"
    )
    assert sent[-1] == {"event": "stream_end", "data": {}}


@pytest.mark.parametrize(
    "error_code, expected_status",
    [
        ("session_not_found", 404),
        ("outbound_not_allowed", 403),
        ("upstream_unreachable", 503),
        ("upstream_http_error", 502),
        ("upstream_error", 502),
        ("timeout", 504),
    ],
)
@pytest.mark.asyncio
async def test_run_http_invoke_route_returns_status_for_error_code(
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
    expected_status: int,
) -> None:
    async def fake_run_http_invoke(**kwargs):  # noqa: ARG001
        return A2AAgentInvokeResponse(
            success=False,
            error="synthetic upstream error",
            error_code=error_code,
            agent_name="Demo Agent",
            agent_url="https://example.com",
        )

    monkeypatch.setattr(invoke_route_runner, "run_http_invoke", fake_run_http_invoke)
    if error_code == "session_not_found":

        async def fake_continue_session(
            *_,
            user_id: object,  # noqa: ARG002
            conversation_id: str,
            **__,  # noqa: ARG001
        ) -> tuple[dict[str, object], bool]:
            return (
                {"conversationId": conversation_id},
                False,
            )

        async def fake_commit_safely(_: object) -> None:
            return None

        monkeypatch.setattr(
            invoke_route_runner.session_hub_service,
            "continue_session",
            fake_continue_session,
        )
        monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    runtime = SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")

    async def runtime_builder():
        return runtime

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "test invoke route",
            "conversationId": str(uuid4()),
            "metadata": {},
        }
    )

    response = await invoke_route_runner.run_http_invoke_route(
        db=object(),
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        stream=False,
        gateway=object(),
        runtime_builder=runtime_builder,
        runtime_not_found_errors=(RuntimeError,),
        runtime_not_found_status_code=404,
        runtime_validation_errors=(ValueError,),
        runtime_validation_status_code=400,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        invoke_log_message="test invoke",
        invoke_log_extra_builder=lambda req, runtime: {},  # noqa: ARG001
    )
    assert isinstance(response, JSONResponse)
    assert response.status_code == expected_status
    response_payload = json.loads(response.body.decode())
    assert response_payload["success"] is False
    assert response_payload["error_code"] == error_code
