from __future__ import annotations

from tests.invoke.invoke_route_runner_support import (
    DB_BUSY_RETRY_AFTER_SECONDS,
    A2AAgentInvokeRequest,
    A2AAgentInvokeResponse,
    DbLockFailureKind,
    HTTPException,
    PreemptedInvokeReport,
    RetryableDbLockError,
    RetryableDbQueryTimeoutError,
    SimpleNamespace,
    StreamFinishReason,
    StreamingResponse,
    StreamOutcome,
    _consume_stream,
    asyncio,
    invoke_route_runner,
    pytest,
    route_runner_state,
    uuid4,
)


@pytest.mark.asyncio
async def test_prepare_state_reuses_persisted_context_id_when_payload_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_session_id = uuid4()

    class _DummySessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, _exc_type, _exc, _tb) -> None:
            return None

    async def fake_ensure_local_session_for_invoke(
        db,  # noqa: ARG001
        **kwargs,  # noqa: ARG001
    ) -> tuple[SimpleNamespace, str]:
        return (
            SimpleNamespace(id=local_session_id, context_id="  ctx-persisted  "),
            "manual",
        )

    async def fake_commit_safely(db):  # noqa: ARG001
        return None

    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "ensure_local_session_for_invoke",
        fake_ensure_local_session_for_invoke,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(local_session_id),
            "metadata": {"locale": "zh-CN"},
        }
    )

    state = await invoke_route_runner._prepare_state(  # noqa: SLF001
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
    )

    assert state.local_session_id == local_session_id
    assert state.local_source == "manual"
    assert state.context_id == "ctx-persisted"
    assert state.metadata == {"locale": "zh-CN"}


@pytest.mark.asyncio
async def test_run_issue_ws_ticket_route_maps_lock_contention_to_http_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _raise_lock_contention(*_args, **_kwargs):
        raise RetryableDbLockError(
            "WS ticket issuance is currently locked by another operation; retry shortly.",
            kind=DbLockFailureKind.LOCK_NOT_AVAILABLE,
        )

    async def _allow_access() -> None:
        return None

    monkeypatch.setattr(
        invoke_route_runner.ws_ticket_service,
        "issue_ticket",
        _raise_lock_contention,
    )

    with pytest.raises(HTTPException) as exc_info:
        await invoke_route_runner.run_issue_ws_ticket_route(
            db=object(),
            user_id=uuid4(),
            scope_type="me_a2a_agent",
            scope_id=uuid4(),
            ensure_access=_allow_access,
            not_found_errors=(ValueError,),
            not_found_status_code=404,
            not_found_detail="not found",
        )

    assert exc_info.value.status_code == 409
    assert "retry shortly" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_run_issue_ws_ticket_route_maps_query_timeout_to_http_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _raise_query_timeout(*_args, **_kwargs):
        raise RetryableDbQueryTimeoutError(
            "WS ticket issuance timed out; service busy, retry shortly."
        )

    async def _allow_access() -> None:
        return None

    monkeypatch.setattr(
        invoke_route_runner.ws_ticket_service,
        "issue_ticket",
        _raise_query_timeout,
    )

    with pytest.raises(HTTPException) as exc_info:
        await invoke_route_runner.run_issue_ws_ticket_route(
            db=object(),
            user_id=uuid4(),
            scope_type="me_a2a_agent",
            scope_id=uuid4(),
            ensure_access=_allow_access,
            not_found_errors=(ValueError,),
            not_found_status_code=404,
            not_found_detail="not found",
        )

    assert exc_info.value.status_code == 503
    assert "service busy" in str(exc_info.value.detail)
    assert exc_info.value.headers == {"Retry-After": str(DB_BUSY_RETRY_AFTER_SECONDS)}


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
async def test_close_open_transaction_delegates_to_shared_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    async def fake_prepare_for_external_call(db) -> None:
        calls.append(db)

    session = object()
    monkeypatch.setattr(
        invoke_route_runner,
        "prepare_for_external_call",
        fake_prepare_for_external_call,
    )

    await invoke_route_runner._close_open_transaction(session)  # noqa: SLF001

    assert calls == [session]


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
async def test_run_http_invoke_route_stream_releases_inflight_guard_even_if_stream_consumer_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoke_route_runner._invoke_inflight_keys.clear()
    stream_started = asyncio.Event()

    async def fake_run_http_invoke_with_session_recovery(**kwargs):  # noqa: ARG001
        async def iterator():
            stream_started.set()
            yield "data: {}\n\n"
            await asyncio.Future()

        return StreamingResponse(iterator(), media_type="text/event-stream")

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
            "query": "cancel cleanup test",
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

    assert isinstance(response, StreamingResponse)

    first_chunk = await response.body_iterator.__anext__()
    assert first_chunk == "data: {}\n\n"
    await asyncio.wait_for(stream_started.wait(), timeout=1.0)
    assert invoke_route_runner._invoke_inflight_keys

    consume_task = asyncio.create_task(response.body_iterator.aclose())
    consume_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consume_task
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
async def test_run_http_invoke_route_stream_maps_interrupt_failure_to_http_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoke_route_runner._invoke_inflight_keys.clear()

    async def fake_run_http_invoke_with_session_recovery(**kwargs):  # noqa: ARG001
        raise ValueError("invoke_interrupt_failed")

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
    assert exc_info.value.detail == "invoke_interrupt_failed"
    assert invoke_route_runner._invoke_inflight_keys == {}


@pytest.mark.asyncio
async def test_run_http_invoke_records_usage_metadata(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class _DummySessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, _exc_type, _exc, _tb) -> None:
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
                        "block_type": "text",
                        "message_id": "msg-usage-1",
                        "event_id": "evt-usage-1",
                        "shared": {
                            "usage": {
                                "input_tokens": 100,
                                "output_tokens": 20,
                                "total_tokens": 120,
                                "cost": 0.01,
                            },
                        },
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
async def test_run_http_invoke_uses_recovered_state_context_id_for_upstream_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_consume_stream(**kwargs):
        captured["context_id"] = kwargs["context_id"]
        return StreamOutcome(
            success=True,
            finish_reason=StreamFinishReason.SUCCESS,
            final_text="ok",
            error_message=None,
            error_code=None,
            elapsed_seconds=0.1,
            idle_seconds=0.0,
            terminal_event_seen=True,
            source="upstream_a2a",
        )

    async def fake_prepare_state(**kwargs):  # noqa: ARG001
        return invoke_route_runner._InvokeState(
            local_session_id=None,
            local_source=None,
            context_id="ctx-reused",
            metadata={},
            stream_identity={},
            stream_usage={},
        )

    monkeypatch.setattr(
        invoke_route_runner.a2a_invoke_service,
        "consume_stream",
        fake_consume_stream,
    )
    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)

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
        gateway=object(),
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
    assert response.content == "ok"
    assert captured["context_id"] == "ctx-reused"


@pytest.mark.asyncio
async def test_run_http_invoke_non_stream_accepts_blocking_message_payload_via_consume_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Gateway:
        async def stream(self, **kwargs):  # noqa: ARG002
            yield SimpleNamespace(
                model_dump=lambda exclude_none=True: {  # noqa: ARG005
                    "kind": "message",
                    "message_id": "msg-run-http-invoke-1",
                    "task_id": "task-run-http-invoke-1",
                    "parts": [{"type": "text", "text": "downgraded result"}],
                    "metadata": {
                        "event_id": "evt-run-http-invoke-1",
                        "block_type": "text",
                    },
                }
            )

    async def fake_prepare_state(**kwargs):  # noqa: ARG001
        return invoke_route_runner._InvokeState(
            local_session_id=None,
            local_source=None,
            context_id=None,
            metadata={},
            stream_identity={},
            stream_usage={},
        )

    async def fake_persist_stream_block_update(**kwargs):  # noqa: ARG001
        return None

    async def fake_persist_interrupt_lifecycle_event(**kwargs):  # noqa: ARG001
        return None

    async def fake_flush_stream_buffer(**kwargs):  # noqa: ARG001
        return None

    async def fake_persist_local_outcome(**kwargs):  # noqa: ARG001
        return None

    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)
    monkeypatch.setattr(
        invoke_route_runner,
        "_persist_stream_block_update",
        fake_persist_stream_block_update,
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_persist_interrupt_lifecycle_event",
        fake_persist_interrupt_lifecycle_event,
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_flush_stream_buffer",
        fake_flush_stream_buffer,
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_persist_local_outcome",
        fake_persist_local_outcome,
    )

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

    assert isinstance(response, A2AAgentInvokeResponse)
    assert response.success is True
    assert response.content == "downgraded result"
    assert response.error is None


@pytest.mark.asyncio
async def test_run_http_invoke_returns_structured_error_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Gateway:
        async def stream(self, **kwargs):  # noqa: ARG002
            if kwargs:
                await asyncio.sleep(0)
            for event in ():
                yield event

    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )

    async def fake_consume_stream(**kwargs):  # noqa: ARG001
        return StreamOutcome(
            success=False,
            finish_reason=StreamFinishReason.UPSTREAM_ERROR,
            final_text="",
            error_message="Upstream streaming failed",
            error_code="invalid_params",
            elapsed_seconds=0.1,
            idle_seconds=0.0,
            terminal_event_seen=False,
            source="upstream_a2a",
            jsonrpc_code=-32602,
            missing_params=({"name": "project_id", "required": True},),
            upstream_error={"message": "project_id required"},
        )

    monkeypatch.setattr(
        invoke_route_runner.a2a_invoke_service,
        "consume_stream",
        fake_consume_stream,
    )

    async def fake_prepare_state(**kwargs):  # noqa: ARG001
        return invoke_route_runner._InvokeState(
            local_session_id=None,
            local_source=None,
            context_id=None,
            metadata={},
            stream_identity={},
            stream_usage={},
        )

    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {},
        }
    )

    response = await invoke_route_runner.run_http_invoke(
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

    assert response.success is False
    assert response.error_code == "invalid_params"
    assert response.source == "upstream_a2a"
    assert response.jsonrpc_code == -32602
    assert response.missing_params == [{"name": "project_id", "required": True}]
    assert response.upstream_error == {"message": "project_id required"}


def test_normalize_optional_message_id_validates_uuid_inputs() -> None:
    normalized = route_runner_state.normalize_optional_message_id(
        " 550e8400-e29b-41d4-a716-446655440000 "
    )
    assert normalized == "550e8400-e29b-41d4-a716-446655440000"
    assert route_runner_state.normalize_optional_message_id(None) is None
    assert route_runner_state.normalize_optional_message_id(" ") is None
    with pytest.raises(ValueError, match="invalid_message_id"):
        route_runner_state.normalize_optional_message_id("not-a-uuid")


def test_is_interrupt_requested_from_metadata_extensions() -> None:
    payload_interrupt = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {"extensions": {"interrupt": True}},
        }
    )
    payload_normal = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {"extensions": {"interrupt": False}},
        }
    )

    assert (
        invoke_route_runner._is_interrupt_requested(payload_interrupt) is True
    )  # noqa: SLF001
    assert (
        invoke_route_runner._is_interrupt_requested(payload_normal) is False
    )  # noqa: SLF001


@pytest.mark.asyncio
async def test_preempt_previous_invoke_only_when_interrupt_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="manual",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        user_message_id=str(uuid4()),
        agent_message_id=str(uuid4()),
    )
    called: list[str] = []
    recorded_events: list[dict[str, object]] = []

    async def fake_record_preempt_event_by_local_session_id(*args, **kwargs):
        recorded_events.append(kwargs["event"])

    target_message_id = str(uuid4())

    async def fake_preempt_inflight_invoke_report(
        *,
        user_id,  # noqa: ANN001, ARG001
        conversation_id,  # noqa: ANN001, ARG001
        reason,  # noqa: ANN001
        pending_event,  # noqa: ANN001
    ) -> PreemptedInvokeReport:
        called.append(str(reason))
        recorded_events.append(dict(pending_event))
        return PreemptedInvokeReport(
            attempted=True,
            status="completed",
            target_task_ids=["task-preempt-1"],
        )

    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "preempt_inflight_invoke_report",
        fake_preempt_inflight_invoke_report,
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_find_latest_agent_message_id",
        lambda **_kwargs: asyncio.sleep(0, result=target_message_id),
    )

    async def fake_record_preempt_history_event(
        *,
        state,  # noqa: ANN001, ARG001
        user_id,  # noqa: ANN001, ARG001
        event,  # noqa: ANN001
    ) -> None:
        recorded_events.append(dict(event))

    monkeypatch.setattr(
        invoke_route_runner,
        "_record_preempt_history_event",
        fake_record_preempt_history_event,
    )

    payload_normal = A2AAgentInvokeRequest.model_validate(
        {
            "query": "q1",
            "conversationId": str(uuid4()),
            "metadata": {},
        }
    )
    await invoke_route_runner._preempt_previous_invoke_if_requested(  # noqa: SLF001
        state=state,
        payload=payload_normal,
        user_id=uuid4(),
    )
    assert called == []
    assert recorded_events == []

    payload_interrupt = A2AAgentInvokeRequest.model_validate(
        {
            "query": "q2",
            "conversationId": str(uuid4()),
            "metadata": {"extensions": {"interrupt": True}},
        }
    )
    await invoke_route_runner._preempt_previous_invoke_if_requested(  # noqa: SLF001
        state=state,
        payload=payload_interrupt,
        user_id=uuid4(),
    )
    assert called == ["invoke_interrupt"]
    assert recorded_events == [
        {
            "reason": "invoke_interrupt",
            "source": "user",
            "target_message_id": target_message_id,
            "replacement_user_message_id": state.user_message_id,
            "replacement_agent_message_id": state.agent_message_id,
        },
        {
            "reason": "invoke_interrupt",
            "status": "completed",
            "source": "user",
            "target_message_id": target_message_id,
            "replacement_user_message_id": state.user_message_id,
            "replacement_agent_message_id": state.agent_message_id,
            "target_task_ids": ["task-preempt-1"],
            "failed_error_codes": [],
        },
    ]


@pytest.mark.asyncio
async def test_run_http_invoke_append_returns_ack_with_resolved_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_finalize_outbound_invoke_payload(**kwargs):  # noqa: ARG001
        return kwargs["payload"]

    async def fake_append_session_control(**kwargs):  # noqa: ARG001
        return SimpleNamespace(
            success=True,
            result={"ok": True, "session_id": "ses-upstream-next"},
            error_code=None,
            source="upstream_a2a",
            jsonrpc_code=None,
            missing_params=None,
            upstream_error=None,
        )

    monkeypatch.setattr(
        invoke_route_runner,
        "_finalize_outbound_invoke_payload",
        fake_finalize_outbound_invoke_payload,
    )
    monkeypatch.setattr(
        invoke_route_runner.get_a2a_extensions_service(),
        "append_session_control",
        fake_append_session_control,
    )

    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "append this",
            "conversationId": str(uuid4()),
            "userMessageId": str(uuid4()),
            "sessionBinding": {
                "provider": "opencode",
                "externalSessionId": "ses-upstream-current",
            },
            "sessionControl": {"intent": "append"},
            "metadata": {"locale": "zh-CN"},
        }
    )

    response = await invoke_route_runner.run_http_invoke(
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="personal",
        payload=payload,
        stream=False,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={},
    )

    assert response.success is True
    assert response.source == "hub_session_control"
    assert response.session_control is not None
    assert response.session_control.intent == "append"
    assert response.session_control.status == "accepted"
    assert response.session_control.session_id == "ses-upstream-next"


@pytest.mark.asyncio
async def test_run_http_invoke_append_requires_bound_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_finalize_outbound_invoke_payload(**kwargs):  # noqa: ARG001
        return kwargs["payload"]

    monkeypatch.setattr(
        invoke_route_runner,
        "_finalize_outbound_invoke_payload",
        fake_finalize_outbound_invoke_payload,
    )

    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "append this",
            "conversationId": str(uuid4()),
            "sessionControl": {"intent": "append"},
            "metadata": {},
        }
    )

    response = await invoke_route_runner.run_http_invoke(
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="personal",
        payload=payload,
        stream=False,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={},
    )

    assert response.success is False
    assert response.error_code == "append_requires_bound_session"
    assert response.session_control is not None
    assert response.session_control.intent == "append"
    assert response.session_control.status == "unavailable"


@pytest.mark.asyncio
async def test_run_http_invoke_append_turn_forbidden_returns_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_finalize_outbound_invoke_payload(**kwargs):  # noqa: ARG001
        return kwargs["payload"]

    async def fake_append_session_control(**kwargs):  # noqa: ARG001
        return SimpleNamespace(
            success=False,
            result=None,
            error_code="turn_forbidden",
            source="upstream_a2a",
            jsonrpc_code=-32013,
            missing_params=None,
            upstream_error={"message": "Turn does not belong to caller"},
        )

    monkeypatch.setattr(
        invoke_route_runner,
        "_finalize_outbound_invoke_payload",
        fake_finalize_outbound_invoke_payload,
    )
    monkeypatch.setattr(
        invoke_route_runner.get_a2a_extensions_service(),
        "append_session_control",
        fake_append_session_control,
    )

    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "append this",
            "conversationId": str(uuid4()),
            "userMessageId": str(uuid4()),
            "sessionBinding": {
                "provider": "codex",
                "externalSessionId": "ses-upstream-current",
            },
            "sessionControl": {"intent": "append"},
            "metadata": {
                "shared": {
                    "stream": {
                        "thread_id": "thread-1",
                        "turn_id": "turn-1",
                    }
                }
            },
        }
    )

    response = await invoke_route_runner.run_http_invoke(
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="personal",
        payload=payload,
        stream=False,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={},
    )

    assert response.success is False
    assert response.error_code == "turn_forbidden"
    assert response.error == "Append failed."
    assert response.session_control is not None
    assert response.session_control.intent == "append"
    assert response.session_control.status == "failed"


@pytest.mark.asyncio
async def test_run_http_invoke_preempt_only_returns_completed_session_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_finalize_outbound_invoke_payload(**kwargs):  # noqa: ARG001
        return kwargs["payload"]

    async def fake_find_latest_agent_message_id(**kwargs):  # noqa: ARG001
        return "22222222-2222-4222-8222-222222222222"

    async def fake_preempt_inflight_invoke_report(**kwargs):  # noqa: ARG001
        return SimpleNamespace(
            attempted=True,
            status="completed",
            target_task_ids=["task-preempt-1"],
            failed_error_codes=[],
        )

    recorded_events: list[dict[str, object]] = []

    async def fake_record_preempt_event_by_local_session_id(*args, **kwargs):
        recorded_events.append(kwargs["event"])

    monkeypatch.setattr(
        invoke_route_runner,
        "_finalize_outbound_invoke_payload",
        fake_finalize_outbound_invoke_payload,
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_find_latest_agent_message_id",
        fake_find_latest_agent_message_id,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "preempt_inflight_invoke_report",
        fake_preempt_inflight_invoke_report,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_preempt_event_by_local_session_id",
        fake_record_preempt_event_by_local_session_id,
    )

    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "",
            "conversationId": str(uuid4()),
            "sessionControl": {"intent": "preempt"},
            "metadata": {},
        }
    )

    response = await invoke_route_runner.run_http_invoke(
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="personal",
        payload=payload,
        stream=False,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={},
    )

    assert response.success is True
    assert response.session_control is not None
    assert response.session_control.intent == "preempt"
    assert response.session_control.status == "completed"
    assert recorded_events == [
        {
            "reason": "invoke_interrupt",
            "source": "user",
            "target_message_id": "22222222-2222-4222-8222-222222222222",
            "status": "completed",
            "target_task_ids": ["task-preempt-1"],
            "failed_error_codes": [],
        }
    ]


@pytest.mark.asyncio
async def test_run_http_invoke_preempt_only_returns_no_inflight_when_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_finalize_outbound_invoke_payload(**kwargs):  # noqa: ARG001
        return kwargs["payload"]

    async def fake_find_latest_agent_message_id(**kwargs):  # noqa: ARG001
        return None

    async def fake_preempt_inflight_invoke_report(**kwargs):  # noqa: ARG001
        return SimpleNamespace(
            attempted=False,
            status="none",
            target_task_ids=[],
            failed_error_codes=[],
        )

    monkeypatch.setattr(
        invoke_route_runner,
        "_finalize_outbound_invoke_payload",
        fake_finalize_outbound_invoke_payload,
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_find_latest_agent_message_id",
        fake_find_latest_agent_message_id,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "preempt_inflight_invoke_report",
        fake_preempt_inflight_invoke_report,
    )

    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "",
            "conversationId": str(uuid4()),
            "sessionControl": {"intent": "preempt"},
            "metadata": {},
        }
    )

    response = await invoke_route_runner.run_http_invoke(
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="personal",
        payload=payload,
        stream=False,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={},
    )

    assert response.success is True
    assert response.session_control is not None
    assert response.session_control.intent == "preempt"
    assert response.session_control.status == "no_inflight"
