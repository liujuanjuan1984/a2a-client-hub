from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.integrations.a2a_extensions.errors import A2AExtensionContractError
from app.integrations.a2a_extensions.service import (
    A2AExtensionsService,
    ExtensionCallResult,
    InterruptCallbackCapabilitySnapshot,
    InterruptRecoveryCapabilitySnapshot,
    ModelSelectionCapabilitySnapshot,
    ProviderDiscoveryCapabilitySnapshot,
    ResolvedCapabilitySnapshot,
    SessionBindingCapabilitySnapshot,
    SessionQueryCapabilitySnapshot,
    StreamHintsCapabilitySnapshot,
)
from app.integrations.a2a_extensions.session_extension_service import (
    SessionExtensionService,
)
from app.integrations.a2a_extensions.session_query_runtime_selection import (
    ResolvedSessionQueryRuntimeCapability,
)
from app.integrations.a2a_extensions.shared_contract import (
    INTERRUPT_RECOVERY_URI,
    PROVIDER_DISCOVERY_URI,
    SHARED_INTERRUPT_CALLBACK_URI,
    SHARED_SESSION_BINDING_URI,
    SHARED_SESSION_ID_FIELD,
    SHARED_SESSION_QUERY_URI,
    STREAM_HINTS_URI,
)
from app.integrations.a2a_extensions.shared_support import A2AExtensionSupport
from app.integrations.a2a_extensions.types import (
    JsonRpcInterface,
    MessageCursorPaginationContract,
    PageSizePagination,
    ResolvedExtension,
    ResolvedInterruptCallbackExtension,
    ResolvedInterruptRecoveryExtension,
    ResolvedModelSelectionExtension,
    ResolvedProviderDiscoveryExtension,
    ResolvedSessionControlMethodCapability,
    ResolvedStreamHintsExtension,
    ResultEnvelopeMapping,
    SessionListFilterFieldContract,
    SessionListFiltersContract,
)


def _session_query_snapshot(
    ext: ResolvedExtension,
    *,
    contract_mode: str = "canonical",
    selection_mode: str = "canonical_parser",
) -> SessionQueryCapabilitySnapshot:
    control_methods = {
        "prompt_async": ResolvedSessionControlMethodCapability(
            method=ext.methods.get("prompt_async"),
            declared=bool(ext.methods.get("prompt_async")),
            availability="always" if ext.methods.get("prompt_async") else "unsupported",
        ),
        "command": ResolvedSessionControlMethodCapability(
            method=ext.methods.get("command"),
            declared=bool(ext.methods.get("command")),
            availability="always" if ext.methods.get("command") else "unsupported",
        ),
        "shell": ResolvedSessionControlMethodCapability(
            method=ext.methods.get("shell"),
            declared=bool(ext.methods.get("shell")),
            availability="conditional" if ext.methods.get("shell") else "unsupported",
            enabled_by_default=False if ext.methods.get("shell") else None,
            config_key="A2A_ENABLE_SESSION_SHELL" if ext.methods.get("shell") else None,
        ),
    }
    return SessionQueryCapabilitySnapshot(
        status="supported",
        capability=ResolvedSessionQueryRuntimeCapability(
            ext=ext,
            contract_mode=contract_mode,
            selection_mode=selection_mode,
            control_methods=control_methods,
        ),
    )


def _binding_snapshot(
    *,
    status: str = "supported",
    ext=None,
    error: str | None = None,
    meta: dict | None = None,
) -> SessionBindingCapabilitySnapshot:
    return SessionBindingCapabilitySnapshot(
        status=status,
        ext=ext,
        error=error,
        meta=meta or {},
    )


def _interrupt_snapshot(
    *,
    status: str = "unsupported",
    ext: ResolvedInterruptCallbackExtension | None = None,
    jsonrpc_url: str | None = None,
    error: str | None = None,
) -> InterruptCallbackCapabilitySnapshot:
    return InterruptCallbackCapabilitySnapshot(
        status=status,
        ext=ext,
        jsonrpc_url=jsonrpc_url,
        error=error,
    )


def _provider_discovery_snapshot(
    *,
    status: str = "unsupported",
    ext: ResolvedProviderDiscoveryExtension | None = None,
    jsonrpc_url: str | None = None,
    error: str | None = None,
) -> ProviderDiscoveryCapabilitySnapshot:
    return ProviderDiscoveryCapabilitySnapshot(
        status=status,
        ext=ext,
        jsonrpc_url=jsonrpc_url,
        error=error,
    )


def _interrupt_recovery_snapshot(
    *,
    status: str = "unsupported",
    ext: ResolvedInterruptRecoveryExtension | None = None,
    jsonrpc_url: str | None = None,
    error: str | None = None,
) -> InterruptRecoveryCapabilitySnapshot:
    return InterruptRecoveryCapabilitySnapshot(
        status=status,
        ext=ext,
        jsonrpc_url=jsonrpc_url,
        error=error,
    )


def _model_selection_snapshot(
    *,
    status: str = "unsupported",
    ext: ResolvedModelSelectionExtension | None = None,
    error: str | None = None,
    meta: dict | None = None,
) -> ModelSelectionCapabilitySnapshot:
    return ModelSelectionCapabilitySnapshot(
        status=status,
        ext=ext,
        error=error,
        meta=meta or {},
    )


def _capability_snapshot(
    *,
    session_query: SessionQueryCapabilitySnapshot,
    session_binding: SessionBindingCapabilitySnapshot | None = None,
    interrupt_callback: InterruptCallbackCapabilitySnapshot | None = None,
    interrupt_recovery: InterruptRecoveryCapabilitySnapshot | None = None,
    model_selection: ModelSelectionCapabilitySnapshot | None = None,
    provider_discovery: ProviderDiscoveryCapabilitySnapshot | None = None,
    stream_hints: StreamHintsCapabilitySnapshot | None = None,
) -> ResolvedCapabilitySnapshot:
    return ResolvedCapabilitySnapshot(
        session_query=session_query,
        session_binding=session_binding or _binding_snapshot(status="unsupported"),
        interrupt_callback=interrupt_callback or _interrupt_snapshot(),
        interrupt_recovery=interrupt_recovery or _interrupt_recovery_snapshot(),
        model_selection=model_selection or _model_selection_snapshot(),
        provider_discovery=provider_discovery or _provider_discovery_snapshot(),
        stream_hints=stream_hints
        or StreamHintsCapabilitySnapshot(status="unsupported", meta={}),
    )


def _resolved_extension(
    *,
    supports_offset: bool = False,
    supports_cursor: bool = False,
    session_list_filters: SessionListFiltersContract | None = None,
) -> ResolvedExtension:
    return ResolvedExtension(
        uri=SHARED_SESSION_QUERY_URI,
        required=False,
        provider="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={
            "list_sessions": "shared.sessions.list",
            "get_session_messages": "shared.sessions.messages.list",
            "prompt_async": "shared.sessions.prompt_async",
            "command": "shared.sessions.command",
            "shell": None,
        },
        pagination=PageSizePagination(
            mode="limit",
            default_size=20,
            max_size=100,
            params=("limit", "offset") if supports_offset else ("limit",),
            supports_offset=supports_offset,
        ),
        business_code_map={
            -32001: "session_not_found",
            -32005: "upstream_payload_error",
            -32006: "session_forbidden",
        },
        result_envelope=None,
        message_cursor_pagination=MessageCursorPaginationContract(
            cursor_param="before" if supports_cursor else None,
            result_cursor_field="next_cursor" if supports_cursor else None,
        ),
        session_list_filters=session_list_filters or SessionListFiltersContract(),
    )


def _interrupt_extension_fixture() -> ResolvedInterruptCallbackExtension:
    return ResolvedInterruptCallbackExtension(
        uri=SHARED_INTERRUPT_CALLBACK_URI,
        required=False,
        provider="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={
            "reply_permission": None,
            "reply_question": None,
            "reject_question": None,
            "reply_permissions": None,
            "reply_elicitation": None,
        },
        business_code_map={},
    )


def _provider_discovery_extension_fixture() -> ResolvedProviderDiscoveryExtension:
    return ResolvedProviderDiscoveryExtension(
        uri=PROVIDER_DISCOVERY_URI,
        required=False,
        provider="opencode",
        metadata_namespace="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={
            "list_providers": "providers.list",
            "list_models": "models.list",
        },
        business_code_map={},
    )


def _interrupt_recovery_extension_fixture() -> ResolvedInterruptRecoveryExtension:
    return ResolvedInterruptRecoveryExtension(
        uri=INTERRUPT_RECOVERY_URI,
        required=False,
        provider="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={
            "list_permissions": "opencode.permissions.list",
            "list_questions": "opencode.questions.list",
        },
        business_code_map={},
    )


def _stream_hints_snapshot(
    *,
    status: str = "supported",
    ext: ResolvedStreamHintsExtension | None = None,
    error: str | None = None,
    meta: dict | None = None,
) -> StreamHintsCapabilitySnapshot:
    return StreamHintsCapabilitySnapshot(
        status=status,
        ext=ext,
        error=error,
        meta=meta or {},
    )


def _stream_hints_extension_fixture() -> ResolvedStreamHintsExtension:
    return ResolvedStreamHintsExtension(
        uri=STREAM_HINTS_URI,
        required=False,
        provider="opencode",
        stream_field="metadata.shared.stream",
        usage_field="metadata.shared.usage",
        interrupt_field="metadata.shared.interrupt",
        session_field="metadata.shared.session",
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


def test_map_business_error_code_supports_dynamic_declared_codes() -> None:
    ext = _resolved_extension()
    assert (
        A2AExtensionSupport.map_business_error_code(
            {"code": -32005},
            ext,
        )
        == "upstream_payload_error"
    )
    assert (
        A2AExtensionSupport.map_business_error_code(
            {"code": "-32001"},
            ext,
        )
        == "session_not_found"
    )
    assert (
        A2AExtensionSupport.map_business_error_code(
            {"code": -32006},
            ext,
        )
        == "session_forbidden"
    )


def test_map_business_error_code_prefers_error_data_type() -> None:
    ext = _resolved_extension()
    assert (
        A2AExtensionSupport.map_business_error_code(
            {
                "code": -32001,
                "data": {"type": "METHOD_DISABLED"},
            },
            ext,
        )
        == "method_disabled"
    )
    assert (
        A2AExtensionSupport.map_business_error_code(
            {
                "code": -32003,
                "data": {"type": "UPSTREAM_UNAUTHORIZED"},
            },
            ext,
        )
        == "upstream_unauthorized"
    )


def test_map_business_error_code_maps_jsonrpc_invalid_params() -> None:
    ext = _resolved_extension()
    assert (
        A2AExtensionSupport.map_business_error_code(
            {"code": -32602},
            ext,
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
        A2AExtensionSupport.map_interrupt_business_error_code(
            {
                "code": -32004,
                "data": {"type": "INTERRUPT_REQUEST_EXPIRED"},
            },
            ext,
        )
        == "interrupt_request_expired"
    )
    assert (
        A2AExtensionSupport.map_interrupt_business_error_code(
            {
                "code": -32602,
                "data": {"type": "INTERRUPT_TYPE_MISMATCH"},
            },
            ext,
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
        "provider": "opencode",
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
async def test_continue_session_keeps_legacy_binding_metadata_in_fallback_mode(
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
                    "session_binding_mode": "compat_fallback",
                    "session_binding_fallback_used": True,
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
        "provider": "opencode",
        "metadata": {
            "contextId": "ses_legacy",
            "provider": "opencode",
            "externalSessionId": "ses_legacy",
            "shared": {
                "session": {
                    "id": "ses_legacy",
                    "provider": "opencode",
                }
            },
        },
    }
    assert result.meta["session_binding_mode"] == "compat_fallback"


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
        url="https://example.com/jsonrpc",
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
    assert result.meta["session_query_selection_mode"] == "canonical_parser"
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
        )


@pytest.mark.asyncio
async def test_prompt_session_async_forwards_request_and_metadata(
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

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "prompt_async"
        assert kwargs["params"]["session_id"] == "ses_123"
        assert kwargs["params"]["request"] == {
            "parts": [{"type": "text", "text": "continue"}],
            "noReply": True,
        }
        assert kwargs["params"]["metadata"] == {
            "provider": "opencode",
            "externalSessionId": "ses_123",
        }
        assert kwargs["normalize_envelope"] is False
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "session_id": "ses_123"},
            meta={"session_id": "ses_123"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _fake_invoke)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.prompt_session_async(
        runtime=runtime,
        session_id="ses_123",
        request_payload={
            "parts": [{"type": "text", "text": "continue"}],
            "noReply": True,
        },
        metadata={"provider": "opencode", "externalSessionId": "ses_123"},
    )

    assert result.success is True
    assert result.result == {"ok": True, "session_id": "ses_123"}


@pytest.mark.asyncio
async def test_prompt_session_async_returns_method_not_supported_if_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _resolved_extension()
    ext = ResolvedExtension(
        uri=ext.uri,
        required=ext.required,
        provider=ext.provider,
        jsonrpc=ext.jsonrpc,
        methods={
            "list_sessions": ext.methods["list_sessions"],
            "get_session_messages": ext.methods["get_session_messages"],
            "prompt_async": None,
        },
        pagination=ext.pagination,
        business_code_map=ext.business_code_map,
        result_envelope=ext.result_envelope,
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._support, "_call_with_retry", _unexpected_remote_call)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.prompt_session_async(
        runtime=runtime,
        session_id="ses_123",
        request_payload={"parts": [{"type": "text", "text": "continue"}]},
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta == {
        "extension_uri": SHARED_SESSION_QUERY_URI,
        "session_query_contract_mode": "canonical",
        "session_query_selection_mode": "canonical_parser",
    }


@pytest.mark.asyncio
async def test_prompt_session_async_requires_non_empty_parts() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError):
        await service.prompt_session_async(
            runtime=runtime,
            session_id="ses_123",
            request_payload={"parts": []},
        )


@pytest.mark.asyncio
async def test_prompt_session_async_rejects_non_object_metadata() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError, match="metadata must be an object"):
        await service.prompt_session_async(
            runtime=runtime,
            session_id="ses_123",
            request_payload={"parts": [{"type": "text", "text": "continue"}]},
            metadata=[],
        )


@pytest.mark.asyncio
async def test_command_session_forwards_request_and_metadata(
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

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "command"
        assert kwargs["params"]["session_id"] == "ses_123"
        assert kwargs["params"]["request"] == {
            "command": "/review",
            "arguments": "--quick",
            "parts": [{"type": "text", "text": "Focus on tests"}],
        }
        assert kwargs["params"]["metadata"] == {
            "provider": "opencode",
            "externalSessionId": "ses_123",
        }
        assert kwargs["normalize_envelope"] is False
        return ExtensionCallResult(
            success=True,
            result={"item": {"kind": "message", "messageId": "msg-cmd-1"}},
            meta={"session_id": "ses_123"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _fake_invoke)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.command_session(
        runtime=runtime,
        session_id="ses_123",
        request_payload={
            "command": "/review",
            "arguments": "--quick",
            "parts": [{"type": "text", "text": "Focus on tests"}],
        },
        metadata={"provider": "opencode", "externalSessionId": "ses_123"},
    )

    assert result.success is True
    assert result.result == {"item": {"kind": "message", "messageId": "msg-cmd-1"}}


@pytest.mark.asyncio
async def test_command_session_returns_method_not_supported_if_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _resolved_extension()
    ext = ResolvedExtension(
        uri=ext.uri,
        required=ext.required,
        provider=ext.provider,
        jsonrpc=ext.jsonrpc,
        methods={
            "list_sessions": ext.methods["list_sessions"],
            "get_session_messages": ext.methods["get_session_messages"],
            "prompt_async": ext.methods["prompt_async"],
            "command": None,
            "shell": ext.methods["shell"],
        },
        pagination=ext.pagination,
        business_code_map=ext.business_code_map,
        result_envelope=ext.result_envelope,
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._support, "_call_with_retry", _unexpected_remote_call)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.command_session(
        runtime=runtime,
        session_id="ses_123",
        request_payload={"command": "/review", "arguments": "--quick"},
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta == {
        "extension_uri": SHARED_SESSION_QUERY_URI,
        "session_query_contract_mode": "canonical",
        "session_query_selection_mode": "canonical_parser",
    }


@pytest.mark.asyncio
async def test_command_session_requires_non_empty_command() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError, match="request.command must be a non-empty string"):
        await service.command_session(
            runtime=runtime,
            session_id="ses_123",
            request_payload={"command": "", "arguments": "--quick"},
        )


@pytest.mark.asyncio
async def test_command_session_requires_string_arguments() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError, match="request.arguments must be a string"):
        await service.command_session(
            runtime=runtime,
            session_id="ses_123",
            request_payload={"command": "/review", "arguments": None},
        )


@pytest.mark.asyncio
async def test_command_session_allows_empty_arguments(
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

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "command"
        assert kwargs["params"]["request"] == {
            "command": "/status",
            "arguments": "",
        }
        return ExtensionCallResult(
            success=True,
            result={"item": {"kind": "message", "messageId": "msg-cmd-status-1"}},
            meta={"session_id": "ses_123"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _fake_invoke)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.command_session(
        runtime=runtime,
        session_id="ses_123",
        request_payload={
            "command": "/status",
            "arguments": "",
        },
    )

    assert result.success is True
    assert result.result == {
        "item": {"kind": "message", "messageId": "msg-cmd-status-1"}
    }


@pytest.mark.asyncio
async def test_command_session_rejects_non_object_metadata() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError, match="metadata must be an object"):
        await service.command_session(
            runtime=runtime,
            session_id="ses_123",
            request_payload={"command": "/review", "arguments": "--quick"},
            metadata=[],
        )


@pytest.mark.asyncio
async def test_reply_permission_interrupt_uses_request_id_and_reply_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
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

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "reply_permission"
        assert kwargs["jsonrpc_url"] == "https://example.com/jsonrpc"
        assert kwargs["params"] == {"request_id": "perm-1", "reply": "once"}
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "request_id": "perm-1"},
            meta={"request_id": "perm-1"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._interrupt_extensions, "invoke_method", _fake_invoke)

    result = await service.reply_permission_interrupt(
        runtime=runtime,
        request_id="perm-1",
        reply="once",
    )
    assert result.success is True
    assert result.result == {"ok": True, "request_id": "perm-1"}


@pytest.mark.asyncio
async def test_reply_permission_interrupt_rejects_invalid_reply_value() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError):
        await service.reply_permission_interrupt(
            runtime=runtime,
            request_id="perm-1",
            reply="allow",
        )


@pytest.mark.asyncio
async def test_reply_permission_interrupt_forwards_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
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

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "reply_permission"
        assert kwargs["jsonrpc_url"] == "https://example.com/jsonrpc"
        assert kwargs["params"] == {
            "request_id": "perm-1",
            "reply": "once",
            "metadata": {"provider": "opencode", "requestScope": "shared"},
        }
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "request_id": "perm-1"},
            meta={"request_id": "perm-1"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._interrupt_extensions, "invoke_method", _fake_invoke)

    result = await service.reply_permission_interrupt(
        runtime=runtime,
        request_id="perm-1",
        reply="once",
        metadata={"provider": "opencode", "requestScope": "shared"},
    )
    assert result.success is True


@pytest.mark.asyncio
async def test_reply_permission_interrupt_rejects_non_object_metadata() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError, match="metadata must be an object"):
        await service.reply_permission_interrupt(
            runtime=runtime,
            request_id="perm-1",
            reply="once",
            metadata=[],
        )


@pytest.mark.asyncio
async def test_reject_question_interrupt_uses_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = ResolvedInterruptCallbackExtension(
        uri=SHARED_INTERRUPT_CALLBACK_URI,
        required=False,
        provider="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={"reject_question": "shared.question.reject"},
        business_code_map={-32004: "interrupt_request_not_found"},
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "reject_question"
        assert kwargs["jsonrpc_url"] == "https://example.com/jsonrpc"
        assert kwargs["params"] == {"request_id": "q-1"}
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "request_id": "q-1"},
            meta={"request_id": "q-1"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._interrupt_extensions, "invoke_method", _fake_invoke)

    result = await service.reject_question_interrupt(runtime=runtime, request_id="q-1")
    assert result.success is True
    assert result.result == {"ok": True, "request_id": "q-1"}


@pytest.mark.asyncio
async def test_reply_permission_interrupt_returns_method_not_supported_if_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=_interrupt_extension_fixture(),
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._support, "_call_with_retry", _unexpected_remote_call)

    result = await service.reply_permission_interrupt(
        runtime=runtime,
        request_id="perm-1",
        reply="once",
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta == {"extension_uri": SHARED_INTERRUPT_CALLBACK_URI}


@pytest.mark.asyncio
async def test_reply_question_interrupt_returns_method_not_supported_if_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _interrupt_extension_fixture()
    ext = ResolvedInterruptCallbackExtension(
        uri=ext.uri,
        required=ext.required,
        provider=ext.provider,
        jsonrpc=ext.jsonrpc,
        methods={
            "reply_permission": "shared.permission.reply",
            "reply_question": None,
            "reject_question": "shared.question.reject",
            "reply_permissions": "shared.permissions.reply",
            "reply_elicitation": "shared.elicitation.reply",
        },
        business_code_map=ext.business_code_map,
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._support, "_call_with_retry", _unexpected_remote_call)

    result = await service.reply_question_interrupt(
        runtime=runtime,
        request_id="q-1",
        answers=[["yes"], ["no"]],
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta["extension_uri"] == SHARED_INTERRUPT_CALLBACK_URI


@pytest.mark.asyncio
async def test_reply_permissions_interrupt_uses_request_id_permissions_and_scope_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = ResolvedInterruptCallbackExtension(
        uri=SHARED_INTERRUPT_CALLBACK_URI,
        required=False,
        provider="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={"reply_permissions": "shared.permissions.reply"},
        business_code_map={-32004: "interrupt_request_not_found"},
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "reply_permissions"
        assert kwargs["jsonrpc_url"] == "https://example.com/jsonrpc"
        assert kwargs["params"] == {
            "request_id": "perm-v2-1",
            "permissions": {"fileSystem": {"write": ["/workspace/project"]}},
            "scope": "session",
        }
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "request_id": "perm-v2-1"},
            meta={"request_id": "perm-v2-1"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._interrupt_extensions, "invoke_method", _fake_invoke)

    result = await service.reply_permissions_interrupt(
        runtime=runtime,
        request_id="perm-v2-1",
        permissions={"fileSystem": {"write": ["/workspace/project"]}},
        scope="session",
    )
    assert result.success is True
    assert result.result == {"ok": True, "request_id": "perm-v2-1"}


@pytest.mark.asyncio
async def test_reply_permissions_interrupt_rejects_non_object_permissions() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError, match="permissions must be an object"):
        await service.reply_permissions_interrupt(
            runtime=runtime,
            request_id="perm-v2-1",
            permissions=[],  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_reply_permissions_interrupt_returns_method_not_supported_if_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=_interrupt_extension_fixture(),
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._support, "_call_with_retry", _unexpected_remote_call)

    result = await service.reply_permissions_interrupt(
        runtime=runtime,
        request_id="perm-v2-1",
        permissions={"fileSystem": {"write": ["/workspace/project"]}},
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta == {"extension_uri": SHARED_INTERRUPT_CALLBACK_URI}


@pytest.mark.asyncio
async def test_reply_elicitation_interrupt_uses_request_id_action_and_content_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = ResolvedInterruptCallbackExtension(
        uri=SHARED_INTERRUPT_CALLBACK_URI,
        required=False,
        provider="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={"reply_elicitation": "shared.elicitation.reply"},
        business_code_map={-32004: "interrupt_request_not_found"},
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "reply_elicitation"
        assert kwargs["jsonrpc_url"] == "https://example.com/jsonrpc"
        assert kwargs["params"] == {
            "request_id": "eli-1",
            "action": "accept",
            "content": {"approved": True},
        }
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "request_id": "eli-1"},
            meta={"request_id": "eli-1"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._interrupt_extensions, "invoke_method", _fake_invoke)

    result = await service.reply_elicitation_interrupt(
        runtime=runtime,
        request_id="eli-1",
        action="accept",
        content={"approved": True},
    )
    assert result.success is True
    assert result.result == {"ok": True, "request_id": "eli-1"}


@pytest.mark.asyncio
async def test_reply_elicitation_interrupt_rejects_non_null_content_for_decline() -> (
    None
):
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(
        ValueError, match="content must be null when action is decline or cancel"
    ):
        await service.reply_elicitation_interrupt(
            runtime=runtime,
            request_id="eli-1",
            action="decline",
            content={"approved": False},
        )


@pytest.mark.asyncio
async def test_reply_elicitation_interrupt_returns_method_not_supported_if_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=_interrupt_extension_fixture(),
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._support, "_call_with_retry", _unexpected_remote_call)

    result = await service.reply_elicitation_interrupt(
        runtime=runtime,
        request_id="eli-1",
        action="cancel",
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta == {"extension_uri": SHARED_INTERRUPT_CALLBACK_URI}


@pytest.mark.asyncio
async def test_list_model_providers_uses_resolved_provider_discovery_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _provider_discovery_extension_fixture()

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            provider_discovery=_provider_discovery_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "list_providers"
        assert kwargs["jsonrpc_url"] == "https://example.com/jsonrpc"
        assert kwargs["params"] == {
            "metadata": {"opencode": {"directory": "/workspace"}}
        }
        return ExtensionCallResult(success=True, result={"items": []}, meta={})

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._opencode_discovery, "invoke_method", _fake_invoke)

    result = await service.list_model_providers(
        runtime=runtime,
        session_metadata={"opencode": {"directory": "/workspace"}},
    )

    assert result.success is True
    assert result.result == {"items": []}


@pytest.mark.asyncio
async def test_provider_and_interrupt_share_single_card_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    fetch_calls = 0
    fake_card = SimpleNamespace(
        url="https://example.com",
        additionalInterfaces=[
            SimpleNamespace(transport="jsonrpc", url="https://example.com/jsonrpc")
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
                            "prompt_async": "shared.sessions.prompt_async",
                        },
                        "pagination": {
                            "mode": "limit",
                            "default_limit": 20,
                            "max_limit": 100,
                            "params": ["limit", "offset"],
                        },
                    },
                ),
                SimpleNamespace(
                    uri=PROVIDER_DISCOVERY_URI,
                    required=False,
                    params={
                        "methods": {
                            "list_providers": "providers.list",
                            "list_models": "models.list",
                        }
                    },
                ),
                SimpleNamespace(
                    uri=SHARED_INTERRUPT_CALLBACK_URI,
                    required=False,
                    params={
                        "methods": {
                            "reply_permission": "shared.permission.reply",
                            "reply_question": "shared.question.reply",
                            "reject_question": "shared.question.reject",
                        }
                    },
                ),
            ]
        ),
    )

    async def _fake_fetch_card(_runtime):
        nonlocal fetch_calls
        fetch_calls += 1
        return fake_card

    async def _fake_provider_invoke(**kwargs):
        assert kwargs["method_key"] == "list_providers"
        return ExtensionCallResult(success=True, result={"items": []}, meta={})

    async def _fake_interrupt_invoke(**kwargs):
        assert kwargs["method_key"] == "reply_permission"
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "request_id": "perm-1"},
            meta={"request_id": "perm-1"},
        )

    monkeypatch.setattr(service._support, "fetch_card", _fake_fetch_card)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )
    monkeypatch.setattr(
        service._opencode_discovery, "invoke_method", _fake_provider_invoke
    )
    monkeypatch.setattr(
        service._interrupt_extensions, "invoke_method", _fake_interrupt_invoke
    )

    providers = await service.list_model_providers(runtime=runtime)
    interrupt = await service.reply_permission_interrupt(
        runtime=runtime,
        request_id="perm-1",
        reply="once",
    )

    assert providers.success is True
    assert interrupt.success is True
    assert fetch_calls == 1


@pytest.mark.asyncio
async def test_recover_interrupts_merges_and_filters_by_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(resolved=SimpleNamespace(url="https://example.com"))
    ext = _interrupt_recovery_extension_fixture()
    calls: list[str] = []

    async def _fake_snapshot(*, runtime):
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_recovery=_interrupt_recovery_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        calls.append(kwargs["method_key"])
        if kwargs["method_key"] == "list_permissions":
            return ExtensionCallResult(
                success=True,
                result={
                    "items": [
                        {
                            "request_id": "perm-1",
                            "session_id": "sess-1",
                            "type": "permission",
                            "details": {"permission": "write"},
                            "expires_at": 20,
                        },
                        {
                            "request_id": "perm-2",
                            "session_id": "sess-2",
                            "type": "permission",
                            "details": {"permission": "read"},
                            "expires_at": 25,
                        },
                    ]
                },
                meta={},
            )
        return ExtensionCallResult(
            success=True,
            result={
                "items": [
                    {
                        "request_id": "perm-1",
                        "session_id": "sess-1",
                        "type": "permission",
                        "details": {"permission": "write"},
                        "expires_at": 20,
                    },
                    {
                        "request_id": "q-1",
                        "session_id": "sess-1",
                        "type": "question",
                        "details": {"questions": []},
                        "expires_at": 10,
                    },
                ]
            },
            meta={},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._interrupt_recovery, "invoke_method", _fake_invoke)

    result = await service.recover_interrupts(runtime=runtime, session_id="sess-1")

    assert result.success is True
    assert calls == ["list_permissions", "list_questions"]
    assert result.result == {
        "items": [
            {
                "request_id": "q-1",
                "session_id": "sess-1",
                "type": "question",
                "details": {"questions": []},
                "expires_at": 10,
            },
            {
                "request_id": "perm-1",
                "session_id": "sess-1",
                "type": "permission",
                "details": {"permission": "write"},
                "expires_at": 20,
            },
        ]
    }


@pytest.mark.asyncio
async def test_recover_interrupts_returns_method_not_supported_when_upstream_missing_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(resolved=SimpleNamespace(url="https://example.com"))
    ext = ResolvedInterruptRecoveryExtension(
        uri=INTERRUPT_RECOVERY_URI,
        required=False,
        provider="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={
            "list_permissions": "opencode.permissions.list",
            "list_questions": None,
        },
        business_code_map={},
    )

    async def _fake_snapshot(*, runtime):
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_recovery=_interrupt_recovery_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        if kwargs["method_key"] == "list_permissions":
            return ExtensionCallResult(success=True, result={"items": []}, meta={})
        assert kwargs["method_key"] == "list_questions"
        return ExtensionCallResult(
            success=False,
            error_code="method_not_supported",
            upstream_error={"message": "Method list_questions is not supported"},
            meta={},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._interrupt_recovery, "invoke_method", _fake_invoke)

    result = await service.recover_interrupts(runtime=runtime, session_id="sess-1")

    assert result.success is False
    assert result.error_code == "method_not_supported"
