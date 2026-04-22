"""Helpers for normalizing upstream A2A task payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def normalize_task_payload(task: Any) -> dict[str, Any] | None:
    """Return a JSON-like dict for task payloads from SDK or JSON-RPC adapters."""

    normalized = _to_json_like(task)
    return normalized if isinstance(normalized, dict) else None


def _to_json_like(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _to_json_like(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_to_json_like(item) for item in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="json", by_alias=True, exclude_none=True)
        except TypeError:
            dumped = model_dump()
        return _to_json_like(dumped)

    legacy_dict = getattr(value, "dict", None)
    if callable(legacy_dict):
        try:
            dumped = legacy_dict(by_alias=True, exclude_none=True)
        except TypeError:
            dumped = legacy_dict()
        return _to_json_like(dumped)

    raw_dict = getattr(value, "__dict__", None)
    if isinstance(raw_dict, Mapping):
        return {
            str(key): _to_json_like(item)
            for key, item in raw_dict.items()
            if item is not None and not str(key).startswith("_")
        }
    return value
