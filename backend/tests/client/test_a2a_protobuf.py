from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app.integrations.a2a_client.client import _json_fallback
from app.integrations.a2a_client.protobuf import to_json_like
from app.utils.json_encoder import json_dumps


@dataclass
class _DataclassPayload:
    event_id: str
    metadata: dict[str, object]


class _ModelDumpPayload:
    def model_dump(self, **_kwargs):
        return {
            "event_id": "evt-model",
            "metadata": {"source": "model-dump"},
        }


class _LegacyDictPayload:
    def __init__(self) -> None:
        self.called = False

    def dict(self, **_kwargs):
        self.called = True
        return {"event_id": "evt-legacy"}


class _AttrsOnlyPayload:
    def __init__(self) -> None:
        self.event_id = "evt-attrs"
        self.metadata = {"source": "attrs-only"}


def test_to_json_like_supports_dataclass_instances() -> None:
    payload = _DataclassPayload(
        event_id="evt-dataclass",
        metadata={"source": "dataclass"},
    )

    assert to_json_like(payload) == {
        "event_id": "evt-dataclass",
        "metadata": {"source": "dataclass"},
    }


def test_to_json_like_supports_model_dump_objects() -> None:
    assert to_json_like(_ModelDumpPayload()) == {
        "event_id": "evt-model",
        "metadata": {"source": "model-dump"},
    }


def test_to_json_like_does_not_consume_legacy_dict_only_objects() -> None:
    payload = _LegacyDictPayload()

    assert to_json_like(payload) is payload
    assert payload.called is False


def test_to_json_like_does_not_consume_attrs_only_objects() -> None:
    payload = _AttrsOnlyPayload()

    assert to_json_like(payload) is payload


def test_json_dumps_serializes_dataclass_payloads() -> None:
    payload = _DataclassPayload(
        event_id="evt-dataclass",
        metadata={"source": "dataclass"},
    )

    assert json.loads(json_dumps(payload)) == {
        "event_id": "evt-dataclass",
        "metadata": {"source": "dataclass"},
    }


def test_json_dumps_rejects_legacy_dict_only_objects() -> None:
    payload = _LegacyDictPayload()

    with pytest.raises(TypeError):
        json_dumps(payload)

    assert payload.called is False


def test_json_fallback_uses_model_dump_but_not_legacy_dict() -> None:
    assert _json_fallback(_ModelDumpPayload()) == {
        "event_id": "evt-model",
        "metadata": {"source": "model-dump"},
    }

    payload = _LegacyDictPayload()
    assert _json_fallback(payload) == str(payload)
    assert payload.called is False
