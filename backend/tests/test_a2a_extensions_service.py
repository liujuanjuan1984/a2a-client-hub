from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.integrations.a2a_extensions.errors import A2AExtensionContractError
from app.integrations.a2a_extensions.service import (
    A2AExtensionsService,
    ExtensionCallResult,
)
from app.integrations.a2a_extensions.session_extension_service import (
    SessionExtensionService,
)
from app.integrations.a2a_extensions.shared_contract import (
    SHARED_INTERRUPT_CALLBACK_URI,
    SHARED_SESSION_BINDING_URI,
    SHARED_SESSION_ID_FIELD,
    SHARED_SESSION_QUERY_URI,
)
from app.integrations.a2a_extensions.shared_support import A2AExtensionSupport
from app.integrations.a2a_extensions.types import (
    JsonRpcInterface,
    PageSizePagination,
    ResolvedExtension,
    ResolvedInterruptCallbackExtension,
    ResultEnvelopeMapping,
)


def _resolved_extension(*, supports_offset: bool = False) -> ResolvedExtension:
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
        },
        business_code_map={},
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

    async def _fake_resolve(_runtime):
        return (
            ext,
            "https://example.com/jsonrpc",
            {
                "session_query_contract_mode": "canonical",
                "session_query_selection_mode": "canonical_parser",
            },
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "get_session_messages"
        assert kwargs["params"]["session_id"] == "ses_123"
        assert kwargs["params"]["offset"] == 0
        assert kwargs["params"]["limit"] == 1
        return ExtensionCallResult(success=True, result={"items": []}, meta={})

    async def _fake_binding_capability(_runtime):
        return None, {
            "session_binding_declared": True,
            "session_binding_uri": SHARED_SESSION_BINDING_URI,
            "session_binding_mode": "declared_contract",
            "session_binding_fallback_used": False,
        }

    monkeypatch.setattr(service._session_extensions, "resolve_extension", _fake_resolve)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _fake_invoke)
    monkeypatch.setattr(
        service._session_extensions,
        "resolve_session_binding_capability",
        _fake_binding_capability,
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

    async def _fake_resolve(_runtime):
        return (
            ext,
            "https://example.com/jsonrpc",
            {
                "session_query_contract_mode": "canonical",
                "session_query_selection_mode": "canonical_parser",
            },
        )

    async def _fake_invoke(**kwargs):
        return ExtensionCallResult(success=True, result={"items": []}, meta={})

    async def _fake_binding_capability(_runtime):
        return None, {
            "session_binding_declared": False,
            "session_binding_mode": "compat_fallback",
            "session_binding_fallback_used": True,
        }

    monkeypatch.setattr(service._session_extensions, "resolve_extension", _fake_resolve)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _fake_invoke)
    monkeypatch.setattr(
        service._session_extensions,
        "resolve_session_binding_capability",
        _fake_binding_capability,
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
async def test_get_session_messages_short_circuits_when_limit_has_no_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(supports_offset=False)
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_resolve(_runtime):
        return (
            ext,
            "https://example.com/jsonrpc",
            {
                "session_query_contract_mode": "canonical",
                "session_query_selection_mode": "canonical_parser",
            },
        )

    async def _never_invoke(**_kwargs):
        raise AssertionError("Upstream call should be short-circuited")

    monkeypatch.setattr(service._session_extensions, "resolve_extension", _fake_resolve)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _never_invoke)

    result = await service.get_session_messages(
        runtime=runtime,
        session_id="ses_123",
        page=2,
        size=20,
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

    async def _fake_resolve(_runtime):
        return (
            ext,
            "https://example.com/jsonrpc",
            {
                "session_query_contract_mode": "canonical",
                "session_query_selection_mode": "canonical_parser",
            },
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

    monkeypatch.setattr(service._session_extensions, "resolve_extension", _fake_resolve)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _fake_invoke)

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

    async def _fake_resolve(_runtime):
        return (
            ext,
            "https://example.com/jsonrpc",
            {
                "session_query_contract_mode": "canonical",
                "session_query_selection_mode": "canonical_parser",
            },
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service._session_extensions, "resolve_extension", _fake_resolve)
    monkeypatch.setattr(service._support, "_call_with_retry", _unexpected_remote_call)

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

    async def _fake_resolve(_runtime):
        return ext, "https://example.com/jsonrpc"

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "reply_permission"
        assert kwargs["params"] == {"request_id": "perm-1", "reply": "once"}
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "request_id": "perm-1"},
            meta={"request_id": "perm-1"},
        )

    monkeypatch.setattr(
        service._interrupt_extensions, "resolve_extension", _fake_resolve
    )
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

    async def _fake_resolve(_runtime):
        return ext, "https://example.com/jsonrpc"

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "reply_permission"
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

    monkeypatch.setattr(
        service._interrupt_extensions, "resolve_extension", _fake_resolve
    )
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

    async def _fake_resolve(_runtime):
        return ext, "https://example.com/jsonrpc"

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "reject_question"
        assert kwargs["params"] == {"request_id": "q-1"}
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "request_id": "q-1"},
            meta={"request_id": "q-1"},
        )

    monkeypatch.setattr(
        service._interrupt_extensions, "resolve_extension", _fake_resolve
    )
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

    async def _fake_resolve(_runtime):
        return _interrupt_extension_fixture(), "https://example.com/jsonrpc"

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(
        service._interrupt_extensions, "resolve_extension", _fake_resolve
    )
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
        },
        business_code_map=ext.business_code_map,
    )

    async def _fake_resolve(_runtime):
        return ext, "https://example.com/jsonrpc"

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(
        service._interrupt_extensions, "resolve_extension", _fake_resolve
    )
    monkeypatch.setattr(service._support, "_call_with_retry", _unexpected_remote_call)

    result = await service.reply_question_interrupt(
        runtime=runtime,
        request_id="q-1",
        answers=[["yes"], ["no"]],
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta["extension_uri"] == SHARED_INTERRUPT_CALLBACK_URI
