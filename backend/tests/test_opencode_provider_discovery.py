from __future__ import annotations

import pytest
from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import (
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.opencode_provider_discovery import (
    resolve_opencode_provider_discovery,
)
from app.integrations.a2a_extensions.shared_contract import PROVIDER_DISCOVERY_URI


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
