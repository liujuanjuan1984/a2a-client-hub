"""Stable working-directory contract helpers."""

from __future__ import annotations

from typing import Any, Mapping

from app.utils.session_identity import normalize_non_empty_text


def extract_working_directory(metadata: Mapping[str, Any] | None) -> str | None:
    """Resolve a working directory from stable or legacy metadata shapes."""
    if not isinstance(metadata, Mapping):
        return None

    direct = normalize_non_empty_text(
        metadata.get("workingDirectory") or metadata.get("working_directory")
    )
    if direct:
        return direct

    opencode = metadata.get("opencode")
    if not isinstance(opencode, Mapping):
        return None
    return normalize_non_empty_text(opencode.get("directory"))


def merge_working_directory_metadata(
    metadata: Mapping[str, Any] | None,
    working_directory: str | None,
) -> dict[str, Any]:
    """Adapt the stable field into legacy provider-private metadata."""
    next_metadata = dict(metadata or {})
    next_metadata.pop("workingDirectory", None)
    next_metadata.pop("working_directory", None)

    normalized_directory = normalize_non_empty_text(working_directory)
    opencode_raw = next_metadata.get("opencode")
    next_opencode = dict(opencode_raw) if isinstance(opencode_raw, Mapping) else {}

    if normalized_directory:
        next_opencode["directory"] = normalized_directory
        next_metadata["opencode"] = next_opencode
        return next_metadata

    next_opencode.pop("directory", None)
    if next_opencode:
        next_metadata["opencode"] = next_opencode
    else:
        next_metadata.pop("opencode", None)
    return next_metadata
