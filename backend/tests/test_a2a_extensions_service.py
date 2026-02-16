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
)


def _resolved_extension(*, metadata_key: str | None) -> ResolvedExtension:
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
        pagination=PageSizePagination(mode="limit", default_size=20, max_size=100),
        business_code_map={
            -32001: "session_not_found",
            -32005: "upstream_payload_error",
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


@pytest.mark.asyncio
async def test_continue_session_uses_dynamic_binding_metadata_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(metadata_key="external_session_key")
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
