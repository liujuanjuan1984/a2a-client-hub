from __future__ import annotations

import pytest

from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.session_binding import resolve_session_binding
from app.integrations.a2a_extensions.shared_contract import (
    OPENCODE_SHARED_SESSION_BINDING_URI,
    SHARED_SESSION_BINDING_URI,
    SHARED_SESSION_ID_FIELD,
)
from tests.support.a2a import parse_agent_card


def _base_card_payload() -> dict:
    return {
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


def test_resolve_requires_session_binding_extension_present() -> None:
    card = parse_agent_card(_base_card_payload())
    with pytest.raises(A2AExtensionNotSupportedError):
        resolve_session_binding(card)


def test_resolve_extracts_canonical_session_binding_contract() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_BINDING_URI,
            "required": False,
            "params": {
                "provider": "OpenCode",
                "metadata_field": SHARED_SESSION_ID_FIELD,
                "behavior": "prefer_metadata_binding_else_create_session",
                "supported_metadata": ["shared.session.id", "opencode.directory"],
                "provider_private_metadata": ["opencode.directory"],
                "shared_workspace_across_consumers": True,
                "tenant_isolation": "none",
            },
        }
    ]

    card = parse_agent_card(payload)
    resolved = resolve_session_binding(card)

    assert resolved.uri == SHARED_SESSION_BINDING_URI
    assert resolved.provider_key == "opencode"
    assert resolved.metadata_field == SHARED_SESSION_ID_FIELD
    assert resolved.behavior == "prefer_metadata_binding_else_create_session"
    assert resolved.supported_metadata == (
        "shared.session.id",
        "opencode.directory",
    )
    assert resolved.provider_private_fields == ("opencode.directory",)
    assert resolved.shared_workspace_across_consumers is True
    assert resolved.tenant_isolation == "none"


def test_resolve_defaults_provider_to_opencode() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_BINDING_URI,
            "required": False,
            "params": {
                "metadata_field": SHARED_SESSION_ID_FIELD,
                "behavior": "prefer_metadata_binding_else_create_session",
            },
        }
    ]

    resolved = resolve_session_binding(parse_agent_card(payload))
    assert resolved.provider_key == "opencode"


def test_resolve_accepts_opencode_https_session_binding_uri() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": OPENCODE_SHARED_SESSION_BINDING_URI,
            "required": False,
            "params": {
                "metadata_field": SHARED_SESSION_ID_FIELD,
                "behavior": "prefer_metadata_binding_else_create_session",
            },
        }
    ]

    resolved = resolve_session_binding(parse_agent_card(payload))

    assert resolved.uri == OPENCODE_SHARED_SESSION_BINDING_URI


def test_resolve_accepts_current_opencode_session_binding_uri() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": OPENCODE_SHARED_SESSION_BINDING_URI,
            "required": False,
            "params": {
                "metadata_field": SHARED_SESSION_ID_FIELD,
                "behavior": "prefer_metadata_binding_else_create_session",
            },
        }
    ]

    resolved = resolve_session_binding(parse_agent_card(payload))

    assert resolved.uri == OPENCODE_SHARED_SESSION_BINDING_URI


def test_resolve_rejects_legacy_session_binding_uri() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": "urn:shared-a2a:session-binding:v1",
            "required": False,
            "params": {
                "metadata_field": SHARED_SESSION_ID_FIELD,
                "behavior": "prefer_metadata_binding_else_create_session",
            },
        }
    ]

    with pytest.raises(A2AExtensionNotSupportedError):
        resolve_session_binding(parse_agent_card(payload))


def test_resolve_rejects_non_canonical_metadata_field() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_BINDING_URI,
            "required": False,
            "params": {
                "metadata_field": "metadata.externalSessionId",
                "behavior": "prefer_metadata_binding_else_create_session",
            },
        }
    ]

    with pytest.raises(A2AExtensionContractError):
        resolve_session_binding(parse_agent_card(payload))


def test_resolve_rejects_invalid_supported_metadata_shape() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_BINDING_URI,
            "required": False,
            "params": {
                "metadata_field": SHARED_SESSION_ID_FIELD,
                "behavior": "prefer_metadata_binding_else_create_session",
                "supported_metadata": "shared.session.id",
            },
        }
    ]

    with pytest.raises(A2AExtensionContractError):
        resolve_session_binding(parse_agent_card(payload))
