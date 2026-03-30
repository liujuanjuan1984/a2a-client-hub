from __future__ import annotations

from a2a.types import AgentCard

from app.integrations.a2a_extensions.session_query_diagnostics import (
    diagnose_session_query,
)
from app.integrations.a2a_extensions.shared_contract import (
    LEGACY_SHARED_SESSION_QUERY_URI,
    SHARED_SESSION_QUERY_URI,
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


def test_diagnose_session_query_returns_canonical_status() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_QUERY_URI,
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
                "result_envelope": {"raw": True, "items": True, "pagination": True},
            },
        }
    ]

    diagnostic = diagnose_session_query(AgentCard.model_validate(payload))

    assert diagnostic.declared is True
    assert diagnostic.status == "canonical"
    assert diagnostic.uses_legacy_uri is False
    assert diagnostic.uses_legacy_contract_fields is False
    assert diagnostic.pagination_mode == "page_size"


def test_diagnose_session_query_returns_legacy_status_for_legacy_uri() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": LEGACY_SHARED_SESSION_QUERY_URI,
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
                "result_envelope": {"raw": True, "items": True, "pagination": True},
            },
        }
    ]

    diagnostic = diagnose_session_query(AgentCard.model_validate(payload))

    assert diagnostic.declared is True
    assert diagnostic.status == "legacy"
    assert diagnostic.uses_legacy_uri is True


def test_diagnose_session_query_returns_legacy_status_for_legacy_limit_fields() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_QUERY_URI,
            "params": {
                "provider": "opencode",
                "methods": {
                    "list_sessions": "shared.sessions.list",
                    "get_session_messages": "shared.sessions.messages.list",
                },
                "pagination": {
                    "mode": "limit",
                    "default_size": 20,
                    "max_size": 100,
                },
                "result_envelope": {"raw": True, "items": True, "pagination": True},
            },
        }
    ]

    diagnostic = diagnose_session_query(AgentCard.model_validate(payload))

    assert diagnostic.declared is True
    assert diagnostic.status == "legacy"
    assert diagnostic.uses_legacy_contract_fields is True
    assert diagnostic.pagination_mode == "limit"


def test_diagnose_session_query_accepts_limit_and_optional_cursor_mode() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_QUERY_URI,
            "params": {
                "provider": "opencode",
                "methods": {
                    "list_sessions": "opencode.sessions.list",
                    "get_session_messages": "opencode.sessions.messages.list",
                },
                "pagination": {
                    "mode": "limit_and_optional_cursor",
                    "default_limit": 20,
                    "max_limit": 100,
                    "params": ["limit", "before"],
                    "cursor_param": "before",
                    "result_cursor_field": "next_cursor",
                    "cursor_applies_to": ["opencode.sessions.messages.list"],
                },
                "result_envelope": {"raw": True, "items": True, "pagination": True},
            },
        }
    ]

    diagnostic = diagnose_session_query(AgentCard.model_validate(payload))

    assert diagnostic.declared is True
    assert diagnostic.status == "canonical"
    assert diagnostic.uses_legacy_contract_fields is False
    assert diagnostic.pagination_mode == "limit_and_optional_cursor"
    assert diagnostic.pagination_params == ["limit", "before"]


def test_diagnose_session_query_returns_unsupported_when_not_declared() -> None:
    diagnostic = diagnose_session_query(AgentCard.model_validate(_base_card_payload()))

    assert diagnostic.declared is False
    assert diagnostic.status == "unsupported"


def test_diagnose_session_query_returns_invalid_for_bad_contract() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": SHARED_SESSION_QUERY_URI,
            "params": {
                "provider": "opencode",
                "methods": {
                    "list_sessions": "shared.sessions.list",
                    "get_session_messages": "shared.sessions.messages.list",
                },
                "pagination": {
                    "mode": "page_size",
                    "default_size": 20,
                },
            },
        }
    ]

    diagnostic = diagnose_session_query(AgentCard.model_validate(payload))

    assert diagnostic.declared is True
    assert diagnostic.status == "invalid"
    assert diagnostic.error is not None
    assert "pagination.max_size" in diagnostic.error
