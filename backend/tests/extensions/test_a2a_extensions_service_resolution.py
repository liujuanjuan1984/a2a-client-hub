from __future__ import annotations

from tests.extensions.a2a_extensions_service_support import (
    INVOKE_METADATA_URI,
    SHARED_INTERRUPT_CALLBACK_URI,
    SHARED_INVOKE_FIELD,
    SHARED_SESSION_BINDING_URI,
    SHARED_SESSION_ID_FIELD,
    SHARED_SESSION_QUERY_URI,
    A2AExtensionContractError,
    A2AExtensionsService,
    A2AExtensionSupport,
    Any,
    ExtensionCallResult,
    JsonRpcInterface,
    ResolvedInterruptCallbackExtension,
    ResultEnvelopeMapping,
    SessionExtensionService,
    SessionListFilterFieldContract,
    SessionListFiltersContract,
    SimpleNamespace,
    _binding_snapshot,
    _capability_snapshot,
    _resolved_extension,
    _session_query_snapshot,
    pytest,
)


@pytest.mark.asyncio
async def test_resolve_session_binding_fetches_card_and_returns_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    fake_card = SimpleNamespace(
        capabilities=SimpleNamespace(
            extensions=[
                SimpleNamespace(
                    uri=SHARED_SESSION_BINDING_URI,
                    required=False,
                    params={
                        "metadata_field": SHARED_SESSION_ID_FIELD,
                        "behavior": "prefer_metadata_binding_else_create_session",
                    },
                )
            ]
        )
    )

    async def _fake_fetch_card(_runtime):
        return fake_card

    monkeypatch.setattr(service._support, "fetch_card", _fake_fetch_card)

    resolved = await service.resolve_session_binding(runtime=runtime)

    assert resolved.uri == SHARED_SESSION_BINDING_URI
    assert resolved.metadata_field == SHARED_SESSION_ID_FIELD
    assert resolved.behavior == "prefer_metadata_binding_else_create_session"


@pytest.mark.asyncio
async def test_resolve_session_binding_uses_cache_for_repeated_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(
            url="https://example.com/.well-known/agent-card.json",
            headers={"Authorization": "Bearer token"},
        )
    )
    fake_card = SimpleNamespace(
        capabilities=SimpleNamespace(
            extensions=[
                SimpleNamespace(
                    uri=SHARED_SESSION_BINDING_URI,
                    required=False,
                    params={
                        "metadata_field": SHARED_SESSION_ID_FIELD,
                        "behavior": "prefer_metadata_binding_else_create_session",
                    },
                )
            ]
        )
    )
    fetch_calls = 0

    async def _fake_fetch_card(_runtime):
        nonlocal fetch_calls
        fetch_calls += 1
        return fake_card

    monkeypatch.setattr(service._support, "fetch_card", _fake_fetch_card)

    first = await service.resolve_session_binding(runtime=runtime)
    second = await service.resolve_session_binding(runtime=runtime)

    assert first == second
    assert fetch_calls == 1


@pytest.mark.asyncio
async def test_resolve_session_binding_refreshes_cache_after_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(
            url="https://example.com/.well-known/agent-card.json",
            headers={},
        )
    )
    fake_card = SimpleNamespace(
        capabilities=SimpleNamespace(
            extensions=[
                SimpleNamespace(
                    uri=SHARED_SESSION_BINDING_URI,
                    required=False,
                    params={
                        "metadata_field": SHARED_SESSION_ID_FIELD,
                        "behavior": "prefer_metadata_binding_else_create_session",
                    },
                )
            ]
        )
    )
    fetch_calls = 0
    current_monotonic = 100.0

    async def _fake_fetch_card(_runtime):
        nonlocal fetch_calls
        fetch_calls += 1
        return fake_card

    def _fake_monotonic():
        return current_monotonic

    monkeypatch.setattr(service._support, "fetch_card", _fake_fetch_card)
    monkeypatch.setattr(
        "app.integrations.a2a_extensions.service.time.monotonic",
        _fake_monotonic,
    )

    await service.resolve_session_binding(runtime=runtime)
    current_monotonic = 500.0
    await service.resolve_session_binding(runtime=runtime)

    assert fetch_calls == 2


@pytest.mark.asyncio
async def test_resolve_invoke_metadata_fetches_card_and_returns_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    fake_card = SimpleNamespace(
        capabilities=SimpleNamespace(
            extensions=[
                SimpleNamespace(
                    uri=INVOKE_METADATA_URI,
                    required=False,
                    params={
                        "metadata_field": SHARED_INVOKE_FIELD,
                        "behavior": "merge_bound_metadata_into_invoke",
                        "applies_to_methods": ["message/send", "message/stream"],
                        "fields": [
                            {"name": "project_id", "required": True},
                            {"name": "channel_id", "required": True},
                        ],
                    },
                )
            ]
        )
    )

    async def _fake_fetch_card(_runtime):
        return fake_card

    monkeypatch.setattr(service._support, "fetch_card", _fake_fetch_card)

    resolved = await service.resolve_invoke_metadata(runtime=runtime)

    assert resolved.uri == INVOKE_METADATA_URI
    assert resolved.metadata_field == SHARED_INVOKE_FIELD
    assert [item.name for item in resolved.fields] == ["project_id", "channel_id"]


def test_map_business_error_code_supports_dynamic_declared_codes() -> None:
    ext = _resolved_extension()
    assert (
        A2AExtensionSupport.map_upstream_error_code(
            error={"code": -32005},
            business_code_map=ext.business_code_map,
        )
        == "upstream_payload_error"
    )
    assert (
        A2AExtensionSupport.map_upstream_error_code(
            error={"code": "-32001"},
            business_code_map=ext.business_code_map,
        )
        == "session_not_found"
    )
    assert (
        A2AExtensionSupport.map_upstream_error_code(
            error={"code": -32006},
            business_code_map=ext.business_code_map,
        )
        == "session_forbidden"
    )


def test_map_business_error_code_prefers_error_data_type() -> None:
    ext = _resolved_extension()
    assert (
        A2AExtensionSupport.map_upstream_error_code(
            error={
                "code": -32001,
                "data": {"type": "METHOD_DISABLED"},
            },
            business_code_map=ext.business_code_map,
        )
        == "method_disabled"
    )
    assert (
        A2AExtensionSupport.map_upstream_error_code(
            error={
                "code": -32003,
                "data": {"type": "UPSTREAM_UNAUTHORIZED"},
            },
            business_code_map=ext.business_code_map,
        )
        == "upstream_unauthorized"
    )


def test_map_business_error_code_maps_jsonrpc_invalid_params() -> None:
    ext = _resolved_extension()
    assert (
        A2AExtensionSupport.map_upstream_error_code(
            error={"code": -32602},
            business_code_map=ext.business_code_map,
        )
        == "invalid_params"
    )


def test_map_interrupt_business_error_code_prefers_error_data_type() -> None:
    ext = ResolvedInterruptCallbackExtension(
        uri=SHARED_INTERRUPT_CALLBACK_URI,
        required=False,
        provider="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={"reply_permission": "shared.permission.reply"},
        business_code_map={-32004: "interrupt_request_not_found"},
    )
    assert (
        A2AExtensionSupport.map_upstream_error_code(
            error={
                "code": -32004,
                "data": {"type": "INTERRUPT_REQUEST_EXPIRED"},
            },
            business_code_map=ext.business_code_map,
        )
        == "interrupt_request_expired"
    )
    assert (
        A2AExtensionSupport.map_upstream_error_code(
            error={
                "code": -32602,
                "data": {"type": "INTERRUPT_TYPE_MISMATCH"},
            },
            business_code_map=ext.business_code_map,
        )
        == "interrupt_type_mismatch"
    )


@pytest.mark.asyncio
async def test_continue_session_returns_canonical_binding_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(supports_offset=True)
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "get_session_messages"
        assert kwargs["params"]["session_id"] == "ses_123"
        assert kwargs["params"]["offset"] == 0
        assert kwargs["params"]["limit"] == 1
        return ExtensionCallResult(success=True, result={"items": []}, meta={})

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(
                status="supported",
                meta={
                    "session_binding_declared": True,
                    "session_binding_uri": SHARED_SESSION_BINDING_URI,
                    "session_binding_mode": "declared_contract",
                    "session_binding_fallback_used": False,
                },
            ),
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _fake_invoke)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.continue_session(
        runtime=runtime,
        session_id="ses_123",
    )

    assert result.success is True
    assert result.result == {
        "contextId": "ses_123",
        "metadata": {
            "contextId": "ses_123",
            "shared": {
                "session": {
                    "id": "ses_123",
                    "provider": "opencode",
                }
            },
        },
    }
    assert result.meta["provider"] == "opencode"
    assert result.meta["validated"] is True
    assert result.meta["session_binding_mode"] == "declared_contract"


@pytest.mark.asyncio
async def test_continue_session_normalizes_binding_metadata_in_fallback_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(supports_offset=True)
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_invoke(**kwargs):
        return ExtensionCallResult(success=True, result={"items": []}, meta={})

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(
                status="unsupported",
                meta={
                    "session_binding_declared": False,
                    "session_binding_mode": "undeclared",
                    "session_binding_fallback_used": False,
                },
            ),
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _fake_invoke)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.continue_session(runtime=runtime, session_id="ses_legacy")

    assert result.success is True
    assert result.result == {
        "contextId": "ses_legacy",
        "metadata": {
            "contextId": "ses_legacy",
            "shared": {
                "session": {
                    "id": "ses_legacy",
                    "provider": "opencode",
                }
            },
        },
    }
    assert result.meta["session_binding_mode"] == "undeclared"


@pytest.mark.asyncio
async def test_continue_session_fetches_card_once_for_query_and_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    fetch_calls = 0
    fake_card = SimpleNamespace(
        supported_interfaces=[
            SimpleNamespace(
                protocol_binding="JSONRPC",
                url="https://example.com/jsonrpc",
            )
        ],
        capabilities=SimpleNamespace(
            extensions=[
                SimpleNamespace(
                    uri=SHARED_SESSION_QUERY_URI,
                    required=False,
                    params={
                        "provider": "opencode",
                        "methods": {
                            "list_sessions": "shared.sessions.list",
                            "get_session_messages": "shared.sessions.messages.list",
                        },
                        "pagination": {
                            "mode": "limit",
                            "default_limit": 20,
                            "max_limit": 100,
                            "params": ["limit", "offset"],
                        },
                        "result_envelope": {
                            "raw": True,
                            "items": True,
                            "pagination": True,
                        },
                    },
                ),
                SimpleNamespace(
                    uri=SHARED_SESSION_BINDING_URI,
                    required=False,
                    params={
                        "provider": "opencode",
                        "metadata_field": SHARED_SESSION_ID_FIELD,
                        "behavior": "prefer_metadata_binding_else_create_session",
                    },
                ),
            ]
        ),
    )

    async def _fake_fetch_card(_runtime):
        nonlocal fetch_calls
        fetch_calls += 1
        return fake_card

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "get_session_messages"
        return ExtensionCallResult(
            success=True,
            result={"items": []},
            meta=dict(kwargs.get("selection_meta") or {}),
        )

    monkeypatch.setattr(service._support, "fetch_card", _fake_fetch_card)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )
    monkeypatch.setattr(service._session_extensions, "invoke_method", _fake_invoke)

    result = await service.continue_session(runtime=runtime, session_id="ses_once")

    assert result.success is True
    assert result.meta["session_binding_mode"] == "declared_contract"
    assert result.meta["session_query_negotiation_mode"] == "declared_contract"
    assert result.meta["session_query_compatibility_hints_applied"] is False
    assert fetch_calls == 1


@pytest.mark.asyncio
async def test_get_session_messages_short_circuits_when_limit_has_no_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(supports_offset=False)
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
        )

    async def _never_invoke(**_kwargs):
        raise AssertionError("Upstream call should be short-circuited")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _never_invoke)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.get_session_messages(
        runtime=runtime,
        session_id="ses_123",
        page=2,
        size=20,
        before=None,
        include_raw=False,
        query=None,
    )

    assert result.success is True
    assert result.result == {
        "items": [],
        "pagination": {"page": 2, "size": 20},
    }
    assert result.meta["session_id"] == "ses_123"
    assert result.meta["short_circuit_reason"] == "limit_without_offset"


@pytest.mark.asyncio
async def test_list_sessions_routes_typed_filters_using_runtime_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(
        supports_offset=True,
        session_list_filters=SessionListFiltersContract(
            directory=SessionListFilterFieldContract(top_level_param="directory"),
            roots=SessionListFilterFieldContract(query_param="roots"),
            start=SessionListFilterFieldContract(query_param="start"),
            search=SessionListFilterFieldContract(top_level_param="search"),
        ),
    )
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    captured_meta_extra: dict[str, Any] | None = None

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "list_sessions"
        assert kwargs["params"]["offset"] == 20
        assert kwargs["params"]["limit"] == 20
        assert kwargs["params"]["directory"] == "services/api"
        assert kwargs["params"]["search"] == "planner"
        assert kwargs["params"]["query"] == {
            "status": "open",
            "roots": True,
            "start": 40,
        }
        nonlocal captured_meta_extra
        captured_meta_extra = kwargs.get("meta_extra")
        return ExtensionCallResult(success=True, result={"items": []}, meta={})

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _fake_invoke)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.list_sessions(
        runtime=runtime,
        page=2,
        size=20,
        query={"status": "open"},
        filters={
            "directory": "services/api",
            "roots": True,
            "start": 40,
            "search": "planner",
        },
        include_raw=False,
    )

    assert result.success is True
    assert captured_meta_extra == {
        "session_list_filters": {
            "directory": "top_level",
            "roots": "query",
            "start": "query",
            "search": "top_level",
        }
    }
    assert result.meta == {}


@pytest.mark.asyncio
async def test_list_sessions_rejects_unsupported_typed_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(supports_offset=True)
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    with pytest.raises(ValueError, match="directory filter is not supported"):
        await service.list_sessions(
            runtime=runtime,
            page=1,
            size=20,
            query=None,
            filters={"directory": "services/api"},
            include_raw=False,
        )


@pytest.mark.asyncio
async def test_list_sessions_rejects_conflicting_filter_and_query_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(
        supports_offset=True,
        session_list_filters=SessionListFiltersContract(
            directory=SessionListFilterFieldContract(top_level_param="directory"),
        ),
    )
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    with pytest.raises(
        ValueError, match="filters.directory conflicts with query.directory"
    ):
        await service.list_sessions(
            runtime=runtime,
            page=1,
            size=20,
            query={"directory": "legacy"},
            filters={"directory": "services/api"},
            include_raw=False,
        )


@pytest.mark.asyncio
async def test_get_session_messages_forwards_before_and_normalizes_page_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(supports_cursor=True)
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "get_session_messages"
        assert kwargs["params"]["before"] == "cursor-1"
        return ExtensionCallResult(
            success=True,
            result={
                "items": [{"id": "msg-1", "role": "assistant"}],
                "pagination": {"page": 1, "size": 20},
                "next_cursor": "cursor-2",
            },
            meta=dict(kwargs.get("selection_meta") or {}),
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _fake_invoke)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.get_session_messages(
        runtime=runtime,
        session_id="ses_123",
        page=1,
        size=20,
        before="cursor-1",
        include_raw=False,
        query=None,
    )

    assert result.success is True
    assert result.result == {
        "items": [{"id": "msg-1", "role": "assistant"}],
        "pagination": {"page": 1, "size": 20},
        "pageInfo": {"hasMoreBefore": True, "nextBefore": "cursor-2"},
    }


@pytest.mark.asyncio
async def test_get_session_messages_rejects_before_when_runtime_lacks_cursor_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)

    with pytest.raises(ValueError, match="before is not supported by this runtime"):
        await service.get_session_messages(
            runtime=runtime,
            session_id="ses_123",
            page=1,
            size=20,
            before="cursor-1",
            include_raw=False,
            query=None,
        )


def test_normalize_envelope_excludes_raw_by_default() -> None:
    result = {
        "items": [{"id": "sess-1"}],
        "pagination": {"page": 1, "size": 20, "total": 1},
        "extra": {"debug": True},
    }

    envelope = SessionExtensionService._normalize_envelope(
        result,
        page=1,
        size=20,
        result_envelope=ResultEnvelopeMapping(),
    )

    assert envelope == {
        "items": [{"id": "sess-1"}],
        "pagination": {"page": 1, "size": 20, "total": 1},
    }


def test_normalize_envelope_includes_raw_when_requested() -> None:
    result = [{"id": "sess-1"}]

    envelope = SessionExtensionService._normalize_envelope(
        result,
        page=1,
        size=20,
        result_envelope=ResultEnvelopeMapping(),
        include_raw=True,
    )

    assert envelope == {
        "items": [{"id": "sess-1"}],
        "pagination": {"page": 1, "size": 20},
        "raw": [{"id": "sess-1"}],
    }


def test_normalize_envelope_uses_result_envelope_aliases() -> None:
    result = {
        "payload": {
            "sessions": [{"id": "sess-1"}],
            "page_info": {"page": 1, "size": 20, "total": 1},
        }
    }

    envelope = SessionExtensionService._normalize_envelope(
        result,
        page=1,
        size=20,
        result_envelope=ResultEnvelopeMapping(
            items="payload.sessions",
            pagination="payload.page_info",
            raw="payload",
        ),
        include_raw=True,
    )

    assert envelope == {
        "items": [{"id": "sess-1"}],
        "pagination": {"page": 1, "size": 20, "total": 1},
        "raw": {
            "sessions": [{"id": "sess-1"}],
            "page_info": {"page": 1, "size": 20, "total": 1},
        },
    }


def test_normalize_envelope_rejects_invalid_result_envelope_items() -> None:
    result = {"payload": {"sessions": "not-a-list"}}

    with pytest.raises(A2AExtensionContractError):
        SessionExtensionService._normalize_envelope(
            result,
            page=1,
            size=20,
            result_envelope=ResultEnvelopeMapping(items="payload.sessions"),
        )


def test_normalize_envelope_does_not_fallback_when_result_envelope_declared() -> None:
    result = {
        "items": [{"id": "sess-1"}],
        "pagination": {"page": 1, "size": 20},
    }

    with pytest.raises(A2AExtensionContractError):
        SessionExtensionService._normalize_envelope(
            result,
            page=1,
            size=20,
            result_envelope=ResultEnvelopeMapping(
                items="payload.sessions",
                pagination="payload.page_info",
            ),
        )


def test_normalize_envelope_rejects_non_object_items_in_result_list() -> None:
    with pytest.raises(A2AExtensionContractError):
        SessionExtensionService._normalize_envelope(
            ["invalid-item"],
            page=1,
            size=20,
            result_envelope=ResultEnvelopeMapping(),
        )
