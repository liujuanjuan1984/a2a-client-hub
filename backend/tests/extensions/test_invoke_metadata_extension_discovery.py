from __future__ import annotations

import pytest
from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.invoke_metadata import resolve_invoke_metadata
from app.integrations.a2a_extensions.shared_contract import (
    INVOKE_METADATA_URI,
    OPENCODE_INVOKE_METADATA_URI,
    SHARED_INVOKE_FIELD,
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


def test_resolve_requires_invoke_metadata_extension_present() -> None:
    card = AgentCard.model_validate(_base_card_payload())
    with pytest.raises(A2AExtensionNotSupportedError):
        resolve_invoke_metadata(card)


def test_resolve_extracts_invoke_metadata_contract() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": INVOKE_METADATA_URI,
            "required": False,
            "params": {
                "provider": "Commonground",
                "metadata_field": SHARED_INVOKE_FIELD,
                "behavior": "merge_bound_metadata_into_invoke",
                "applies_to_methods": ["message/send", "message/stream"],
                "fields": [
                    {
                        "name": "project_id",
                        "required": True,
                        "description": "Project scope for routing.",
                    },
                    {"name": "channel_id", "required": True},
                ],
                "supported_metadata": [
                    "shared.invoke.bindings.project_id",
                    "shared.invoke.bindings.channel_id",
                ],
            },
        }
    ]

    resolved = resolve_invoke_metadata(AgentCard.model_validate(payload))

    assert resolved.uri == INVOKE_METADATA_URI
    assert resolved.provider == "commonground"
    assert resolved.metadata_field == SHARED_INVOKE_FIELD
    assert resolved.behavior == "merge_bound_metadata_into_invoke"
    assert resolved.applies_to_methods == ("message/send", "message/stream")
    assert [item.name for item in resolved.fields] == ["project_id", "channel_id"]
    assert resolved.fields[0].description == "Project scope for routing."
    assert resolved.supported_metadata == (
        "shared.invoke.bindings.project_id",
        "shared.invoke.bindings.channel_id",
    )


def test_resolve_accepts_https_alias() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": OPENCODE_INVOKE_METADATA_URI,
            "required": False,
            "params": {
                "metadata_field": SHARED_INVOKE_FIELD,
                "behavior": "merge_bound_metadata_into_invoke",
                "applies_to_methods": ["message/send"],
                "fields": [{"name": "project_id", "required": True}],
            },
        }
    ]

    resolved = resolve_invoke_metadata(AgentCard.model_validate(payload))
    assert resolved.uri == OPENCODE_INVOKE_METADATA_URI


def test_resolve_rejects_non_canonical_metadata_field() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": INVOKE_METADATA_URI,
            "required": False,
            "params": {
                "metadata_field": "metadata.invoke",
                "behavior": "merge_bound_metadata_into_invoke",
                "applies_to_methods": ["message/send"],
                "fields": [{"name": "project_id", "required": True}],
            },
        }
    ]

    with pytest.raises(A2AExtensionContractError):
        resolve_invoke_metadata(AgentCard.model_validate(payload))


def test_resolve_rejects_empty_fields() -> None:
    payload = _base_card_payload()
    payload["capabilities"]["extensions"] = [
        {
            "uri": INVOKE_METADATA_URI,
            "required": False,
            "params": {
                "metadata_field": SHARED_INVOKE_FIELD,
                "behavior": "merge_bound_metadata_into_invoke",
                "applies_to_methods": ["message/send"],
                "fields": [],
            },
        }
    ]

    with pytest.raises(A2AExtensionContractError):
        resolve_invoke_metadata(AgentCard.model_validate(payload))
