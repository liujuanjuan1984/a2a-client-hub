"""Shared helpers for extracting normalized values from payload-like objects."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.utils.session_identity import normalize_provider


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


_PROVIDER_KEYS = ("provider", "session_provider", "external_provider")
_EXTERNAL_KEYS = (
    "externalSessionId",
    "external_session_id",
    "upstream_session_id",
    "opencode_session_id",
)
_CONTEXT_KEYS = ("contextId", "context_id")


def extract_context_id(payload: Mapping[str, Any]) -> str | None:
    return pick_first_non_empty_str(payload, _CONTEXT_KEYS)


def extract_provider_and_external_session_id(
    payload: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    provider = normalize_provider(pick_first_non_empty_str(payload, _PROVIDER_KEYS))
    external_session_id = pick_first_non_empty_str(payload, _EXTERNAL_KEYS)
    if external_session_id and provider is None and "opencode_session_id" in payload:
        provider = normalize_provider("opencode")
    return provider, external_session_id


__all__ = [
    "as_dict",
    "extract_context_id",
    "extract_provider_and_external_session_id",
    "pick_first_non_empty_str",
]
