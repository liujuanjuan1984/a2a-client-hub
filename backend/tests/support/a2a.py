from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Final

from a2a.types import AgentCard

from app.integrations.a2a_client.protobuf import parse_agent_card as _parse_agent_card
from app.integrations.a2a_extensions.shared_contract import SHARED_SESSION_QUERY_URI

_OMIT: Final = object()


def parse_agent_card(payload: Mapping[str, Any]) -> AgentCard:
    """Parse test AgentCard payloads via the protobuf-native helper."""

    return _parse_agent_card(payload)


def build_agent_card_payload(
    *,
    extensions: list[Mapping[str, Any]] | None = None,
    skills: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal AgentCard payload for test fixtures."""

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
        "capabilities": {"extensions": deepcopy(extensions or [])},
        "defaultInputModes": [],
        "defaultOutputModes": [],
        "skills": deepcopy(
            skills or [{"id": "s1", "name": "s1", "description": "d", "tags": []}]
        ),
    }


def build_session_query_extension_payload(
    *,
    uri: str = SHARED_SESSION_QUERY_URI,
    provider: str = "opencode",
    methods: Mapping[str, str] | None = None,
    pagination: Mapping[str, Any] | None = None,
    result_envelope: Mapping[str, Any] | object = _OMIT,
    method_contracts: Mapping[str, Any] | None = None,
    control_method_flags: Mapping[str, Any] | None = None,
    errors: Mapping[str, Any] | None = None,
    required: bool | None = None,
) -> dict[str, Any]:
    """Build a shared session-query extension payload for test fixtures."""

    extension: dict[str, Any] = {
        "uri": uri,
        "params": {
            "provider": provider,
            "methods": deepcopy(
                methods
                or {
                    "list_sessions": "shared.sessions.list",
                    "get_session_messages": "shared.sessions.messages.list",
                }
            ),
            "pagination": deepcopy(
                pagination
                or {
                    "mode": "page_size",
                    "default_size": 20,
                    "max_size": 100,
                }
            ),
        },
    }
    if required is not None:
        extension["required"] = required

    params = extension["params"]
    if method_contracts is not None:
        params["method_contracts"] = deepcopy(method_contracts)
    if control_method_flags is not None:
        params["control_method_flags"] = deepcopy(control_method_flags)
    if errors is not None:
        params["errors"] = deepcopy(errors)
    if result_envelope is not _OMIT:
        params["result_envelope"] = deepcopy(result_envelope)

    return extension
