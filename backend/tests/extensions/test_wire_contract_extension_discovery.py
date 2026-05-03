from __future__ import annotations

import pytest
from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.shared_contract import (
    MODEL_SELECTION_URI,
    OPENCODE_MODEL_SELECTION_URI,
    OPENCODE_MODEL_SELECTION_URN,
    OPENCODE_WIRE_CONTRACT_URI,
    OPENCODE_WIRE_CONTRACT_URN,
    WIRE_CONTRACT_URI,
)
from app.integrations.a2a_extensions.wire_contract import resolve_wire_contract
from tests.support.a2a import parse_agent_card


def _build_card(*, extension_payload: dict | None) -> AgentCard:
    extensions = [extension_payload] if extension_payload is not None else []
    return parse_agent_card(
        {
            "name": "Example Agent",
            "description": "Example",
            "version": "1.0",
            "supportedInterfaces": [
                {
                    "url": "https://example.com/jsonrpc",
                    "protocolBinding": "JSONRPC",
                }
            ],
            "capabilities": {"extensions": extensions},
            "defaultInputModes": [],
            "defaultOutputModes": [],
            "skills": [{"id": "s1", "name": "s1", "description": "d", "tags": []}],
        }
    )


def test_resolve_wire_contract_supports_declared_contract() -> None:
    card = _build_card(
        extension_payload={
            "uri": WIRE_CONTRACT_URI,
            "required": False,
            "params": {
                "protocol_version": "0.3.0",
                "preferred_transport": "HTTP+JSON",
                "additional_transports": ["JSON-RPC"],
                "core": {
                    "jsonrpc_methods": ["agent/getAuthenticatedExtendedCard"],
                    "http_endpoints": ["GET /v1/tasks"],
                },
                "extensions": {
                    "jsonrpc_methods": ["providers.list", "models.list"],
                    "conditionally_available_methods": {
                        "opencode.sessions.shell": {
                            "reason": "disabled_by_configuration",
                            "toggle": "A2A_ENABLE_SESSION_SHELL",
                        }
                    },
                    "extension_uris": [OPENCODE_MODEL_SELECTION_URI],
                },
                "all_jsonrpc_methods": [
                    "agent/getAuthenticatedExtendedCard",
                    "providers.list",
                    "models.list",
                ],
                "service_behaviors": {
                    "classification": "stable-service-semantics",
                },
                "unsupported_method_error": {
                    "code": -32601,
                    "type": "METHOD_NOT_SUPPORTED",
                    "data_fields": [
                        "type",
                        "method",
                        "supported_methods",
                        "protocol_version",
                    ],
                },
            },
        }
    )

    resolved = resolve_wire_contract(card)

    assert resolved.uri == WIRE_CONTRACT_URI
    assert resolved.preferred_transport == "HTTP+JSON"
    assert resolved.additional_transports == ("JSON-RPC",)
    assert resolved.extension_uris == ("urn:a2a:model-selection/v1",)
    assert resolved.conditionally_available_methods[
        "opencode.sessions.shell"
    ].toggle == ("A2A_ENABLE_SESSION_SHELL")
    assert resolved.unsupported_method_error.code == -32601


def test_resolve_wire_contract_accepts_https_alias() -> None:
    card = _build_card(
        extension_payload={
            "uri": OPENCODE_WIRE_CONTRACT_URI,
            "required": False,
            "params": {
                "protocol_version": "0.3.0",
                "preferred_transport": "HTTP+JSON",
                "additional_transports": ["JSON-RPC"],
                "core": {
                    "jsonrpc_methods": ["agent/getAuthenticatedExtendedCard"],
                    "http_endpoints": ["GET /v1/tasks"],
                },
                "extensions": {
                    "jsonrpc_methods": [],
                    "conditionally_available_methods": {},
                    "extension_uris": [OPENCODE_MODEL_SELECTION_URN],
                },
                "all_jsonrpc_methods": ["agent/getAuthenticatedExtendedCard"],
                "service_behaviors": {},
                "unsupported_method_error": {
                    "code": -32601,
                    "type": "METHOD_NOT_SUPPORTED",
                    "data_fields": [
                        "type",
                        "method",
                        "supported_methods",
                        "protocol_version",
                    ],
                },
            },
        }
    )

    resolved = resolve_wire_contract(card)

    assert resolved.uri == OPENCODE_WIRE_CONTRACT_URI
    assert resolved.conditionally_available_methods == {}


def test_resolve_wire_contract_accepts_opencode_urn_alias() -> None:
    card = _build_card(
        extension_payload={
            "uri": OPENCODE_WIRE_CONTRACT_URN,
            "required": False,
            "params": {
                "protocol_version": "0.3.0",
                "preferred_transport": "HTTP+JSON",
                "additional_transports": ["JSON-RPC"],
                "core": {
                    "jsonrpc_methods": ["agent/getAuthenticatedExtendedCard"],
                    "http_endpoints": ["GET /v1/tasks"],
                },
                "extensions": {
                    "jsonrpc_methods": [],
                    "conditionally_available_methods": {},
                    "extension_uris": [OPENCODE_MODEL_SELECTION_URN],
                },
                "all_jsonrpc_methods": ["agent/getAuthenticatedExtendedCard"],
                "service_behaviors": {},
                "unsupported_method_error": {
                    "code": -32601,
                    "type": "METHOD_NOT_SUPPORTED",
                    "data_fields": [
                        "type",
                        "method",
                        "supported_methods",
                        "protocol_version",
                    ],
                },
            },
        }
    )

    resolved = resolve_wire_contract(card)

    assert resolved.uri == OPENCODE_WIRE_CONTRACT_URN
    assert resolved.extension_uris == (MODEL_SELECTION_URI,)


def test_resolve_wire_contract_rejects_invalid_conditional_map() -> None:
    card = _build_card(
        extension_payload={
            "uri": WIRE_CONTRACT_URI,
            "required": False,
            "params": {
                "protocol_version": "0.3.0",
                "preferred_transport": "HTTP+JSON",
                "additional_transports": ["JSON-RPC"],
                "core": {
                    "jsonrpc_methods": ["agent/getAuthenticatedExtendedCard"],
                    "http_endpoints": ["GET /v1/tasks"],
                },
                "extensions": {
                    "jsonrpc_methods": ["providers.list"],
                    "conditionally_available_methods": [],
                    "extension_uris": [],
                },
                "all_jsonrpc_methods": ["agent/getAuthenticatedExtendedCard"],
                "service_behaviors": {},
                "unsupported_method_error": {
                    "code": -32601,
                    "type": "METHOD_NOT_SUPPORTED",
                    "data_fields": [
                        "type",
                        "method",
                        "supported_methods",
                        "protocol_version",
                    ],
                },
            },
        }
    )

    with pytest.raises(
        A2AExtensionContractError,
        match="params.extensions.conditionally_available_methods",
    ):
        resolve_wire_contract(card)


def test_resolve_wire_contract_requires_declared_extension() -> None:
    card = _build_card(extension_payload=None)

    with pytest.raises(
        A2AExtensionNotSupportedError,
        match="Wire contract extension not found|Agent does not declare any extensions",
    ):
        resolve_wire_contract(card)
