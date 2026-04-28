from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def _coerce_mapping(payload: Any) -> Mapping[str, Any] | None:
    if isinstance(payload, Mapping):
        return payload
    return None


def dict_field(payload: Any, key: str) -> dict[str, Any]:
    source = _coerce_mapping(payload)
    if source is None:
        return {}
    value = source.get(key)
    if isinstance(value, dict):
        return value
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def pick_non_empty_str(
    payload: Any,
    keys: tuple[str, ...],
) -> str | None:
    source = _coerce_mapping(payload)
    if source is None:
        return None
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def pick_int(
    payload: Any,
    keys: tuple[str, ...],
) -> int | None:
    source = _coerce_mapping(payload)
    if source is None:
        return None
    for key in keys:
        value = source.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
    return None


def pick_first_non_empty_str(
    payloads: Iterable[Any],
    keys: tuple[str, ...],
) -> str | None:
    for payload in payloads:
        resolved = pick_non_empty_str(payload, keys)
        if resolved is not None:
            return resolved
    return None


def pick_first_int(
    payloads: Iterable[Any],
    keys: tuple[str, ...],
) -> int | None:
    for payload in payloads:
        resolved = pick_int(payload, keys)
        if resolved is not None:
            return resolved
    return None
