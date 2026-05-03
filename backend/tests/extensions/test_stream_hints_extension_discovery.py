from __future__ import annotations

import pytest

from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.shared_contract import (
    OPENCODE_STREAM_HINTS_URI,
    STREAM_HINTS_URI,
)
from app.integrations.a2a_extensions.stream_hints import resolve_stream_hints
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


def test_resolve_stream_hints_defaults_to_canonical_shared_fields() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [{"uri": STREAM_HINTS_URI, "params": {}}]

    resolved = resolve_stream_hints(parse_agent_card(payload))

    assert resolved.uri == STREAM_HINTS_URI
    assert resolved.stream_field == "metadata.shared.stream"
    assert resolved.usage_field == "metadata.shared.usage"
    assert resolved.interrupt_field == "metadata.shared.interrupt"
    assert resolved.session_field == "metadata.shared.session"


def test_resolve_stream_hints_accepts_opencode_https_uri() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {"uri": OPENCODE_STREAM_HINTS_URI, "params": {}}
    ]

    resolved = resolve_stream_hints(parse_agent_card(payload))

    assert resolved.uri == OPENCODE_STREAM_HINTS_URI
    assert resolved.stream_field == "metadata.shared.stream"


def test_resolve_stream_hints_accepts_current_opencode_uri() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {"uri": OPENCODE_STREAM_HINTS_URI, "params": {}}
    ]

    resolved = resolve_stream_hints(parse_agent_card(payload))

    assert resolved.uri == OPENCODE_STREAM_HINTS_URI
    assert resolved.stream_field == "metadata.shared.stream"


def test_resolve_stream_hints_rejects_non_canonical_field_override() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": STREAM_HINTS_URI,
            "params": {"stream_field": "metadata.private.stream"},
        }
    ]

    with pytest.raises(A2AExtensionContractError, match="params.stream_field"):
        resolve_stream_hints(parse_agent_card(payload))


def test_resolve_stream_hints_rejects_missing_extension() -> None:
    with pytest.raises(A2AExtensionNotSupportedError):
        resolve_stream_hints(parse_agent_card(_base_card_payload()))
