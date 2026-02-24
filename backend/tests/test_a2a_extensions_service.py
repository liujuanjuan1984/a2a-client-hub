from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.integrations.a2a_extensions.errors import A2AExtensionContractError
from app.integrations.a2a_extensions.service import (
    A2AExtensionsService,
    ExtensionCallResult,
)
from app.integrations.a2a_extensions.types import (
    JsonRpcInterface,
    PageSizePagination,
    ResolvedExtension,
    ResolvedInterruptCallbackExtension,
)


def _resolved_extension(
    *,
    metadata_key: str | None,
    supports_offset: bool = False,
) -> ResolvedExtension:
    return ResolvedExtension(
        uri="urn:opencode-a2a:opencode-session-query/v1",
        required=False,
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={
            "list_sessions": "opencode.sessions.list",
            "get_session_messages": "opencode.sessions.messages.list",
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
        session_binding_metadata_key=metadata_key,
        result_envelope=None,
    )


def test_map_business_error_code_supports_dynamic_declared_codes() -> None:
    ext = _resolved_extension(metadata_key="opencode_session_id")
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


@pytest.mark.asyncio
async def test_continue_session_uses_dynamic_binding_metadata_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(metadata_key="external_session_key", supports_offset=True)
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

    monkeypatch.setattr(service, "_resolve_opencode_extension", _fake_resolve)
    monkeypatch.setattr(service, "_invoke_opencode_method", _fake_invoke)

    result = await service.opencode_continue_session(
        runtime=runtime,
        session_id="ses_123",
    )

    assert result.success is True
    assert result.result == {
        "contextId": "ses_123",
        "provider": "opencode",
        "metadata": {"external_session_key": "ses_123"},
    }
    assert result.meta["session_binding_metadata_key"] == "external_session_key"


@pytest.mark.asyncio
async def test_continue_session_requires_binding_metadata_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(metadata_key=None)
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_resolve(_runtime):
        return ext, "https://example.com/jsonrpc"

    monkeypatch.setattr(service, "_resolve_opencode_extension", _fake_resolve)

    with pytest.raises(A2AExtensionContractError):
        await service.opencode_continue_session(runtime=runtime, session_id="ses_123")


@pytest.mark.asyncio
async def test_get_session_messages_short_circuits_when_limit_has_no_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(
        metadata_key="external_session_key", supports_offset=False
    )
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_resolve(_runtime):
        return ext, "https://example.com/jsonrpc"

    async def _never_invoke(**_kwargs):
        raise AssertionError("Upstream call should be short-circuited")

    monkeypatch.setattr(service, "_resolve_opencode_extension", _fake_resolve)
    monkeypatch.setattr(service, "_invoke_opencode_method", _never_invoke)

    result = await service.opencode_get_session_messages(
        runtime=runtime,
        session_id="ses_123",
        page=2,
        size=20,
        query=None,
    )

    assert result.success is True
    assert result.result == {
        "raw": [],
        "items": [],
        "pagination": {"page": 2, "size": 20},
    }
    assert result.meta["session_id"] == "ses_123"
    assert result.meta["short_circuit_reason"] == "limit_without_offset"


@pytest.mark.asyncio
async def test_reply_permission_uses_request_id_and_reply_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = SimpleNamespace(
        uri="urn:opencode-a2a:opencode-interrupt-callback/v1",
        jsonrpc=SimpleNamespace(url="https://example.com/jsonrpc", fallback_used=False),
        methods={"reply_permission": "opencode.permission.reply"},
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

    monkeypatch.setattr(service, "_resolve_opencode_interrupt_extension", _fake_resolve)
    monkeypatch.setattr(service, "_invoke_opencode_interrupt_method", _fake_invoke)

    result = await service.opencode_reply_permission(
        runtime=runtime,
        request_id="perm-1",
        reply="once",
    )
    assert result.success is True
    assert result.result == {"ok": True, "request_id": "perm-1"}


@pytest.mark.asyncio
async def test_reply_permission_rejects_invalid_reply_value() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError):
        await service.opencode_reply_permission(
            runtime=runtime,
            request_id="perm-1",
            reply="allow",
        )


@pytest.mark.asyncio
async def test_reject_question_uses_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = SimpleNamespace(
        uri="urn:opencode-a2a:opencode-interrupt-callback/v1",
        jsonrpc=SimpleNamespace(url="https://example.com/jsonrpc", fallback_used=False),
        methods={"reject_question": "opencode.question.reject"},
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

    monkeypatch.setattr(service, "_resolve_opencode_interrupt_extension", _fake_resolve)
    monkeypatch.setattr(service, "_invoke_opencode_interrupt_method", _fake_invoke)

    result = await service.opencode_reject_question(runtime=runtime, request_id="q-1")
    assert result.success is True
    assert result.result == {"ok": True, "request_id": "q-1"}


def _interrupt_ext_fixture() -> ResolvedInterruptCallbackExtension:
    return ResolvedInterruptCallbackExtension(
        uri="urn:opencode-a2a:opencode-interrupt-callback/v1",
        required=False,
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
async def test_reply_permission_returns_method_not_supported_if_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_resolve(_runtime):
        return _interrupt_ext_fixture(), "https://example.com/jsonrpc"

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service, "_resolve_opencode_interrupt_extension", _fake_resolve)
    monkeypatch.setattr(service, "_call_with_retry", _unexpected_remote_call)

    result = await service.opencode_reply_permission(
        runtime=runtime,
        request_id="perm-1",
        reply="once",
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta == {
        "extension_uri": "urn:opencode-a2a:opencode-interrupt-callback/v1"
    }


@pytest.mark.asyncio
async def test_reply_question_returns_method_not_supported_if_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _interrupt_ext_fixture()
    ext = ResolvedInterruptCallbackExtension(
        uri=ext.uri,
        required=ext.required,
        jsonrpc=ext.jsonrpc,
        methods={
            "reply_permission": "opencode.permission.reply",
            "reply_question": None,
            "reject_question": "opencode.question.reject",
        },
        business_code_map=ext.business_code_map,
    )

    async def _fake_resolve(_runtime):
        return ext, "https://example.com/jsonrpc"

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service, "_resolve_opencode_interrupt_extension", _fake_resolve)
    monkeypatch.setattr(service, "_call_with_retry", _unexpected_remote_call)

    result = await service.opencode_reply_question(
        runtime=runtime,
        request_id="q-1",
        answers=[["yes"], ["no"]],
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert (
        result.meta["extension_uri"]
        == "urn:opencode-a2a:opencode-interrupt-callback/v1"
    )
