from __future__ import annotations

import pytest
from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.model_selection import resolve_model_selection
from app.integrations.a2a_extensions.shared_contract import (
    MODEL_SELECTION_URI,
    OPENCODE_MODEL_SELECTION_URI,
    SHARED_MODEL_FIELD,
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


def test_resolve_requires_model_selection_extension_present() -> None:
    card = AgentCard.model_validate(_base_card_payload())
    with pytest.raises(A2AExtensionNotSupportedError):
        resolve_model_selection(card)


def test_resolve_extracts_canonical_model_selection_contract() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": MODEL_SELECTION_URI,
            "required": False,
            "params": {
                "metadata_field": SHARED_MODEL_FIELD,
                "behavior": "prefer_metadata_model_else_upstream_default",
                "applies_to_methods": ["message/send", "message/stream"],
                "supported_metadata": [
                    "shared.model.providerID",
                    "shared.model.modelID",
                ],
                "provider_private_metadata": [],
            },
        }
    ]

    resolved = resolve_model_selection(AgentCard.model_validate(payload))

    assert resolved.uri == MODEL_SELECTION_URI
    assert resolved.provider == "opencode"
    assert resolved.metadata_field == SHARED_MODEL_FIELD
    assert resolved.behavior == "prefer_metadata_model_else_upstream_default"
    assert resolved.applies_to_methods == ("message/send", "message/stream")
    assert resolved.supported_metadata == (
        "shared.model.providerID",
        "shared.model.modelID",
    )
    assert resolved.provider_private_metadata == ()


def test_resolve_defaults_provider_to_opencode() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": MODEL_SELECTION_URI,
            "required": False,
            "params": {
                "metadata_field": SHARED_MODEL_FIELD,
                "behavior": "prefer_metadata_model_else_upstream_default",
                "applies_to_methods": ["message/send"],
            },
        }
    ]

    resolved = resolve_model_selection(AgentCard.model_validate(payload))

    assert resolved.provider == "opencode"


def test_resolve_accepts_opencode_https_model_selection_uri() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": OPENCODE_MODEL_SELECTION_URI,
            "required": False,
            "params": {
                "metadata_field": SHARED_MODEL_FIELD,
                "behavior": "prefer_metadata_model_else_upstream_default",
                "applies_to_methods": ["message/send"],
            },
        }
    ]

    resolved = resolve_model_selection(AgentCard.model_validate(payload))

    assert resolved.uri == OPENCODE_MODEL_SELECTION_URI
    assert resolved.provider == "opencode"


def test_resolve_rejects_non_canonical_metadata_field() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": MODEL_SELECTION_URI,
            "required": False,
            "params": {
                "metadata_field": "metadata.model",
                "behavior": "prefer_metadata_model_else_upstream_default",
                "applies_to_methods": ["message/send", "message/stream"],
            },
        }
    ]

    with pytest.raises(A2AExtensionContractError):
        resolve_model_selection(AgentCard.model_validate(payload))


def test_resolve_rejects_empty_applies_to_methods() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": MODEL_SELECTION_URI,
            "required": False,
            "params": {
                "metadata_field": SHARED_MODEL_FIELD,
                "behavior": "prefer_metadata_model_else_upstream_default",
                "applies_to_methods": [],
            },
        }
    ]

    with pytest.raises(A2AExtensionContractError):
        resolve_model_selection(AgentCard.model_validate(payload))
