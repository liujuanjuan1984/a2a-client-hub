"""Helpers for canonical shared A2A metadata sections."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.integrations.a2a_extensions.shared_contract import (
    CANONICAL_EXTERNAL_SESSION_ID_KEY,
    CANONICAL_PROVIDER_KEY,
    SHARED_INTERRUPT_KEY,
    SHARED_METADATA_KEY,
    SHARED_SESSION_KEY,
    SHARED_STREAM_KEY,
    SHARED_USAGE_KEY,
)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _pick_first_non_empty_str(
    payload: Mapping[str, Any], keys: Iterable[str]
) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed:
                return trimmed
    return None


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
    interrupt = extract_shared_metadata_section(
        payload_or_metadata,
        section=SHARED_INTERRUPT_KEY,
    )
    if interrupt:
        return interrupt
    metadata = coerce_metadata_mapping(payload_or_metadata)
    return _as_dict(metadata.get(SHARED_INTERRUPT_KEY))


def extract_preferred_usage_metadata(
    payload_or_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    usage = extract_shared_metadata_section(
        payload_or_metadata,
        section=SHARED_USAGE_KEY,
    )
    if usage:
        return usage
    metadata = coerce_metadata_mapping(payload_or_metadata)
    return _as_dict(metadata.get(SHARED_USAGE_KEY))


def extract_preferred_session_metadata(
    payload_or_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = coerce_metadata_mapping(payload_or_metadata)
    session = extract_shared_metadata_section(
        payload_or_metadata,
        section=SHARED_SESSION_KEY,
    )
    if session:
        merged = dict(session)
        if "id" not in merged:
            external_session_id = _pick_first_non_empty_str(
                metadata, (CANONICAL_EXTERNAL_SESSION_ID_KEY,)
            )
            if external_session_id:
                merged["id"] = external_session_id
        if CANONICAL_PROVIDER_KEY not in merged:
            provider = _pick_first_non_empty_str(metadata, (CANONICAL_PROVIDER_KEY,))
            if provider:
                merged[CANONICAL_PROVIDER_KEY] = provider
        return merged

    legacy: dict[str, Any] = {}
    external_session_id = _pick_first_non_empty_str(
        metadata, (CANONICAL_EXTERNAL_SESSION_ID_KEY,)
    )
    provider = _pick_first_non_empty_str(metadata, (CANONICAL_PROVIDER_KEY,))
    if external_session_id:
        legacy["id"] = external_session_id
    if provider:
        legacy[CANONICAL_PROVIDER_KEY] = provider
    return legacy


__all__ = [
    "SHARED_INTERRUPT_KEY",
    "SHARED_SESSION_KEY",
    "SHARED_STREAM_KEY",
    "coerce_metadata_mapping",
    "extract_preferred_interrupt_metadata",
    "extract_preferred_session_metadata",
    "extract_preferred_usage_metadata",
    "extract_shared_metadata_section",
    "merge_shared_metadata_sections",
]
