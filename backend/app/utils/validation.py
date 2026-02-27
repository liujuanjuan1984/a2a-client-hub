"""Shared validation helpers for services and routers."""

from __future__ import annotations

from typing import Type


def normalize_required_text(
    *,
    value: str,
    field_label: str,
    validation_error_cls: Type[Exception],
) -> str:
    """Normalize required text fields and raise service-specific errors."""

    trimmed = (value or "").strip()
    if not trimmed:
        raise validation_error_cls(f"{field_label} is required")
    return trimmed
