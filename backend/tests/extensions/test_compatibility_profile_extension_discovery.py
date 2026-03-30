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


def _build_card(*, extension_payload: dict | None) -> AgentCard:
    extensions = [extension_payload] if extension_payload is not None else []
    return AgentCard.model_validate(
        {
            "name": "Example Agent",
            "description": "Example",
            "url": "https://example.com",
            "version": "1.0",
            "capabilities": {"extensions": extensions},
            "defaultInputModes": [],
            "defaultOutputModes": [],
            "skills": [{"id": "s1", "name": "s1", "description": "d", "tags": []}],
        }
    )


def test_resolve_compatibility_profile_supports_declared_profile() -> None:
    card = _build_card(
        extension_payload={
            "uri": "urn:a2a:compatibility-profile/v1",
            "required": False,
            "params": {
                "extension_retention": {
                    "urn:opencode-a2a:session-query/v1": {
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
                        "extension_uri": "urn:opencode-a2a:session-query/v1",
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

    assert resolved.uri == "urn:a2a:compatibility-profile/v1"
    assert resolved.method_retention["opencode.sessions.shell"].toggle == (
        "A2A_ENABLE_SESSION_SHELL"
    )
    assert resolved.consumer_guidance == (
        "Treat opencode.sessions.shell as deployment-conditional.",
    )


def test_resolve_compatibility_profile_rejects_invalid_retention_map() -> None:
    card = _build_card(
        extension_payload={
            "uri": "urn:a2a:compatibility-profile/v1",
            "required": False,
            "params": {
                "extension_retention": {},
                "method_retention": {
                    "opencode.sessions.command": {
                        "surface": "extension",
                        "availability": "always",
                        "retention": "stable",
                    }
                },
                "service_behaviors": {
                    "classification": "stable-service-semantics",
                    "methods": {"tasks/cancel": {"retention": "stable"}},
                },
                "consumer_guidance": ["Treat opencode.sessions.* as provider-private."],
            },
        }
    )

    with pytest.raises(
        A2AExtensionContractError,
        match="params.extension_retention",
    ):
        resolve_compatibility_profile(card)


def test_resolve_compatibility_profile_requires_declared_extension() -> None:
    card = _build_card(extension_payload=None)

    with pytest.raises(
        A2AExtensionNotSupportedError,
        match="Compatibility profile extension not found|Agent does not declare any extensions",
    ):
        resolve_compatibility_profile(card)
