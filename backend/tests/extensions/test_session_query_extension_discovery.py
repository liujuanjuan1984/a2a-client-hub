from __future__ import annotations

import pytest
from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.session_query import (
    resolve_session_query,
    resolve_session_query_control_methods,
)
from app.integrations.a2a_extensions.shared_contract import (
    CODEX_SHARED_SESSION_QUERY_URI,
    LEGACY_SHARED_SESSION_QUERY_URI,
    OPENCODE_SHARED_SESSION_MANAGEMENT_URI,
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
            "uri": OPENCODE_SHARED_SESSION_MANAGEMENT_URI,
            "required": False,
            "params": {
                "provider": "OpenCode",
                "methods": {
                    "list_sessions": "opencode.sessions.list",
                    "get_session_messages": "opencode.sessions.messages.list",
                    "prompt_async": "opencode.sessions.prompt_async",
                    "command": "opencode.sessions.command",
                },
                "control_method_flags": {
                    "opencode.sessions.shell": {
                        "enabled_by_default": False,
                        "config_key": "A2A_ENABLE_SESSION_SHELL",
                    }
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

    assert resolved.uri == OPENCODE_SHARED_SESSION_MANAGEMENT_URI
    assert resolved.provider == "opencode"
    assert resolved.methods["list_sessions"] == "opencode.sessions.list"
    assert resolved.methods["get_session_messages"] == "opencode.sessions.messages.list"
    assert resolved.methods["prompt_async"] == "opencode.sessions.prompt_async"
    assert resolved.methods["command"] == "opencode.sessions.command"
    assert resolved.methods["shell"] is None
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
    assert resolved.session_list_filters.directory.top_level_param is None
    assert resolved.session_list_filters.directory.query_param is None

    control_methods = resolve_session_query_control_methods(card, ext=resolved)
    assert control_methods["prompt_async"].declared is True
    assert control_methods["prompt_async"].availability == "always"
    assert control_methods["command"].declared is True
    assert control_methods["command"].availability == "always"
    assert control_methods["shell"].declared is False
    assert control_methods["shell"].availability == "conditional"
    assert control_methods["shell"].config_key == "A2A_ENABLE_SESSION_SHELL"


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


def test_resolve_extracts_message_cursor_pagination_contract() -> None:
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
                    "params": ["limit", "before"],
                    "cursor_param": "before",
                    "result_cursor_field": "next_cursor",
                    "cursor_applies_to": ["shared.sessions.messages.list"],
                },
                "errors": {"business_codes": {}},
                "result_envelope": {"raw": True, "items": True, "pagination": True},
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_session_query(card)

    assert resolved.message_cursor_pagination.cursor_param == "before"
    assert resolved.message_cursor_pagination.result_cursor_field == "next_cursor"


def test_resolve_accepts_codex_session_query_contract() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": CODEX_SHARED_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "provider": "codex",
                "methods": {
                    "list_sessions": "codex.sessions.list",
                    "get_session_messages": "codex.sessions.messages.list",
                    "prompt_async": "codex.sessions.prompt_async",
                    "command": "codex.sessions.command",
                },
                "pagination": {
                    "mode": "limit",
                    "default_limit": 20,
                    "max_limit": 100,
                },
                "method_contracts": {
                    "codex.sessions.prompt_async": {
                        "params": {
                            "required": ["session_id", "request.parts"],
                            "optional": [
                                "request.messageID",
                                "request.agent",
                                "request.system",
                                "request.variant",
                                "metadata.codex.directory",
                            ],
                        }
                    },
                    "codex.sessions.command": {
                        "params": {
                            "required": ["session_id", "request.command"],
                            "optional": [
                                "request.arguments",
                                "request.messageID",
                                "metadata.codex.directory",
                            ],
                        }
                    },
                },
                "errors": {"business_codes": {}},
                "result_envelope": {},
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_session_query(card)

    assert resolved.uri == CODEX_SHARED_SESSION_QUERY_URI
    assert resolved.provider == "codex"
    assert resolved.pagination.mode == "limit"
    assert resolved.pagination.params == ("limit",)
    assert resolved.pagination.supports_offset is False


def test_resolve_rejects_codex_offset_pagination() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": CODEX_SHARED_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "provider": "codex",
                "methods": {
                    "list_sessions": "codex.sessions.list",
                    "get_session_messages": "codex.sessions.messages.list",
                },
                "pagination": {
                    "mode": "limit",
                    "default_limit": 20,
                    "max_limit": 100,
                    "params": ["limit", "offset"],
                },
                "errors": {"business_codes": {}},
                "result_envelope": {},
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    with pytest.raises(
        A2AExtensionContractError,
        match="does not support offset pagination",
    ):
        resolve_session_query(card)


def test_resolve_rejects_codex_command_requiring_arguments() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": CODEX_SHARED_SESSION_QUERY_URI,
            "required": False,
            "params": {
                "provider": "codex",
                "methods": {
                    "list_sessions": "codex.sessions.list",
                    "get_session_messages": "codex.sessions.messages.list",
                    "command": "codex.sessions.command",
                },
                "pagination": {
                    "mode": "limit",
                    "default_limit": 20,
                    "max_limit": 100,
                },
                "method_contracts": {
                    "codex.sessions.command": {
                        "params": {
                            "required": [
                                "session_id",
                                "request.command",
                                "request.arguments",
                            ]
                        }
                    }
                },
                "errors": {"business_codes": {}},
                "result_envelope": {},
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    with pytest.raises(
        A2AExtensionContractError,
        match="must not require request.arguments",
    ):
        resolve_session_query(card)


def test_resolve_accepts_limit_and_optional_cursor_mode() -> None:
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
    assert resolved.pagination.params == ("limit", "before")
    assert resolved.pagination.supports_offset is False
    assert resolved.message_cursor_pagination.cursor_param == "before"
    assert resolved.message_cursor_pagination.result_cursor_field == "next_cursor"


def test_resolve_extracts_session_list_filter_contract() -> None:
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
                "method_contracts": {
                    "shared.sessions.list": {
                        "params": {
                            "optional_params": [
                                "limit",
                                "directory",
                                "query.roots",
                                "query.start",
                                "search",
                            ]
                        }
                    }
                },
                "errors": {"business_codes": {}},
                "result_envelope": {"raw": True, "items": True, "pagination": True},
            },
        }
    ]

    card = AgentCard.model_validate(payload)
    resolved = resolve_session_query(card)

    assert resolved.session_list_filters.directory.top_level_param == "directory"
    assert resolved.session_list_filters.directory.query_param is None
    assert resolved.session_list_filters.roots.top_level_param is None
    assert resolved.session_list_filters.roots.query_param == "roots"
    assert resolved.session_list_filters.start.top_level_param is None
    assert resolved.session_list_filters.start.query_param == "start"
    assert resolved.session_list_filters.search.top_level_param == "search"
    assert resolved.session_list_filters.search.query_param is None


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
