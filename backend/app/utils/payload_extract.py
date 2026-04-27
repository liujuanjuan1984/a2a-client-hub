"""Shared helpers for extracting normalized values from payload-like objects."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.utils.session_identity import normalize_provider


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


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


_CONTEXT_KEYS = ("contextId",)


def extract_context_id(payload: Mapping[str, Any]) -> str | None:
    return pick_first_non_empty_str(payload, _CONTEXT_KEYS)


def extract_provider_and_external_session_id(
    payload: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    metadata = as_dict(payload.get("metadata"))
    source = metadata or as_dict(payload)
    shared = as_dict(source.get("shared"))
    session = as_dict(shared.get("session"))

    provider = normalize_provider(pick_first_non_empty_str(session, ("provider",)))
    external_session_id = pick_first_non_empty_str(
        session,
        ("id",),
    )
    return provider, external_session_id
