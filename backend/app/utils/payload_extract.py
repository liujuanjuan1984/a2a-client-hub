"""Shared helpers for extracting normalized values from payload-like objects."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def pick_first_non_empty_str(
    payload: Mapping[str, Any], keys: Iterable[str]
) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed:
                return trimmed
    return None


__all__ = ["as_dict", "pick_first_non_empty_str"]
