from __future__ import annotations

from tests.invoke.invoke_route_runner_support import (
    A2AAgentInvokeRequest,
    A2AAgentInvokeResponse,
    A2AExtensionNotSupportedError,
    A2AExtensionUpstreamError,
    AgentCard,
    JSONResponse,
    SimpleNamespace,
    WebSocketDisconnect,
    _CancelableCloseWebSocket,
    _NoopWebSocket,
    asyncio,
    inspect,
    invoke_route_runner,
    json,
    pytest,
    route_runner_streaming,
    uuid4,
)


def _session_metadata(
    *,
    provider: str | None = None,
    session_id: str | None = None,
    context_id: str | None = None,
    **extra: object,
) -> dict[str, object]:
    metadata: dict[str, object] = dict(extra)
    if context_id is not None:
        metadata["contextId"] = context_id
    if provider is not None or session_id is not None:
        shared = metadata.get("shared")
        shared_dict = dict(shared) if isinstance(shared, dict) else {}
        session: dict[str, str] = {}
        if session_id is not None:
            session["id"] = session_id
        if provider is not None:
            session["provider"] = provider
        shared_dict["session"] = session
        metadata["shared"] = shared_dict
    return metadata


@pytest.mark.asyncio
async def test_run_http_invoke_route_retries_session_not_found_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    original_conversation_id = str(uuid4())
    rebound_conversation_id = str(uuid4())
    attempts: list[dict[str, object]] = []

    async def fake_run_http_invoke(**kwargs):
        payload = kwargs["payload"]
        attempts.append(
            {
                "conversationId": payload.conversation_id,
                "metadata": dict(payload.metadata or {}),
                "sessionBinding": (
                    payload.session_binding.model_dump(by_alias=True)
                    if payload.session_binding is not None
                    else None
                ),
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
        user_id: object,
        conversation_id: str,
        **__,
    ) -> tuple[dict[str, object], bool]:
        assert conversation_id == original_conversation_id
        return (
            {
                "conversationId": rebound_conversation_id,
                "source": "manual",
                "metadata": _session_metadata(
                    provider="opencode",
                    session_id="upstream-sid-2",
                    context_id="ctx-2",
                ),
            },
            True,
        )

    async def fake_commit_safely(_: object) -> None:
        return None

    async def fake_validate_provider_aware_continue_session(**kwargs):
        return "validated"

    monkeypatch.setattr(invoke_route_runner, "run_http_invoke", fake_run_http_invoke)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "continue_session",
        fake_continue_session,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)
    monkeypatch.setattr(
        invoke_route_runner,
        "_validate_provider_aware_continue_session",
        fake_validate_provider_aware_continue_session,
    )

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
        invoke_log_extra_builder=lambda _req, _runtime: {},
    )

    assert isinstance(response, A2AAgentInvokeResponse)
    assert response.success is True
    assert response.content == "ok"
    assert len(attempts) == 2
    assert attempts[0]["conversationId"] == original_conversation_id
    assert attempts[1]["conversationId"] == rebound_conversation_id
    assert attempts[1]["metadata"] == {}
    assert attempts[1]["sessionBinding"] == {
        "provider": "opencode",
        "externalSessionId": "upstream-sid-2",
    }


@pytest.mark.asyncio
async def test_run_http_invoke_route_retries_once_for_session_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    attempt = 0

    async def fake_run_http_invoke(**kwargs):
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
        user_id: object,
        conversation_id: str,
        **__,
    ) -> tuple[dict[str, object], bool]:
        assert conversation_id
        return (
            {
                "conversationId": conversation_id,
                "source": "manual",
                "metadata": _session_metadata(
                    provider="opencode",
                    session_id="upstream-sid-2",
                    context_id="ctx-2",
                ),
            },
            True,
        )

    async def fake_commit_safely(_: object) -> None:
        return None

    async def fake_validate_provider_aware_continue_session(**kwargs):
        return "validated"

    monkeypatch.setattr(invoke_route_runner, "run_http_invoke", fake_run_http_invoke)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "continue_session",
        fake_continue_session,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)
    monkeypatch.setattr(
        invoke_route_runner,
        "_validate_provider_aware_continue_session",
        fake_validate_provider_aware_continue_session,
    )

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
        invoke_log_extra_builder=lambda _req, _runtime: {},
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 404
    response_payload = json.loads(response.body.decode())
    assert response_payload["detail"]["error_code"] == "session_not_found"
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

    async def fake_prepare_state(**kwargs):
        payload = kwargs["payload"]
        prepare_payloads.append(
            {
                "conversationId": payload.conversation_id,
                "metadata": dict(payload.metadata or {}),
                "sessionBinding": (
                    payload.session_binding.model_dump(by_alias=True)
                    if payload.session_binding is not None
                    else None
                ),
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

    async def fake_stream_ws(*, on_error_metadata=None, **kwargs):
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
        user_id: object,
        conversation_id: str,
        **__,
    ) -> tuple[dict[str, object], bool]:
        assert conversation_id == original_conversation_id
        return (
            {
                "conversationId": rebound_conversation_id,
                "source": "manual",
                "metadata": _session_metadata(
                    provider="opencode",
                    session_id="upstream-sid-2",
                    context_id="ctx-2",
                ),
            },
            True,
        )

    async def fake_commit_safely(_: object) -> None:
        return None

    async def fake_validate_provider_aware_continue_session(**kwargs):
        return "validated"

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
        invoke_route_runner,
        "_validate_provider_aware_continue_session",
        fake_validate_provider_aware_continue_session,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages_by_local_session_id",
        lambda **kwargs: None,
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
            "sessionBinding": None,
        },
        {
            "conversationId": rebound_conversation_id,
            "metadata": {
                "shared": {
                    "session": {
                        "id": "upstream-sid-2",
                        "provider": "opencode",
                    }
                },
            },
            "sessionBinding": None,
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

    async def fake_prepare_state(**kwargs):
        payload = kwargs["payload"]
        prepare_payloads.append(
            {
                "conversationId": payload.conversation_id,
                "metadata": dict(payload.metadata or {}),
                "sessionBinding": (
                    payload.session_binding.model_dump(by_alias=True)
                    if payload.session_binding is not None
                    else None
                ),
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

    async def fake_stream_ws(*, on_error_metadata=None, **kwargs):
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
        user_id: object,
        conversation_id: str,
        **__,
    ) -> tuple[dict[str, object], bool]:
        assert conversation_id == original_conversation_id
        return (
            {
                "conversationId": rebound_conversation_id,
                "source": "manual",
                "metadata": _session_metadata(
                    provider="opencode",
                    session_id="upstream-sid-2",
                    context_id="ctx-2",
                ),
            },
            True,
        )

    async def fake_commit_safely(_: object) -> None:
        return None

    async def fake_validate_provider_aware_continue_session(**kwargs):
        return "validated"

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
        invoke_route_runner,
        "_validate_provider_aware_continue_session",
        fake_validate_provider_aware_continue_session,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages_by_local_session_id",
        lambda **kwargs: None,
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
            "sessionBinding": None,
        },
        {
            "conversationId": rebound_conversation_id,
            "metadata": {
                "shared": {
                    "session": {
                        "id": "upstream-sid-2",
                        "provider": "opencode",
                    }
                },
            },
            "sessionBinding": None,
        },
    ]
    assert stream_calls == 2
    assert observed_error_codes == ["session_not_found", "session_not_found"]
    assert len(error_events) == 1
    assert (
        error_events[0]["data"]["error_code"] == "session_not_found_recovery_exhausted"
    )
    assert sent[-1] == {"event": "stream_end", "data": {}}


@pytest.mark.asyncio
async def test_run_http_invoke_route_aborts_retry_when_provider_aware_recovery_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    attempt = 0

    async def fake_run_http_invoke(**kwargs):
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
        user_id: object,
        conversation_id: str,
        **__,
    ) -> tuple[dict[str, object], bool]:
        assert conversation_id
        return (
            {
                "conversationId": conversation_id,
                "source": "manual",
                "metadata": _session_metadata(
                    provider="opencode",
                    session_id="upstream-sid-2",
                    context_id="ctx-2",
                ),
            },
            True,
        )

    async def fake_commit_safely(_: object) -> None:
        return None

    async def fake_validate_provider_aware_continue_session(**kwargs):
        return "failed"

    monkeypatch.setattr(invoke_route_runner, "run_http_invoke", fake_run_http_invoke)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "continue_session",
        fake_continue_session,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)
    monkeypatch.setattr(
        invoke_route_runner,
        "_validate_provider_aware_continue_session",
        fake_validate_provider_aware_continue_session,
    )

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
        invoke_log_extra_builder=lambda _req, _runtime: {},
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 404
    response_payload = json.loads(response.body.decode())
    assert response_payload["detail"]["error_code"] == "session_not_found"
    assert attempt == 1


@pytest.mark.asyncio
async def test_run_ws_invoke_route_reports_recovery_exhausted_when_provider_aware_recovery_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )

    async def fake_prepare_state(**kwargs):
        return invoke_route_runner._InvokeState(
            local_session_id=uuid4(),
            local_source="manual",
            context_id=None,
            metadata={},
            stream_identity={},
            stream_usage={},
            user_message_id=None,
        )

    async def fake_stream_ws(*, on_error_metadata=None, **kwargs):
        if on_error_metadata:
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
        user_id: object,
        conversation_id: str,
        **__,
    ) -> tuple[dict[str, object], bool]:
        assert conversation_id
        return (
            {
                "conversationId": conversation_id,
                "source": "manual",
                "metadata": _session_metadata(
                    provider="opencode",
                    session_id="upstream-sid-2",
                    context_id="ctx-2",
                ),
            },
            True,
        )

    async def fake_commit_safely(_: object) -> None:
        return None

    async def fake_validate_provider_aware_continue_session(**kwargs):
        return "failed"

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
        invoke_route_runner,
        "_validate_provider_aware_continue_session",
        fake_validate_provider_aware_continue_session,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages_by_local_session_id",
        lambda **kwargs: None,
    )

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "test invoke route",
            "conversationId": str(uuid4()),
            "metadata": {},
        }
    )
    websocket = _NoopWebSocket()

    await invoke_route_runner.run_ws_invoke_with_session_recovery(
        websocket=websocket,
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
    assert len(error_events) == 1
    assert (
        error_events[0]["data"]["error_code"] == "session_not_found_recovery_exhausted"
    )
    assert sent[-1] == {"event": "stream_end", "data": {}}


@pytest.mark.asyncio
async def test_run_ws_invoke_route_invalid_payload_close_is_cancellation_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _CancelableCloseWebSocket(receive_payload={})

    async def _noop_send_ws_error(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        invoke_route_runner.a2a_invoke_service,
        "send_ws_error",
        _noop_send_ws_error,
    )

    task = asyncio.create_task(
        invoke_route_runner.run_ws_invoke_route(
            websocket=websocket,
            db=object(),
            user_id=uuid4(),
            agent_id=uuid4(),
            agent_source="shared",
            gateway=object(),
            runtime_builder=lambda: asyncio.sleep(0),
            runtime_not_found_errors=(RuntimeError,),
            runtime_not_found_message="runtime not found",
            runtime_not_found_code="runtime_not_found",
            runtime_validation_errors=(ValueError,),
            validate_message=lambda _: [],
            logger=SimpleNamespace(
                info=lambda *args, **kwargs: None,
                error=lambda *args, **kwargs: None,
            ),
            invoke_log_message="test invoke ws route",
            invoke_log_extra_builder=lambda _req, _runtime: {},
            unexpected_log_message="unexpected",
        )
    )
    await asyncio.wait_for(websocket.close_started.wait(), timeout=1.0)
    task.cancel()
    websocket.close_released.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1.0)
    assert websocket.close_finished.is_set() is True
    assert websocket.close_codes[0] == 1003


@pytest.mark.asyncio
async def test_run_ws_invoke_route_finally_close_suppresses_secondary_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _CancelableCloseWebSocket(receive_exc=WebSocketDisconnect())

    info_log = SimpleNamespace(calls=0)

    def _info(*_args, **_kwargs) -> None:
        info_log.calls += 1

    task = asyncio.create_task(
        invoke_route_runner.run_ws_invoke_route(
            websocket=websocket,
            db=object(),
            user_id=uuid4(),
            agent_id=uuid4(),
            agent_source="shared",
            gateway=object(),
            runtime_builder=lambda: asyncio.sleep(0),
            runtime_not_found_errors=(RuntimeError,),
            runtime_not_found_message="runtime not found",
            runtime_not_found_code="runtime_not_found",
            runtime_validation_errors=(ValueError,),
            validate_message=lambda _: [],
            logger=SimpleNamespace(
                info=_info,
                error=lambda *args, **kwargs: None,
            ),
            invoke_log_message="test invoke ws route",
            invoke_log_extra_builder=lambda _req, _runtime: {},
            unexpected_log_message="unexpected",
        )
    )
    await asyncio.wait_for(websocket.close_started.wait(), timeout=1.0)
    task.cancel()
    websocket.close_released.set()

    await asyncio.wait_for(task, timeout=1.0)
    assert websocket.close_finished.is_set() is True
    assert info_log.calls >= 1


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
    async def fake_run_http_invoke(**kwargs):
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
            user_id: object,
            conversation_id: str,
            **__,
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
        invoke_log_extra_builder=lambda _req, _runtime: {},
    )
    assert isinstance(response, JSONResponse)
    assert response.status_code == expected_status
    response_payload = json.loads(response.body.decode())
    assert response_payload["detail"]["error_code"] == error_code


@pytest.mark.asyncio
async def test_run_http_invoke_with_session_recovery_skips_binding_resolution_without_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )

    async def fake_run_http_invoke(**kwargs):
        return A2AAgentInvokeResponse(
            success=True,
            content="ok",
            agent_name="Demo Agent",
            agent_url="https://example.com/a2a",
        )

    monkeypatch.setattr(invoke_route_runner, "run_http_invoke", fake_run_http_invoke)

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "test invoke route",
            "conversationId": str(uuid4()),
            "metadata": {},
        }
    )

    response = await invoke_route_runner.run_http_invoke_with_session_recovery(
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
        max_recovery_attempts=1,
    )

    assert response.success is True


@pytest.mark.asyncio
async def test_finalize_outbound_invoke_payload_applies_declared_contract_from_session_binding_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": _session_metadata(
                provider="legacy",
                session_id="legacy-sid",
                locale="zh-CN",
                shared={
                    "session": {
                        "id": "legacy-sid",
                        "provider": "legacy",
                    },
                    "model": {
                        "providerID": "openai",
                        "modelID": "gpt-5",
                    },
                },
            ),
            "sessionBinding": {
                "provider": "OpenCode",
                "externalSessionId": "ses-upstream-1",
            },
        }
    )

    finalized = await invoke_route_runner._finalize_outbound_invoke_payload(
        payload=payload,
        runtime=SimpleNamespace(
            resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
        ),
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={},
    )

    assert finalized.metadata == {
        "locale": "zh-CN",
        "shared": {
            "model": {
                "providerID": "openai",
                "modelID": "gpt-5",
            },
            "session": {
                "id": "ses-upstream-1",
                "provider": "opencode",
            },
        },
    }


@pytest.mark.asyncio
async def test_finalize_outbound_invoke_payload_normalizes_legacy_binding_metadata_for_compat_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": _session_metadata(
                provider="OpenCode",
                session_id="ses-upstream-2",
                locale="zh-CN",
            ),
        }
    )

    finalized = await invoke_route_runner._finalize_outbound_invoke_payload(
        payload=payload,
        runtime=SimpleNamespace(
            resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
        ),
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={},
    )

    assert finalized.metadata == {
        "locale": "zh-CN",
        "shared": {
            "session": {
                "id": "ses-upstream-2",
                "provider": "opencode",
            }
        },
    }
    assert finalized.session_binding is None


@pytest.mark.asyncio
async def test_finalize_outbound_invoke_payload_discards_incomplete_session_binding_and_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[tuple[str, dict[str, object]]] = []

    class _UnsupportedInvokeMetadataService:
        async def resolve_invoke_metadata(self, *, runtime):
            raise A2AExtensionNotSupportedError("Invoke metadata extension not found")

    from app.features.invoke import recovery as invoke_recovery

    async def fake_finalize_outbound_invoke_payload_impl(**kwargs):
        return await invoke_recovery.finalize_outbound_invoke_payload(
            **kwargs,
            extensions_service_getter=lambda: _UnsupportedInvokeMetadataService(),
        )

    monkeypatch.setattr(
        invoke_route_runner,
        "_finalize_outbound_invoke_payload_impl",
        fake_finalize_outbound_invoke_payload_impl,
    )

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {
                "locale": "zh-CN",
            },
            "sessionBinding": {
                "provider": "OpenCode",
            },
        }
    )

    finalized = await invoke_route_runner._finalize_outbound_invoke_payload(
        payload=payload,
        runtime=SimpleNamespace(
            resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
        ),
        logger=SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda message, *, extra: warnings.append((message, extra)),
        ),
        log_extra={"agent_id": "agent-1"},
    )

    assert finalized.metadata == {"locale": "zh-CN"}
    assert finalized.session_binding is None
    assert warnings == [
        (
            "Discarding incomplete session binding intent without external session id",
            {
                "agent_id": "agent-1",
                "session_binding_discarded": True,
                "session_binding_discard_reason": "missing_external_session_id",
                "session_binding_provider": "opencode",
                "session_binding_source": "session_binding_intent",
            },
        )
    ]


@pytest.mark.asyncio
async def test_resolve_session_binding_outbound_mode_warns_on_upstream_failure_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[tuple[str, dict[str, object]]] = []

    class _FailingExtensionsService:
        async def resolve_session_binding(self, *, runtime):
            raise A2AExtensionUpstreamError(
                message="card fetch failed",
                error_code="upstream_unavailable",
            )

    from app.features.invoke import recovery as invoke_recovery

    include_legacy_root = await invoke_recovery.resolve_session_binding_outbound_mode(
        runtime=SimpleNamespace(
            resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
        ),
        logger=SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda message, *, extra: warnings.append((message, extra)),
        ),
        log_extra={"agent_id": "agent-1"},
        extensions_service_getter=lambda: _FailingExtensionsService(),
    )

    assert include_legacy_root is True
    assert warnings == [
        (
            "Session binding capability resolution failed upstream; using compatibility fallback",
            {
                "agent_id": "agent-1",
                "session_binding_resolution_error": "upstream_fetch_failed",
                "session_binding_resolution_detail": "card fetch failed",
                "session_binding_fallback_used": True,
            },
        )
    ]


def test_build_stream_hints_runtime_meta_from_card_warns_once_for_missing_capability() -> (
    None
):
    warnings: list[tuple[str, dict[str, object]]] = []
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(
            name="Demo Agent",
            url="https://example.com/a2a/missing-stream-hints",
            headers={"Authorization": "Bearer token"},
        )
    )
    card = AgentCard.model_validate(
        {
            "name": "example",
            "description": "example",
            "version": "1.0",
            "supportedInterfaces": [
                {
                    "url": "https://example.com/jsonrpc",
                    "protocolBinding": "JSONRPC",
                }
            ],
            "capabilities": {"extensions": []},
            "defaultInputModes": [],
            "defaultOutputModes": [],
            "skills": [{"id": "s1", "name": "s1", "description": "d", "tags": []}],
        }
    )

    meta = route_runner_streaming.build_stream_hints_runtime_meta_from_card(
        runtime=runtime,
        card=card,
        logger=SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda message, *, extra: warnings.append((message, extra)),
        ),
        log_extra={"agent_id": "agent-1"},
    )
    second = route_runner_streaming.build_stream_hints_runtime_meta_from_card(
        runtime=SimpleNamespace(
            resolved=SimpleNamespace(
                name="Demo Agent",
                url="https://example.com/a2a/missing-stream-hints",
                headers={"Authorization": "Bearer token"},
            )
        ),
        card=card,
        logger=SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda message, *, extra: warnings.append((message, extra)),
        ),
        log_extra={"agent_id": "agent-1"},
    )

    assert meta == {
        "stream_hints_declared": False,
        "stream_hints_mode": "compat_fallback",
        "stream_hints_fallback_used": True,
    }
    assert second == meta
    assert warnings == [
        (
            "Stream hints extension not declared; using compatibility fallback",
            {
                "agent_id": "agent-1",
                "stream_hints_fallback_used": True,
            },
        )
    ]


def test_diagnose_stream_hints_contract_gap_warns_once_for_missing_shared_stream() -> (
    None
):
    warnings: list[tuple[str, dict[str, object]]] = []
    state = invoke_route_runner._InvokeState(
        local_session_id=None,
        local_source=None,
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        stream_hints_meta={
            "stream_hints_declared": True,
            "stream_hints_mode": "declared_contract",
            "stream_hints_fallback_used": False,
        },
    )
    event_payload = {
        "message": {
            "messageId": "msg-fallback-1",
            "role": "ROLE_AGENT",
            "parts": [{"text": "hello"}],
        },
    }

    invoke_route_runner._diagnose_stream_hints_contract_gap(
        state=state,
        event_payload=event_payload,
        logger=SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda message, *, extra: warnings.append((message, extra)),
        ),
        log_extra={"agent_id": "agent-1"},
    )
    invoke_route_runner._diagnose_stream_hints_contract_gap(
        state=state,
        event_payload=event_payload,
        logger=SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda message, *, extra: warnings.append((message, extra)),
        ),
        log_extra={"agent_id": "agent-1"},
    )

    assert warnings == [
        (
            "Stream hints declared but artifact updates relied on compatibility fallback for shared.stream",
            {
                "agent_id": "agent-1",
                "stream_hints_mode": "declared_contract",
                "stream_hints_contract_gap": "shared_stream_missing",
            },
        )
    ]


@pytest.mark.asyncio
async def test_run_ws_invoke_with_session_recovery_skips_binding_resolution_without_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    websocket = _NoopWebSocket()

    async def fake_run_ws_invoke(**kwargs):
        return None

    monkeypatch.setattr(invoke_route_runner, "run_ws_invoke", fake_run_ws_invoke)

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "test invoke route",
            "conversationId": str(uuid4()),
            "metadata": {},
        }
    )

    await invoke_route_runner.run_ws_invoke_with_session_recovery(
        websocket=websocket,
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={},
        max_recovery_attempts=1,
    )

    assert [json.loads(item) for item in websocket.sent] == [
        {"event": "stream_end", "data": {}}
    ]
