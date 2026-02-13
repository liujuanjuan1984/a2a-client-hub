"""Normalization helpers for session identity fields."""

from __future__ import annotations

from typing import Optional


def normalize_non_empty_text(value: object) -> Optional[str]:
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed:
            return trimmed
    return None


def normalize_provider(value: object) -> Optional[str]:
    normalized = normalize_non_empty_text(value)
    if normalized is None:
        return None
    lowered = normalized.lower()
    if lowered == "opencode" or lowered.startswith("opencode-"):
        return "opencode"
    return lowered


__all__ = ["normalize_non_empty_text", "normalize_provider"]
