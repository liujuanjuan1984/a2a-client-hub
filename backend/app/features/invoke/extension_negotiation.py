"""Helpers for request-scoped extension negotiation in core invoke flows."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from app.features.invoke.invoke_metadata import extract_invoke_metadata_bindings
from app.integrations.a2a_extensions import get_a2a_extensions_service
from app.utils.payload_extract import extract_provider_and_external_session_id

logger = logging.getLogger(__name__)


def _has_non_empty_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    return True


def _has_path(root: Mapping[str, Any] | None, dotted_path: str | None) -> bool:
    if not isinstance(root, Mapping) or not dotted_path:
        return False
    current: Any = root
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False
        current = current.get(part)
    return _has_non_empty_value(current)


async def resolve_core_invoke_requested_extensions(
    *,
    runtime: Any,
    metadata: Mapping[str, Any] | None,
    require_stream_hints: bool,
    extensions_service_getter: Callable[[], Any] = get_a2a_extensions_service,
) -> tuple[str, ...]:
    """Resolve request-scoped extension URIs for core invoke/stream operations."""

    try:
        snapshot = await extensions_service_getter().resolve_capability_snapshot(
            runtime=runtime
        )
    except Exception:
        logger.warning(
            "Failed to resolve capability snapshot for core invoke negotiation; "
            "continuing without requested extensions",
            exc_info=True,
            extra={
                "runtime_url": getattr(getattr(runtime, "resolved", None), "url", None),
                "require_stream_hints": require_stream_hints,
            },
        )
        return ()

    requested: list[str] = []

    def append_uri(uri: str | None) -> None:
        if isinstance(uri, str) and uri.strip() and uri not in requested:
            requested.append(uri)

    provider, external_session_id = extract_provider_and_external_session_id(
        {"metadata": dict(metadata or {})}
    )
    if (provider or external_session_id) and snapshot.session_binding.ext is not None:
        append_uri(snapshot.session_binding.ext.uri)

    invoke_metadata_ext = snapshot.invoke_metadata.ext
    if invoke_metadata_ext is not None:
        bound_fields = extract_invoke_metadata_bindings(metadata)
        if bound_fields or any(
            _has_non_empty_value((metadata or {}).get(field.name))
            for field in invoke_metadata_ext.fields
        ):
            append_uri(invoke_metadata_ext.uri)

    model_selection_ext = snapshot.model_selection.ext
    if model_selection_ext is not None and _has_path(
        {"metadata": dict(metadata or {})},
        model_selection_ext.metadata_field,
    ):
        append_uri(model_selection_ext.uri)

    request_execution_options = snapshot.request_execution_options
    if request_execution_options.source_extensions and _has_path(
        {"metadata": dict(metadata or {})},
        request_execution_options.metadata_field,
    ):
        for extension_uri in request_execution_options.source_extensions:
            append_uri(extension_uri)

    if require_stream_hints and snapshot.stream_hints.ext is not None:
        append_uri(snapshot.stream_hints.ext.uri)

    return tuple(requested)
