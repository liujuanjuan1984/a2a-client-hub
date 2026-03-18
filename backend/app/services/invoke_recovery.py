"""Helpers for session binding normalization and invoke rebound recovery."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.integrations.a2a_extensions import get_a2a_extensions_service
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
    A2AExtensionUpstreamError,
)
from app.schemas.a2a_invoke import (
    A2AAgentInvokeRequest,
    A2AAgentInvokeSessionBinding,
)
from app.services.a2a_shared_metadata import (
    apply_invoke_session_binding_metadata,
    strip_session_binding_metadata,
)
from app.services.invoke_session_binding import resolve_invoke_session_binding_hint
from app.utils.payload_extract import (
    as_dict,
    extract_context_id,
    extract_provider_and_external_session_id,
)
from app.utils.session_identity import normalize_non_empty_text


def extract_rebound_continue_binding_fields(
    *,
    continue_payload: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    """Resolve provider/context binding from the continue payload metadata."""
    continue_payload_dict = as_dict(continue_payload)
    continue_metadata = as_dict(continue_payload_dict.get("metadata"))

    provider, external_session_id = extract_provider_and_external_session_id(
        continue_metadata
    )
    context_id = extract_context_id(continue_metadata)

    return provider, external_session_id, context_id


def build_rebound_invoke_payload(
    *,
    payload: A2AAgentInvokeRequest,
    continue_payload: dict[str, Any],
) -> A2AAgentInvokeRequest:
    (
        provider,
        external_session_id,
        context_id,
    ) = extract_rebound_continue_binding_fields(continue_payload=continue_payload)
    conversation_id = continue_payload.get("conversationId")

    normalized_provider = provider.lower() if provider else None
    normalized_external_session_id = external_session_id or None
    next_metadata = strip_session_binding_metadata(payload.metadata or {})
    next_context_id = normalize_non_empty_text(context_id) or payload.context_id
    next_conversation_id = (
        normalize_non_empty_text(conversation_id) or payload.conversation_id
    )
    next_session_binding = None
    if normalized_provider or normalized_external_session_id:
        next_session_binding = A2AAgentInvokeSessionBinding(
            provider=normalized_provider,
            external_session_id=normalized_external_session_id,
        )

    return payload.model_copy(
        update={
            "conversation_id": next_conversation_id,
            "context_id": next_context_id,
            "metadata": next_metadata,
            "session_binding": next_session_binding,
        },
    )


def log_session_binding_warning(
    *,
    logger: Any,
    message: str,
    log_extra: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> None:
    log_warning = getattr(logger, "warning", None) or getattr(logger, "info", None)
    if not callable(log_warning):
        return
    merged_extra = dict(log_extra)
    if extra:
        merged_extra.update(extra)
    log_warning(message, extra=merged_extra)


async def resolve_session_binding_outbound_mode(
    *,
    runtime: Any,
    logger: Any,
    log_extra: dict[str, Any],
    extensions_service_getter: Callable[[], Any] = get_a2a_extensions_service,
    log_warning_fn: Callable[..., None] = log_session_binding_warning,
) -> bool:
    try:
        ext = await extensions_service_getter().resolve_session_binding(runtime=runtime)
    except A2AExtensionNotSupportedError:
        return True
    except A2AExtensionUpstreamError as exc:
        log_warning_fn(
            logger=logger,
            message=(
                "Session binding capability resolution failed upstream; "
                "using compatibility fallback"
            ),
            log_extra=log_extra,
            extra={
                "session_binding_resolution_error": "upstream_fetch_failed",
                "session_binding_resolution_detail": str(exc),
                "session_binding_fallback_used": True,
            },
        )
        return True
    except AttributeError as exc:
        log_warning_fn(
            logger=logger,
            message=(
                "Session binding capability resolution failed due to runtime shape; "
                "using compatibility fallback"
            ),
            log_extra=log_extra,
            extra={
                "session_binding_resolution_error": "runtime_invalid",
                "session_binding_resolution_detail": str(exc),
                "session_binding_fallback_used": True,
            },
        )
        return True
    except A2AExtensionContractError as exc:
        log_warning_fn(
            logger=logger,
            message=(
                "Session binding capability contract invalid; "
                "using compatibility fallback"
            ),
            log_extra=log_extra,
            extra={
                "session_binding_resolution_error": "contract_invalid",
                "session_binding_contract_error": str(exc),
                "session_binding_fallback_used": True,
            },
        )
        return True

    return ext.legacy_uri_used


async def finalize_outbound_invoke_payload(
    *,
    payload: A2AAgentInvokeRequest,
    runtime: Any,
    logger: Any,
    log_extra: dict[str, Any],
    resolve_outbound_mode: Callable[..., Awaitable[bool]] = (
        resolve_session_binding_outbound_mode
    ),
    log_warning_fn: Callable[..., None] = log_session_binding_warning,
) -> A2AAgentInvokeRequest:
    provider, external_session_id = resolve_invoke_session_binding_hint(
        session_binding=payload.session_binding,
        metadata=payload.metadata,
    )
    cleaned_metadata = strip_session_binding_metadata(payload.metadata or {})
    if provider and not external_session_id:
        log_warning_fn(
            logger=logger,
            message=(
                "Discarding incomplete session binding intent without external "
                "session id"
            ),
            log_extra=log_extra,
            extra={
                "session_binding_discarded": True,
                "session_binding_discard_reason": "missing_external_session_id",
                "session_binding_provider": provider,
                "session_binding_source": (
                    "session_binding_intent"
                    if payload.session_binding is not None
                    else "legacy_metadata"
                ),
            },
        )
        provider = None
    if not provider and not external_session_id:
        if (
            cleaned_metadata == (payload.metadata or {})
            and payload.session_binding is None
        ):
            return payload
        return payload.model_copy(
            update={"metadata": cleaned_metadata, "session_binding": None}
        )

    include_legacy_root = await resolve_outbound_mode(
        runtime=runtime,
        logger=logger,
        log_extra=log_extra,
    )
    next_metadata = apply_invoke_session_binding_metadata(
        cleaned_metadata,
        provider=provider,
        external_session_id=external_session_id,
        include_legacy_root=include_legacy_root,
    )
    return payload.model_copy(
        update={"metadata": next_metadata, "session_binding": None}
    )


__all__ = [
    "build_rebound_invoke_payload",
    "extract_rebound_continue_binding_fields",
    "finalize_outbound_invoke_payload",
    "log_session_binding_warning",
    "resolve_session_binding_outbound_mode",
]
