"""Stable working-directory contract helpers."""

from __future__ import annotations

from typing import Any, Mapping

from app.utils.session_identity import normalize_non_empty_text


def extract_working_directory(metadata: Mapping[str, Any] | None) -> str | None:
    """Resolve a working directory from the stable Hub metadata shape."""
    if not isinstance(metadata, Mapping):
        return None

    return normalize_non_empty_text(
        metadata.get("workingDirectory") or metadata.get("working_directory")
    )


def merge_working_directory_metadata(
    metadata: Mapping[str, Any] | None,
    working_directory: str | None,
) -> dict[str, Any]:
    """Merge the stable Hub working-directory metadata field."""
    next_metadata = dict(metadata or {})
    next_metadata.pop("working_directory", None)

    normalized_directory = normalize_non_empty_text(working_directory)
    if normalized_directory:
        next_metadata["workingDirectory"] = normalized_directory
    else:
        next_metadata.pop("workingDirectory", None)
    return next_metadata


def adapt_working_directory_metadata_for_provider(
    metadata: Mapping[str, Any] | None,
    working_directory: str | None,
    *,
    metadata_namespace: str,
) -> dict[str, Any]:
    """Adapt Hub-stable working-directory metadata for a provider upstream."""
    next_metadata = dict(metadata or {})
    if working_directory is None:
        resolved_directory = extract_working_directory(next_metadata)
    else:
        resolved_directory = normalize_non_empty_text(working_directory)

    next_metadata.pop("workingDirectory", None)
    next_metadata.pop("working_directory", None)

    normalized_namespace = normalize_non_empty_text(metadata_namespace)
    if not normalized_namespace:
        return next_metadata

    section_raw = next_metadata.get(normalized_namespace)
    next_section = dict(section_raw) if isinstance(section_raw, Mapping) else {}
    if resolved_directory:
        next_section["directory"] = resolved_directory
        next_metadata[normalized_namespace] = next_section
        return next_metadata

    next_section.pop("directory", None)
    if next_section:
        next_metadata[normalized_namespace] = next_section
    else:
        next_metadata.pop(normalized_namespace, None)
    return next_metadata
