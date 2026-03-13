from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.integrations.a2a_extensions.service import (
    A2AExtensionsService,
    ExtensionCallResult,
)
from app.integrations.a2a_extensions.shared_contract import (
    SHARED_INTERRUPT_CALLBACK_URI,
    SHARED_SESSION_QUERY_URI,
)
from app.integrations.a2a_extensions.types import (
    JsonRpcInterface,
    PageSizePagination,
    ResolvedExtension,
    ResolvedInterruptCallbackExtension,
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


def test_map_business_error_code_supports_dynamic_declared_codes() -> None:
    ext = _resolved_extension()
    assert (
        A2AExtensionsService._map_business_error_code(  # noqa: SLF001
            {"code": -32005},
            ext,
        )
        == "upstream_payload_error"
    )
    assert (
        A2AExtensionsService._map_business_error_code(  # noqa: SLF001
            {"code": "-32001"},
            ext,
        )
        == "session_not_found"
    )
    assert (
        A2AExtensionsService._map_business_error_code(  # noqa: SLF001
            {"code": -32006},
            ext,
        )
        == "session_forbidden"
    )


def test_map_business_error_code_prefers_error_data_type() -> None:
    ext = _resolved_extension()
    assert (
        A2AExtensionsService._map_business_error_code(  # noqa: SLF001
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
        A2AExtensionsService._map_business_error_code(  # noqa: SLF001
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
        A2AExtensionsService._map_interrupt_business_error_code(  # noqa: SLF001
            {
                "code": -32004,
                "data": {"type": "INTERRUPT_REQUEST_EXPIRED"},
            },
            ext,
        )
        == "interrupt_request_expired"
    )
    assert (
        A2AExtensionsService._map_interrupt_business_error_code(  # noqa: SLF001
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
        return ext, "https://example.com/jsonrpc"

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "get_session_messages"
        assert kwargs["params"]["session_id"] == "ses_123"
        assert kwargs["params"]["offset"] == 0
        assert kwargs["params"]["limit"] == 1
        return ExtensionCallResult(success=True, result={"items": []}, meta={})

    monkeypatch.setattr(service, "_resolve_session_extension", _fake_resolve)
    monkeypatch.setattr(service, "_invoke_session_method", _fake_invoke)

    result = await service.continue_session(
        runtime=runtime,
        session_id="ses_123",
    )

    assert result.success is True
    assert result.result == {
        "contextId": "ses_123",
        "provider": "opencode",
        "metadata": {
            "provider": "opencode",
            "externalSessionId": "ses_123",
            "contextId": "ses_123",
        },
    }
    assert result.meta["provider"] == "opencode"
    assert result.meta["validated"] is True


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
        return ext, "https://example.com/jsonrpc"

    async def _never_invoke(**_kwargs):
        raise AssertionError("Upstream call should be short-circuited")

    monkeypatch.setattr(service, "_resolve_session_extension", _fake_resolve)
    monkeypatch.setattr(service, "_invoke_session_method", _never_invoke)

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

    envelope = A2AExtensionsService._normalize_envelope(  # noqa: SLF001
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

    envelope = A2AExtensionsService._normalize_envelope(  # noqa: SLF001
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
        return ext, "https://example.com/jsonrpc"

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

    monkeypatch.setattr(service, "_resolve_session_extension", _fake_resolve)
    monkeypatch.setattr(service, "_invoke_session_method", _fake_invoke)

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
        return ext, "https://example.com/jsonrpc"

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service, "_resolve_session_extension", _fake_resolve)
    monkeypatch.setattr(service, "_call_with_retry", _unexpected_remote_call)

    result = await service.prompt_session_async(
        runtime=runtime,
        session_id="ses_123",
        request_payload={"parts": [{"type": "text", "text": "continue"}]},
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta == {"extension_uri": SHARED_SESSION_QUERY_URI}


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

    monkeypatch.setattr(service, "_resolve_interrupt_extension", _fake_resolve)
    monkeypatch.setattr(service, "_invoke_interrupt_method", _fake_invoke)

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

    monkeypatch.setattr(service, "_resolve_interrupt_extension", _fake_resolve)
    monkeypatch.setattr(service, "_invoke_interrupt_method", _fake_invoke)

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

    monkeypatch.setattr(service, "_resolve_interrupt_extension", _fake_resolve)
    monkeypatch.setattr(service, "_invoke_interrupt_method", _fake_invoke)

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

    monkeypatch.setattr(service, "_resolve_interrupt_extension", _fake_resolve)
    monkeypatch.setattr(service, "_call_with_retry", _unexpected_remote_call)

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

    monkeypatch.setattr(service, "_resolve_interrupt_extension", _fake_resolve)
    monkeypatch.setattr(service, "_call_with_retry", _unexpected_remote_call)

    result = await service.reply_question_interrupt(
        runtime=runtime,
        request_id="q-1",
        answers=[["yes"], ["no"]],
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta["extension_uri"] == SHARED_INTERRUPT_CALLBACK_URI
