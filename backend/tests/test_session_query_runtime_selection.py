from __future__ import annotations

from types import SimpleNamespace

import pytest
from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.service import (
    A2AExtensionsService,
)
from app.integrations.a2a_extensions.session_query_runtime_selection import (
    resolve_runtime_session_query,
)
from app.integrations.a2a_extensions.shared_contract import (
    LEGACY_SHARED_SESSION_QUERY_URI,
    SHARED_SESSION_BINDING_URI,
    SHARED_SESSION_ID_FIELD,
    SHARED_SESSION_QUERY_URI,
)


def _base_card_payload() -> dict:
    return {
        "name": "example",
        "description": "example",
        "url": "https://example.com",
        "version": "1.0",
        "capabilities": {"extensions": []},
        "defaultInputModes": [],
        "defaultOutputModes": [],
        "skills": [{"id": "s1", "name": "s1", "description": "d", "tags": []}],
    }


def _build_card(
    *,
    uri: str = SHARED_SESSION_QUERY_URI,
    pagination: dict | None = None,
    with_binding: bool = False,
) -> AgentCard:
    payload = _base_card_payload()
    extensions = [
        {
            "uri": uri,
            "params": {
                "provider": "opencode",
                "methods": {
                    "list_sessions": "shared.sessions.list",
                    "get_session_messages": "shared.sessions.messages.list",
                },
                "pagination": pagination
                or {
                    "mode": "page_size",
                    "default_size": 20,
                    "max_size": 100,
                },
                "result_envelope": {"raw": True, "items": True, "pagination": True},
            },
        }
    ]
    if with_binding:
        extensions.append(
            {
                "uri": SHARED_SESSION_BINDING_URI,
                "params": {
                    "provider": "opencode",
                    "metadata_field": SHARED_SESSION_ID_FIELD,
                    "behavior": "prefer_metadata_binding_else_create_session",
                },
            }
        )
    payload["capabilities"]["extensions"] = extensions
    return AgentCard.model_validate(payload)


def test_resolve_runtime_session_query_selects_canonical_parser() -> None:
    capability = resolve_runtime_session_query(_build_card())

    assert capability.contract_mode == "canonical"
    assert capability.selection_mode == "canonical_parser"
    assert capability.ext.uri == SHARED_SESSION_QUERY_URI


def test_resolve_runtime_session_query_selects_legacy_compatibility() -> None:
    capability = resolve_runtime_session_query(
        _build_card(uri=LEGACY_SHARED_SESSION_QUERY_URI)
    )

    assert capability.contract_mode == "legacy"
    assert capability.selection_mode == "legacy_compatibility"
    assert capability.ext.uri == LEGACY_SHARED_SESSION_QUERY_URI


def test_resolve_runtime_session_query_rejects_unsupported_contract() -> None:
    with pytest.raises(A2AExtensionNotSupportedError):
        resolve_runtime_session_query(AgentCard.model_validate(_base_card_payload()))


def test_resolve_runtime_session_query_rejects_invalid_contract() -> None:
    with pytest.raises(A2AExtensionContractError, match="pagination.max_size"):
        resolve_runtime_session_query(
            _build_card(
                pagination={
                    "mode": "page_size",
                    "default_size": 20,
                }
            )
        )


@pytest.mark.asyncio
async def test_resolve_capability_snapshot_uses_runtime_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(
            url="https://example.com/.well-known/agent-card.json",
            headers={"Authorization": "Bearer token"},
        )
    )
    fake_card = _build_card(with_binding=True)
    fetch_calls = 0

    async def _fake_fetch_card(_runtime):
        nonlocal fetch_calls
        fetch_calls += 1
        return fake_card

    monkeypatch.setattr(service._support, "fetch_card", _fake_fetch_card)

    first = await service.resolve_capability_snapshot(runtime=runtime)
    second = await service.resolve_capability_snapshot(runtime=runtime)

    assert first == second
    assert first.session_query.status == "supported"
    assert first.session_query.selection_meta == {
        "session_query_contract_mode": "canonical",
        "session_query_selection_mode": "canonical_parser",
    }
    assert first.session_binding.status == "supported"
    assert fetch_calls == 1


@pytest.mark.asyncio
async def test_resolve_capability_snapshot_caches_unsupported_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    fetch_calls = 0

    async def _fake_fetch_card(_runtime):
        nonlocal fetch_calls
        fetch_calls += 1
        return _build_card()

    monkeypatch.setattr(service._support, "fetch_card", _fake_fetch_card)

    first = await service.resolve_capability_snapshot(runtime=runtime)
    second = await service.resolve_capability_snapshot(runtime=runtime)

    assert first.session_binding.status == "unsupported"
    assert first.session_binding.meta == {
        "session_binding_declared": False,
        "session_binding_mode": "compat_fallback",
        "session_binding_fallback_used": True,
    }
    assert second == first
    assert fetch_calls == 1


@pytest.mark.asyncio
async def test_resolve_capability_snapshot_caches_invalid_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    fetch_calls = 0

    async def _fake_fetch_card(_runtime):
        nonlocal fetch_calls
        fetch_calls += 1
        return _build_card(
            pagination={
                "mode": "page_size",
                "default_size": 20,
            }
        )

    monkeypatch.setattr(service._support, "fetch_card", _fake_fetch_card)

    first = await service.resolve_capability_snapshot(runtime=runtime)
    second = await service.resolve_capability_snapshot(runtime=runtime)

    assert first.session_query.status == "invalid"
    assert "pagination.max_size" in str(first.session_query.error)
    assert second == first
    assert fetch_calls == 1
