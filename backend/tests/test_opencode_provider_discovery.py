from __future__ import annotations

import pytest
from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import (
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.opencode_discovery_service import (
    OpencodeDiscoveryService,
)
from app.integrations.a2a_extensions.opencode_provider_discovery import (
    resolve_opencode_provider_discovery,
)
from app.integrations.a2a_extensions.shared_contract import PROVIDER_DISCOVERY_URI
from app.integrations.a2a_extensions.types import (
    JsonRpcInterface,
    ResolvedProviderDiscoveryExtension,
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


def test_resolve_requires_provider_discovery_extension_present() -> None:
    card = AgentCard.model_validate(_base_card_payload())
    with pytest.raises(A2AExtensionNotSupportedError):
        resolve_opencode_provider_discovery(card)


def test_resolve_extracts_provider_discovery_methods_and_interface() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": PROVIDER_DISCOVERY_URI,
            "required": False,
            "params": {
                "methods": {
                    "list_providers": "opencode.providers.list",
                    "list_models": "opencode.models.list",
                },
                "errors": {
                    "business_codes": {
                        "UPSTREAM_UNREACHABLE": -32002,
                        "UPSTREAM_HTTP_ERROR": -32003,
                    }
                },
            },
        }
    ]
    payload["additionalInterfaces"] = [
        {"transport": "jsonrpc", "url": "https://api.example.com/jsonrpc"}
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_opencode_provider_discovery(card)

    assert resolved.uri == PROVIDER_DISCOVERY_URI
    assert resolved.provider == "opencode"
    assert resolved.methods["list_providers"] == "opencode.providers.list"
    assert resolved.methods["list_models"] == "opencode.models.list"
    assert resolved.business_code_map[-32002] == "upstream_unreachable"
    assert resolved.jsonrpc.url == "https://api.example.com/jsonrpc"
    assert resolved.jsonrpc.fallback_used is False


class _FakeSupport:
    @staticmethod
    def normalize_extension_metadata(metadata):
        return metadata


@pytest.mark.asyncio
async def test_list_model_providers_extracts_provider_private_metadata() -> None:
    service = OpencodeDiscoveryService(_FakeSupport())
    captured: dict = {}
    runtime = object()
    ext = ResolvedProviderDiscoveryExtension(
        uri=PROVIDER_DISCOVERY_URI,
        required=False,
        provider="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://api.example.com/jsonrpc", fallback_used=False
        ),
        methods={"list_providers": "providers.list", "list_models": "models.list"},
        business_code_map={},
    )

    async def fake_resolve_extension(_runtime):
        assert _runtime is runtime
        return ext, ext.jsonrpc.url

    async def fake_invoke_method(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    service.resolve_extension = fake_resolve_extension  # type: ignore[method-assign]
    service.invoke_method = fake_invoke_method  # type: ignore[method-assign]

    result = await service.list_model_providers(
        runtime=runtime,
        session_metadata={
            "shared": {"model": {"providerID": "openai", "modelID": "gpt-5"}},
            "opencode": {"directory": "/workspace"},
        },
    )

    assert result == {"ok": True}
    assert captured["params"] == {"metadata": {"opencode": {"directory": "/workspace"}}}


@pytest.mark.asyncio
async def test_list_models_omits_provider_private_metadata_when_unavailable() -> None:
    service = OpencodeDiscoveryService(_FakeSupport())
    captured: dict = {}
    runtime = object()
    ext = ResolvedProviderDiscoveryExtension(
        uri=PROVIDER_DISCOVERY_URI,
        required=False,
        provider="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://api.example.com/jsonrpc", fallback_used=False
        ),
        methods={"list_providers": "providers.list", "list_models": "models.list"},
        business_code_map={},
    )

    async def fake_resolve_extension(_runtime):
        assert _runtime is runtime
        return ext, ext.jsonrpc.url

    async def fake_invoke_method(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    service.resolve_extension = fake_resolve_extension  # type: ignore[method-assign]
    service.invoke_method = fake_invoke_method  # type: ignore[method-assign]

    result = await service.list_models(
        runtime=runtime,
        provider_id="openai",
        session_metadata={
            "shared": {"model": {"providerID": "openai", "modelID": "gpt-5"}}
        },
    )

    assert result == {"ok": True}
    assert captured["params"] == {"provider_id": "openai"}
