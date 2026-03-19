from __future__ import annotations

import pytest
from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.session_query import resolve_session_query
from app.integrations.a2a_extensions.shared_contract import (
    LEGACY_SHARED_SESSION_QUERY_URI,
    SHARED_SESSION_QUERY_URI,
)
from app.integrations.a2a_extensions.types import ResultEnvelopeMapping


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
        resolve_session_query(card)


def test_resolve_extracts_methods_pagination_provider_and_interface() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "provider": "OpenCode",
                "methods": {
                    "list_sessions": "shared.sessions.list",
                    "get_session_messages": "shared.sessions.messages.list",
                    "prompt_async": "shared.sessions.prompt_async",
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
                        "UPSTREAM_PAYLOAD_ERROR": -32005,
                        "SESSION_FORBIDDEN": -32006,
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
    resolved = resolve_session_query(card)

    assert resolved.uri == SHARED_SESSION_QUERY_URI
    assert resolved.provider == "opencode"
    assert resolved.methods["list_sessions"] == "shared.sessions.list"
    assert resolved.methods["get_session_messages"] == "shared.sessions.messages.list"
    assert resolved.methods["prompt_async"] == "shared.sessions.prompt_async"
    assert resolved.pagination.default_size == 20
    assert resolved.pagination.max_size == 100
    assert resolved.jsonrpc.url == "https://api.example.com/jsonrpc"
    assert resolved.jsonrpc.fallback_used is False
    assert resolved.business_code_map[-32001] == "session_not_found"
    assert resolved.business_code_map[-32005] == "upstream_payload_error"
    assert resolved.business_code_map[-32006] == "session_forbidden"
    assert resolved.pagination.params == ("page", "size")
    assert resolved.pagination.supports_offset is False
    assert resolved.result_envelope == ResultEnvelopeMapping()


def test_resolve_falls_back_to_card_url_when_interface_missing() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "provider": "opencode",
                "methods": {
                    "list_sessions": "shared.sessions.list",
                    "get_session_messages": "shared.sessions.messages.list",
                },
                "pagination": {"mode": "page_size", "default_size": 1, "max_size": 2},
                "errors": {"business_codes": {}},
                "result_envelope": {"raw": True, "items": True, "pagination": True},
            },
        }
    ]
    card = AgentCard.model_validate(payload)
    resolved = resolve_session_query(card)
    assert resolved.jsonrpc.url == "https://example.com"
    assert resolved.jsonrpc.fallback_used is True
    assert resolved.methods["prompt_async"] is None


def test_resolve_rejects_missing_pagination() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "provider": "opencode",
                "methods": {
                    "list_sessions": "shared.sessions.list",
                    "get_session_messages": "shared.sessions.messages.list",
                },
            },
        }
    ]
    card = AgentCard.model_validate(payload)
    with pytest.raises(A2AExtensionContractError):
        resolve_session_query(card)


def test_resolve_accepts_limit_mode_with_default_limit_keys() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "provider": "opencode",
                "methods": {
                    "list_sessions": "shared.sessions.list",
                    "get_session_messages": "shared.sessions.messages.list",
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
    resolved = resolve_session_query(card)
    assert resolved.pagination.mode == "limit"
    assert resolved.pagination.default_size == 20
    assert resolved.pagination.max_size == 100
    assert resolved.pagination.params == ("limit",)
    assert resolved.pagination.supports_offset is False


def test_resolve_accepts_limit_mode_with_offset_param() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "provider": "opencode",
                "methods": {
                    "list_sessions": "shared.sessions.list",
                    "get_session_messages": "shared.sessions.messages.list",
                },
                "pagination": {
                    "mode": "limit",
                    "default_limit": 20,
                    "max_limit": 100,
                    "params": ["limit", "offset"],
                },
                "errors": {"business_codes": {}},
                "result_envelope": {"raw": True, "items": True, "pagination": True},
            },
        }
    ]
    card = AgentCard.model_validate(payload)
    resolved = resolve_session_query(card)
    assert resolved.pagination.params == ("limit", "offset")
    assert resolved.pagination.supports_offset is True


def test_resolve_accepts_result_envelope_field_aliases() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "provider": "opencode",
                "methods": {
                    "list_sessions": "shared.sessions.list",
                    "get_session_messages": "shared.sessions.messages.list",
                },
                "pagination": {
                    "mode": "page_size",
                    "default_size": 20,
                    "max_size": 100,
                },
                "errors": {"business_codes": {}},
                "result_envelope": {
                    "items": "payload.sessions",
                    "pagination": "payload.page_info",
                    "raw": "payload",
                },
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_session_query(card)
    assert resolved.result_envelope == ResultEnvelopeMapping(
        items="payload.sessions",
        pagination="payload.page_info",
        raw="payload",
    )


def test_resolve_accepts_result_envelope_by_method_for_opencode_extension() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "provider": "opencode",
                "methods": {
                    "list_sessions": "opencode.sessions.list",
                    "get_session_messages": "opencode.sessions.messages.list",
                    "prompt_async": "opencode.sessions.prompt_async",
                },
                "pagination": {
                    "mode": "limit",
                    "default_limit": 20,
                    "max_limit": 100,
                    "params": ["limit"],
                },
                "errors": {"business_codes": {}},
                "result_envelope": {
                    "by_method": {
                        "opencode.sessions.list": {
                            "fields": ["items"],
                            "items_field": "items",
                        }
                    }
                },
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_session_query(card)
    assert resolved.result_envelope == ResultEnvelopeMapping()


def test_resolve_rejects_result_envelope_unknown_keys() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "provider": "opencode",
                "methods": {
                    "list_sessions": "shared.sessions.list",
                    "get_session_messages": "shared.sessions.messages.list",
                },
                "pagination": {
                    "mode": "page_size",
                    "default_size": 20,
                    "max_size": 100,
                },
                "errors": {"business_codes": {}},
                "result_envelope": {
                    "items": "payload.sessions",
                    "unknown": "payload.unknown",
                },
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    with pytest.raises(A2AExtensionContractError):
        resolve_session_query(card)


def test_resolve_defaults_provider_to_opencode_when_missing() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "methods": {
                    "list_sessions": "shared.sessions.list",
                    "get_session_messages": "shared.sessions.messages.list",
                },
                "pagination": {
                    "mode": "page_size",
                    "default_size": 20,
                    "max_size": 100,
                },
                "errors": {"business_codes": {}},
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_session_query(card)
    assert resolved.provider == "opencode"


def test_resolve_accepts_legacy_session_query_uri() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": LEGACY_SHARED_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "methods": {
                    "list_sessions": "shared.sessions.list",
                    "get_session_messages": "shared.sessions.messages.list",
                },
                "pagination": {
                    "mode": "page_size",
                    "default_size": 20,
                    "max_size": 100,
                },
                "errors": {"business_codes": {}},
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_session_query(card)
    assert resolved.uri == LEGACY_SHARED_SESSION_QUERY_URI
    assert resolved.provider == "opencode"
