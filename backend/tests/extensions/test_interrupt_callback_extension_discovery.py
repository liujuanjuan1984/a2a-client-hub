from __future__ import annotations

import pytest
from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import (
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.interrupt_callback import (
    resolve_interrupt_callback,
)
from app.integrations.a2a_extensions.shared_contract import (
    LEGACY_SHARED_INTERRUPT_CALLBACK_URI,
    SHARED_INTERRUPT_CALLBACK_URI,
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


def test_resolve_requires_interrupt_extension_present() -> None:
    payload = _base_card_payload()
    card = AgentCard.model_validate(payload)
    with pytest.raises(A2AExtensionNotSupportedError):
        resolve_interrupt_callback(card)


def test_resolve_extracts_methods_business_codes_and_provider() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_INTERRUPT_CALLBACK_URI,
            "required": False,
            "params": {
                "provider": "OpenCode",
                "methods": {
                    "reply_permission": "shared.permission.reply",
                    "reply_question": "shared.question.reply",
                    "reject_question": "shared.question.reject",
                },
                "errors": {
                    "business_codes": {
                        "INTERRUPT_REQUEST_NOT_FOUND": -32004,
                    }
                },
            },
        }
    ]
    payload["additionalInterfaces"] = [
        {"transport": "jsonrpc", "url": "https://api.example.com/jsonrpc"}
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_interrupt_callback(card)

    assert resolved.provider == "opencode"
    assert resolved.methods["reply_permission"] == "shared.permission.reply"
    assert resolved.methods["reply_question"] == "shared.question.reply"
    assert resolved.methods["reject_question"] == "shared.question.reject"
    assert resolved.business_code_map[-32004] == "interrupt_request_not_found"
    assert resolved.jsonrpc.url == "https://api.example.com/jsonrpc"
    assert resolved.jsonrpc.fallback_used is False


def test_resolve_accepts_missing_interrupt_method_fields() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_INTERRUPT_CALLBACK_URI,
            "required": False,
            "params": {
                "provider": "opencode",
                "methods": {
                    "reply_permission": "shared.permission.reply",
                    "reply_question": "shared.question.reply",
                },
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_interrupt_callback(card)
    assert resolved.methods.get("reply_permission") == "shared.permission.reply"
    assert resolved.methods.get("reject_question") is None


def test_resolve_treats_empty_or_blank_interrupt_method_as_missing() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_INTERRUPT_CALLBACK_URI,
            "required": False,
            "params": {
                "provider": "opencode",
                "methods": {
                    "reply_permission": "   ",
                    "reply_question": "",
                    "reject_question": "\n\t",
                },
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_interrupt_callback(card)
    assert resolved.methods.get("reply_permission") is None
    assert resolved.methods.get("reply_question") is None
    assert resolved.methods.get("reject_question") is None


def test_resolve_defaults_provider_to_opencode_when_missing() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_INTERRUPT_CALLBACK_URI,
            "required": False,
            "params": {
                "methods": {
                    "reply_permission": "shared.permission.reply",
                },
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_interrupt_callback(card)
    assert resolved.provider == "opencode"


def test_resolve_accepts_legacy_interrupt_uri() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": LEGACY_SHARED_INTERRUPT_CALLBACK_URI,
            "required": False,
            "params": {
                "methods": {
                    "reply_permission": "shared.permission.reply",
                },
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_interrupt_callback(card)
    assert resolved.uri == LEGACY_SHARED_INTERRUPT_CALLBACK_URI
    assert resolved.provider == "opencode"
