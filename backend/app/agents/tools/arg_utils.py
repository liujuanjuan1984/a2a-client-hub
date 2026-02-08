"""Shared helper functions for tool argument normalization."""

from __future__ import annotations

import json
from typing import Iterable, Optional, Union
from uuid import UUID

UUIDLike = Union[str, UUID]


def parse_uuid_list_argument(value, *, field_name: str = "ids"):
    """Allow agents to pass UUID lists as JSON strings or comma-separated values."""

    if value is None or isinstance(value, list):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            items = [item.strip() for item in value.split(",") if item.strip()]
            if items:
                return items

    raise ValueError(f"{field_name} must be a list or JSON array string")


def normalize_uuid_list(values: Optional[Iterable[UUIDLike]]) -> Optional[list[str]]:
    """Convert UUID/str iterables to a list of string identifiers for schemas."""

    if not values:
        return None

    normalized: list[str] = []
    for value in values:
        if value is None:
            continue
        normalized.append(str(value))

    return normalized or None


__all__ = ["parse_uuid_list_argument", "normalize_uuid_list"]
