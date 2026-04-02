"""Helpers for session-scoped invoke metadata bindings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.integrations.a2a_extensions.shared_contract import (
    SHARED_INVOKE_KEY,
    SHARED_METADATA_KEY,
)
from app.integrations.a2a_extensions.types import (
    ResolvedInvokeMetadataExtension,
    ResolvedInvokeMetadataField,
)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _has_bound_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def extract_invoke_metadata_bindings(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    root = _as_dict(metadata)
    shared = _as_dict(root.get(SHARED_METADATA_KEY))
    invoke = _as_dict(shared.get(SHARED_INVOKE_KEY))
    bindings = _as_dict(invoke.get("bindings"))
    return {
        str(key): value
        for key, value in bindings.items()
        if isinstance(key, str) and key.strip() and _has_bound_value(value)
    }


def strip_invoke_metadata_bindings(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    root = _as_dict(metadata)
    shared = _as_dict(root.get(SHARED_METADATA_KEY))
    invoke = _as_dict(shared.get(SHARED_INVOKE_KEY))

    invoke.pop("bindings", None)
    if invoke:
        shared[SHARED_INVOKE_KEY] = invoke
    else:
        shared.pop(SHARED_INVOKE_KEY, None)

    if shared:
        root[SHARED_METADATA_KEY] = shared
    else:
        root.pop(SHARED_METADATA_KEY, None)
    return root


@dataclass(frozen=True, slots=True)
class ResolvedInvokeMetadataApplication:
    metadata: dict[str, Any]
    injected_fields: tuple[str, ...]
    missing_required_fields: tuple[str, ...]


def apply_invoke_metadata_bindings(
    *,
    metadata: Mapping[str, Any] | None,
    ext: ResolvedInvokeMetadataExtension | None,
) -> ResolvedInvokeMetadataApplication:
    cleaned_metadata = strip_invoke_metadata_bindings(metadata)
    bound = extract_invoke_metadata_bindings(metadata)
    next_metadata = dict(cleaned_metadata)
    injected_fields: list[str] = []

    for key, value in bound.items():
        if _has_bound_value(next_metadata.get(key)):
            continue
        next_metadata[key] = value
        injected_fields.append(key)

    missing_required_fields: list[str] = []
    if ext is not None:
        for field in ext.fields:
            if not field.required:
                continue
            if _has_bound_value(next_metadata.get(field.name)):
                continue
            missing_required_fields.append(field.name)

    return ResolvedInvokeMetadataApplication(
        metadata=next_metadata,
        injected_fields=tuple(injected_fields),
        missing_required_fields=tuple(missing_required_fields),
    )


def summarize_invoke_metadata_fields(
    fields: tuple[ResolvedInvokeMetadataField, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "name": field.name,
            "required": field.required,
            **({"description": field.description} if field.description else {}),
        }
        for field in fields
    ]


__all__ = [
    "ResolvedInvokeMetadataApplication",
    "apply_invoke_metadata_bindings",
    "extract_invoke_metadata_bindings",
    "strip_invoke_metadata_bindings",
    "summarize_invoke_metadata_fields",
]
