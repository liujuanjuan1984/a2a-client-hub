"""Helpers for canonical shared A2A metadata sections."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.integrations.a2a_extensions.shared_contract import (
    CANONICAL_EXTERNAL_SESSION_ID_KEY,
    CANONICAL_PROVIDER_KEY,
    SHARED_INTERRUPT_KEY,
    SHARED_METADATA_KEY,
    SHARED_SESSION_KEY,
    SHARED_USAGE_KEY,
)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def coerce_metadata_mapping(payload_or_metadata: Mapping[str, Any]) -> dict[str, Any]:
    metadata = payload_or_metadata.get("metadata")
    if isinstance(metadata, Mapping):
        return dict(metadata)
    return dict(payload_or_metadata)


def extract_shared_metadata_section(
    payload_or_metadata: Mapping[str, Any],
    *,
    section: str,
) -> dict[str, Any]:
    metadata = coerce_metadata_mapping(payload_or_metadata)
    shared = _as_dict(metadata.get(SHARED_METADATA_KEY))
    return _as_dict(shared.get(section))


def merge_shared_metadata_sections(
    payloads_or_metadata: Iterable[Mapping[str, Any]],
    *,
    section: str,
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for value in payloads_or_metadata:
        shared_section = extract_shared_metadata_section(value, section=section)
        if shared_section:
            resolved.update(shared_section)
    return resolved


def extract_preferred_interrupt_metadata(
    payload_or_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    return extract_shared_metadata_section(
        payload_or_metadata,
        section=SHARED_INTERRUPT_KEY,
    )


def extract_preferred_usage_metadata(
    payload_or_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    return extract_shared_metadata_section(
        payload_or_metadata,
        section=SHARED_USAGE_KEY,
    )


def merge_preferred_session_binding_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    provider: str | None,
    external_session_id: str | None,
) -> dict[str, Any]:
    next_metadata = coerce_metadata_mapping(metadata or {})
    next_shared = _as_dict(next_metadata.get(SHARED_METADATA_KEY))
    next_session = _as_dict(next_shared.get(SHARED_SESSION_KEY))

    if external_session_id:
        next_session["id"] = external_session_id
    else:
        next_session.pop("id", None)
    if provider:
        next_session[CANONICAL_PROVIDER_KEY] = provider
    else:
        next_session.pop(CANONICAL_PROVIDER_KEY, None)

    if next_session:
        next_shared[SHARED_SESSION_KEY] = next_session
    else:
        next_shared.pop(SHARED_SESSION_KEY, None)

    if next_shared:
        next_metadata[SHARED_METADATA_KEY] = next_shared
    else:
        next_metadata.pop(SHARED_METADATA_KEY, None)

    next_metadata.pop(CANONICAL_EXTERNAL_SESSION_ID_KEY, None)
    next_metadata.pop(CANONICAL_PROVIDER_KEY, None)

    return next_metadata


def strip_session_binding_metadata(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    next_metadata = coerce_metadata_mapping(metadata or {})
    next_shared = _as_dict(next_metadata.get(SHARED_METADATA_KEY))
    next_shared.pop(SHARED_SESSION_KEY, None)

    if next_shared:
        next_metadata[SHARED_METADATA_KEY] = next_shared
    else:
        next_metadata.pop(SHARED_METADATA_KEY, None)

    next_metadata.pop(CANONICAL_EXTERNAL_SESSION_ID_KEY, None)
    next_metadata.pop(CANONICAL_PROVIDER_KEY, None)
    return next_metadata


def apply_invoke_session_binding_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    provider: str | None,
    external_session_id: str | None,
) -> dict[str, Any]:
    next_metadata = strip_session_binding_metadata(metadata or {})
    if external_session_id or provider:
        return merge_preferred_session_binding_metadata(
            next_metadata,
            provider=provider,
            external_session_id=external_session_id,
        )
    return next_metadata
