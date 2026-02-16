from __future__ import annotations

import pytest
from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.opencode_session_query import (
    OPENCODE_SESSION_QUERY_URI,
    resolve_opencode_session_query,
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


def test_resolve_requires_extension_present() -> None:
    payload = _base_card_payload()
    card = AgentCard.model_validate(payload)
    with pytest.raises(A2AExtensionNotSupportedError):
        resolve_opencode_session_query(card)


def test_resolve_extracts_methods_pagination_and_interface() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": OPENCODE_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "methods": {
                    "list_sessions": "opencode.sessions.list",
                    "get_session_messages": "opencode.sessions.messages.list",
                },
                "pagination": {
                    "mode": "page_size",
                    "default_size": 20,
                    "max_size": 100,
                },
                "errors": {
                    "business_codes": {
                        "SESSION_NOT_FOUND": -32001,
                        "UPSTREAM_UNREACHABLE": -32002,
                        "UPSTREAM_HTTP_ERROR": -32003,
                    }
                },
                "result_envelope": {"raw": True, "items": True, "pagination": True},
            },
        }
    ]
    payload["additionalInterfaces"] = [
        {"transport": "jsonrpc", "url": "https://api.example.com/jsonrpc"}
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_opencode_session_query(card)

    assert resolved.uri == OPENCODE_SESSION_QUERY_URI
    assert resolved.methods["list_sessions"] == "opencode.sessions.list"
    assert resolved.methods["get_session_messages"] == "opencode.sessions.messages.list"
    assert resolved.pagination.default_size == 20
    assert resolved.pagination.max_size == 100
    assert resolved.jsonrpc.url == "https://api.example.com/jsonrpc"
    assert resolved.jsonrpc.fallback_used is False
    assert resolved.business_code_map[-32001] == "session_not_found"


def test_resolve_falls_back_to_card_url_when_interface_missing() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": OPENCODE_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "methods": {
                    "list_sessions": "opencode.sessions.list",
                    "get_session_messages": "opencode.sessions.messages.list",
                },
                "pagination": {"mode": "page_size", "default_size": 1, "max_size": 2},
                "errors": {"business_codes": {}},
                "result_envelope": {"raw": True, "items": True, "pagination": True},
            },
        }
    ]
    card = AgentCard.model_validate(payload)
    resolved = resolve_opencode_session_query(card)
    assert resolved.jsonrpc.url == "https://example.com"
    assert resolved.jsonrpc.fallback_used is True


def test_resolve_rejects_missing_pagination() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": OPENCODE_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "methods": {
                    "list_sessions": "opencode.sessions.list",
                    "get_session_messages": "opencode.sessions.messages.list",
                }
            },
        }
    ]
    card = AgentCard.model_validate(payload)
    with pytest.raises(A2AExtensionContractError):
        resolve_opencode_session_query(card)


def test_resolve_accepts_limit_mode_with_default_limit_keys() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": OPENCODE_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "methods": {
                    "list_sessions": "opencode.sessions.list",
                    "get_session_messages": "opencode.sessions.messages.list",
                },
                "pagination": {
                    "mode": "limit",
                    "default_limit": 20,
                    "max_limit": 100,
                },
                "errors": {"business_codes": {}},
                "result_envelope": {"raw": True, "items": True, "pagination": True},
            },
        }
    ]
    card = AgentCard.model_validate(payload)
    resolved = resolve_opencode_session_query(card)
    assert resolved.pagination.mode == "limit"
    assert resolved.pagination.default_size == 20
    assert resolved.pagination.max_size == 100
