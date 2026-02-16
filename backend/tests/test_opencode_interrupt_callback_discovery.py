from __future__ import annotations

import pytest
from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import A2AExtensionNotSupportedError
from app.integrations.a2a_extensions.opencode_interrupt_callback import (
    OPENCODE_INTERRUPT_CALLBACK_URI,
    resolve_opencode_interrupt_callback,
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
        resolve_opencode_interrupt_callback(card)


def test_resolve_extracts_methods_and_business_codes() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": OPENCODE_INTERRUPT_CALLBACK_URI,
            "required": False,
            "params": {
                "methods": {
                    "reply_permission": "opencode.permission.reply",
                    "reply_question": "opencode.question.reply",
                    "reject_question": "opencode.question.reject",
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
    resolved = resolve_opencode_interrupt_callback(card)

    assert resolved.methods["reply_permission"] == "opencode.permission.reply"
    assert resolved.methods["reply_question"] == "opencode.question.reply"
    assert resolved.methods["reject_question"] == "opencode.question.reject"
    assert resolved.business_code_map[-32004] == "interrupt_request_not_found"
    assert resolved.jsonrpc.url == "https://api.example.com/jsonrpc"
    assert resolved.jsonrpc.fallback_used is False


def test_resolve_accepts_missing_interrupt_method_fields() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": OPENCODE_INTERRUPT_CALLBACK_URI,
            "required": False,
            "params": {
                "methods": {
                    "reply_permission": "opencode.permission.reply",
                    "reply_question": "opencode.question.reply",
                },
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_opencode_interrupt_callback(card)
    assert resolved.methods.get("reply_permission") == "opencode.permission.reply"
    assert resolved.methods.get("reject_question") is None


def test_resolve_treats_empty_or_blank_interrupt_method_as_missing() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": OPENCODE_INTERRUPT_CALLBACK_URI,
            "required": False,
            "params": {
                "methods": {
                    "reply_permission": "   ",
                    "reply_question": "",
                    "reject_question": "\n\t",
                },
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_opencode_interrupt_callback(card)
    assert resolved.methods.get("reply_permission") is None
    assert resolved.methods.get("reply_question") is None
    assert resolved.methods.get("reject_question") is None
