from __future__ import annotations

import pytest
from a2a.types import AgentCard

from app.integrations.a2a_extensions.compatibility_profile import (
    resolve_compatibility_profile,
)
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.shared_contract import (
    COMPATIBILITY_PROFILE_URI,
    OPENCODE_COMPATIBILITY_PROFILE_URI,
    OPENCODE_SHARED_SESSION_QUERY_URI,
    SHARED_SESSION_QUERY_URI,
)
from tests.support.a2a import parse_agent_card


def _build_card(*, extension_payload: dict | None) -> AgentCard:
    extensions = [extension_payload] if extension_payload is not None else []
    return parse_agent_card(
        {
            "name": "Example Agent",
            "description": "Example",
            "version": "1.0",
            "supportedInterfaces": [
                {
                    "url": "https://example.com/jsonrpc",
                    "protocolBinding": "JSONRPC",
                }
            ],
            "capabilities": {"extensions": extensions},
            "defaultInputModes": [],
            "defaultOutputModes": [],
            "skills": [{"id": "s1", "name": "s1", "description": "d", "tags": []}],
        }
    )


def test_resolve_compatibility_profile_supports_declared_profile() -> None:
    card = _build_card(
        extension_payload={
            "uri": COMPATIBILITY_PROFILE_URI,
            "required": False,
            "params": {
                "extension_retention": {
                    SHARED_SESSION_QUERY_URI: {
                        "surface": "jsonrpc-extension",
                        "availability": "always",
                        "retention": "stable",
                    }
                },
                "method_retention": {
                    "opencode.sessions.shell": {
                        "surface": "extension",
                        "availability": "disabled",
                        "retention": "deployment-conditional",
                        "extension_uri": SHARED_SESSION_QUERY_URI,
                        "toggle": "A2A_ENABLE_SESSION_SHELL",
                    }
                },
                "service_behaviors": {
                    "classification": "stable-service-semantics",
                    "methods": {"tasks/cancel": {"retention": "stable"}},
                },
                "consumer_guidance": [
                    "Treat opencode.sessions.shell as deployment-conditional."
                ],
            },
        }
    )

    resolved = resolve_compatibility_profile(card)

    assert resolved.uri == COMPATIBILITY_PROFILE_URI
    assert resolved.method_retention["opencode.sessions.shell"].toggle == (
        "A2A_ENABLE_SESSION_SHELL"
    )
    assert resolved.consumer_guidance == (
        "Treat opencode.sessions.shell as deployment-conditional.",
    )


def test_resolve_compatibility_profile_allows_empty_retention_maps() -> None:
    card = _build_card(
        extension_payload={
            "uri": COMPATIBILITY_PROFILE_URI,
            "required": False,
            "params": {
                "extension_retention": {},
                "method_retention": {},
                "service_behaviors": {
                    "classification": "stable-service-semantics",
                    "methods": {"tasks/cancel": {"retention": "stable"}},
                },
                "consumer_guidance": ["Treat opencode.sessions.* as provider-private."],
            },
        }
    )

    resolved = resolve_compatibility_profile(card)

    assert resolved.extension_retention == {}
    assert resolved.method_retention == {}


def test_resolve_compatibility_profile_rejects_non_object_retention_map() -> None:
    card = _build_card(
        extension_payload={
            "uri": COMPATIBILITY_PROFILE_URI,
            "required": False,
            "params": {
                "extension_retention": [],
                "method_retention": {},
                "service_behaviors": {
                    "classification": "stable-service-semantics",
                    "methods": {"tasks/cancel": {"retention": "stable"}},
                },
                "consumer_guidance": ["Treat opencode.sessions.* as provider-private."],
            },
        }
    )

    with pytest.raises(A2AExtensionContractError, match="params.extension_retention"):
        resolve_compatibility_profile(card)


def test_resolve_compatibility_profile_requires_declared_extension() -> None:
    card = _build_card(extension_payload=None)

    with pytest.raises(
        A2AExtensionNotSupportedError,
        match="Compatibility profile extension not found|Agent does not declare any extensions",
    ):
        resolve_compatibility_profile(card)


def test_resolve_compatibility_profile_accepts_https_alias_and_normalizes_known_uris() -> (
    None
):
    card = _build_card(
        extension_payload={
            "uri": OPENCODE_COMPATIBILITY_PROFILE_URI,
            "required": False,
            "params": {
                "extension_retention": {
                    OPENCODE_SHARED_SESSION_QUERY_URI: {
                        "surface": "jsonrpc-extension",
                        "availability": "always",
                        "retention": "stable",
                    }
                },
                "method_retention": {
                    "opencode.sessions.shell": {
                        "surface": "extension",
                        "availability": "disabled",
                        "retention": "deployment-conditional",
                        "extension_uri": OPENCODE_SHARED_SESSION_QUERY_URI,
                    }
                },
                "service_behaviors": {
                    "classification": "stable-service-semantics",
                    "methods": {"tasks/cancel": {"retention": "stable"}},
                },
                "consumer_guidance": ["Prefer extended card when available."],
            },
        }
    )

    resolved = resolve_compatibility_profile(card)

    assert resolved.uri == OPENCODE_COMPATIBILITY_PROFILE_URI
    assert SHARED_SESSION_QUERY_URI in resolved.extension_retention
    assert (
        resolved.method_retention["opencode.sessions.shell"].extension_uri
        == SHARED_SESSION_QUERY_URI
    )
