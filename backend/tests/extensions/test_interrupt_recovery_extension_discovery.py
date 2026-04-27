from __future__ import annotations

import pytest
from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import (
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.interrupt_recovery import (
    resolve_interrupt_recovery,
)
from app.integrations.a2a_extensions.shared_contract import (
    CODEX_INTERRUPT_RECOVERY_URI,
    INTERRUPT_RECOVERY_URI,
    OPENCODE_INTERRUPT_RECOVERY_URI,
)


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


def test_resolve_requires_interrupt_recovery_extension_present() -> None:
    payload = _base_card_payload()
    card = AgentCard.model_validate(payload)
    with pytest.raises(A2AExtensionNotSupportedError):
        resolve_interrupt_recovery(card)


def test_resolve_extracts_interrupt_recovery_methods_and_provider() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": INTERRUPT_RECOVERY_URI,
            "required": False,
            "params": {
                "provider": "OpenCode",
                "methods": {
                    "list_permissions": "opencode.permissions.list",
                    "list_questions": "opencode.questions.list",
                },
                "errors": {
                    "business_codes": {
                        "INTERRUPT_QUERY_FORBIDDEN": -32011,
                    }
                },
            },
        }
    ]
    payload["supportedInterfaces"] = [
        {"url": "https://api.example.com/jsonrpc", "protocolBinding": "JSONRPC"}
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_interrupt_recovery(card)

    assert resolved.provider == "opencode"
    assert resolved.methods["list_permissions"] == "opencode.permissions.list"
    assert resolved.methods["list_questions"] == "opencode.questions.list"
    assert resolved.business_code_map[-32011] == "interrupt_query_forbidden"
    assert resolved.jsonrpc.url == "https://api.example.com/jsonrpc"
    assert resolved.jsonrpc.fallback_used is False


def test_resolve_defaults_provider_to_opencode_when_missing() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": INTERRUPT_RECOVERY_URI,
            "required": False,
            "params": {
                "methods": {
                    "list_permissions": "opencode.permissions.list",
                    "list_questions": "opencode.questions.list",
                },
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_interrupt_recovery(card)
    assert resolved.provider == "opencode"


def test_resolve_accepts_opencode_https_interrupt_recovery_uri() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": OPENCODE_INTERRUPT_RECOVERY_URI,
            "required": False,
            "params": {
                "methods": {
                    "list_permissions": "opencode.permissions.list",
                    "list_questions": "opencode.questions.list",
                },
            },
        }
    ]

    resolved = resolve_interrupt_recovery(AgentCard.model_validate(payload))

    assert resolved.uri == OPENCODE_INTERRUPT_RECOVERY_URI
    assert resolved.methods["list_permissions"] == "opencode.permissions.list"


def test_resolve_treats_blank_interrupt_recovery_methods_as_missing() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": INTERRUPT_RECOVERY_URI,
            "required": False,
            "params": {
                "methods": {
                    "list_permissions": "   ",
                    "list_questions": "",
                },
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_interrupt_recovery(card)
    assert resolved.methods["list"] is None
    assert resolved.methods["list_permissions"] is None
    assert resolved.methods["list_questions"] is None


def test_resolve_accepts_codex_interrupt_recovery_single_list_method() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": CODEX_INTERRUPT_RECOVERY_URI,
            "required": False,
            "params": {
                "methods": {
                    "list": "codex.interrupts.list",
                },
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_interrupt_recovery(card)

    assert resolved.uri == CODEX_INTERRUPT_RECOVERY_URI
    assert resolved.provider == "codex"
    assert resolved.methods["list"] == "codex.interrupts.list"
    assert resolved.methods["list_permissions"] is None
    assert resolved.methods["list_questions"] is None
