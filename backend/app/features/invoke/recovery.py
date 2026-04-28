"""Helpers for session binding normalization and invoke rebound recovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from app.features.invoke.invoke_metadata import (
    apply_invoke_metadata_bindings,
    summarize_invoke_metadata_fields,
)
from app.features.invoke.session_binding import resolve_invoke_session_binding_hint
from app.features.invoke.shared_metadata import (
    apply_invoke_session_binding_metadata,
    strip_session_binding_metadata,
)
from app.integrations.a2a_extensions import get_a2a_extensions_service
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
    A2AExtensionUpstreamError,
)
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.schemas.a2a_invoke import (
    A2AAgentInvokeRequest,
    A2AAgentInvokeSessionBinding,
)
from app.utils.payload_extract import (
    as_dict,
    extract_provider_and_external_session_id,
)
from app.utils.session_identity import normalize_non_empty_text


def extract_rebound_continue_binding_fields(
    *,
    continue_payload: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Resolve provider/session binding from the continue payload metadata."""
    continue_payload_dict = as_dict(continue_payload)
    continue_metadata = as_dict(continue_payload_dict.get("metadata"))

    provider, external_session_id = extract_provider_and_external_session_id(
        continue_metadata
    )
    return provider, external_session_id


def build_rebound_invoke_payload(
    *,
    payload: A2AAgentInvokeRequest,
    continue_payload: dict[str, Any],
) -> A2AAgentInvokeRequest:
    provider, external_session_id = extract_rebound_continue_binding_fields(
        continue_payload=continue_payload
    )
    conversation_id = continue_payload.get("conversationId")

    normalized_provider = provider.lower() if provider else None
    normalized_external_session_id = external_session_id or None
    next_metadata = strip_session_binding_metadata(payload.metadata or {})
    next_conversation_id = (
        normalize_non_empty_text(conversation_id) or payload.conversation_id
    )
    next_session_binding = None
    if normalized_provider or normalized_external_session_id:
        next_session_binding = A2AAgentInvokeSessionBinding(
            provider=normalized_provider,
            externalSessionId=normalized_external_session_id,
        )

    return payload.model_copy(
        update={
            "conversation_id": next_conversation_id,
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


async def validate_provider_aware_continue_session(
    *,
    runtime: Any,
    continue_payload: dict[str, Any],
    logger: Any,
    log_extra: dict[str, Any],
    extensions_service_getter: Callable[[], Any] = get_a2a_extensions_service,
    log_warning_fn: Callable[..., None] = log_session_binding_warning,
) -> Literal["validated", "skipped", "failed"]:
    provider, external_session_id = extract_rebound_continue_binding_fields(
        continue_payload=continue_payload
    )
    if not external_session_id:
        return "skipped"

    try:
        result = await extensions_service_getter().continue_session(
            runtime=runtime,
            session_id=external_session_id,
        )
    except A2AExtensionNotSupportedError:
        return "skipped"
    except A2AExtensionUpstreamError as exc:
        log_warning_fn(
            logger=logger,
            message=(
                "Provider-aware session recovery capability resolution failed upstream; "
                "falling back to local rebound"
            ),
            log_extra=log_extra,
            extra={
                "session_recovery_mode": "provider_aware",
                "session_recovery_provider": provider,
                "session_recovery_session_id": external_session_id,
                "session_recovery_validation_error": str(exc),
            },
        )
        return "skipped"
    except AttributeError as exc:
        log_warning_fn(
            logger=logger,
            message=(
                "Provider-aware session recovery capability resolution failed due to "
                "runtime shape; falling back to local rebound"
            ),
            log_extra=log_extra,
            extra={
                "session_recovery_mode": "provider_aware",
                "session_recovery_provider": provider,
                "session_recovery_session_id": external_session_id,
                "session_recovery_validation_error": str(exc),
            },
        )
        return "skipped"
    except A2AExtensionContractError as exc:
        log_warning_fn(
            logger=logger,
            message=(
                "Provider-aware session recovery contract invalid; "
                "falling back to local rebound"
            ),
            log_extra=log_extra,
            extra={
                "session_recovery_mode": "provider_aware",
                "session_recovery_provider": provider,
                "session_recovery_session_id": external_session_id,
                "session_recovery_validation_error": str(exc),
            },
        )
        return "skipped"

    if not isinstance(result, ExtensionCallResult):
        return "validated"
    if result.success:
        return "validated"

    unsupported_error_codes = {"method_not_supported", "method_disabled"}
    if result.error_code in unsupported_error_codes:
        return "skipped"

    log_warning_fn(
        logger=logger,
        message=(
            "Provider-aware session recovery validation failed; "
            "skipping invoke retry"
        ),
        log_extra=log_extra,
        extra={
            "session_recovery_mode": "provider_aware",
            "session_recovery_provider": provider,
            "session_recovery_session_id": external_session_id,
            "session_recovery_error_code": result.error_code,
            "session_recovery_source": result.source,
        },
    )
    return "failed"


@dataclass(frozen=True, slots=True)
class InvokeMetadataBindingRequiredError(RuntimeError):
    missing_params: tuple[dict[str, Any], ...]
    upstream_error: dict[str, Any]

    def __init__(
        self,
        *,
        missing_fields: tuple[str, ...],
        declared_fields: tuple[dict[str, Any], ...],
    ) -> None:
        message = (
            "Declared invoke metadata is required before this agent can be invoked"
        )
        RuntimeError.__init__(self, message)
        object.__setattr__(
            self,
            "missing_params",
            tuple({"name": name, "required": True} for name in missing_fields),
        )
        object.__setattr__(
            self,
            "upstream_error",
            {
                "message": message,
                "code": "invoke_metadata_not_bound",
                "missing_fields": list(missing_fields),
                "declared_fields": list(declared_fields),
            },
        )
        object.__setattr__(self, "args", (message,))


async def resolve_session_binding_outbound_mode(
    *,
    runtime: Any,
    logger: Any,
    log_extra: dict[str, Any],
    extensions_service_getter: Callable[[], Any] = get_a2a_extensions_service,
    log_warning_fn: Callable[..., None] = log_session_binding_warning,
) -> bool:
    try:
        await extensions_service_getter().resolve_session_binding(runtime=runtime)
    except A2AExtensionNotSupportedError:
        return False
    except A2AExtensionUpstreamError as exc:
        log_warning_fn(
            logger=logger,
            message=(
                "Session binding capability resolution failed upstream; "
                "legacy compatibility remains disabled"
            ),
            log_extra=log_extra,
            extra={
                "session_binding_resolution_error": "upstream_fetch_failed",
                "session_binding_resolution_detail": str(exc),
                "session_binding_fallback_used": False,
            },
        )
        return False
    except AttributeError as exc:
        log_warning_fn(
            logger=logger,
            message=(
                "Session binding capability resolution failed due to runtime shape; "
                "legacy compatibility remains disabled"
            ),
            log_extra=log_extra,
            extra={
                "session_binding_resolution_error": "runtime_invalid",
                "session_binding_resolution_detail": str(exc),
                "session_binding_fallback_used": False,
            },
        )
        return False
    except A2AExtensionContractError as exc:
        log_warning_fn(
            logger=logger,
            message=(
                "Session binding capability contract invalid; "
                "legacy compatibility remains disabled"
            ),
            log_extra=log_extra,
            extra={
                "session_binding_resolution_error": "contract_invalid",
                "session_binding_contract_error": str(exc),
                "session_binding_fallback_used": False,
            },
        )
        return False

    return False


async def finalize_outbound_invoke_payload(
    *,
    payload: A2AAgentInvokeRequest,
    runtime: Any,
    logger: Any,
    log_extra: dict[str, Any],
    extensions_service_getter: Callable[[], Any] = get_a2a_extensions_service,
    log_warning_fn: Callable[..., None] = log_session_binding_warning,
) -> A2AAgentInvokeRequest:
    invoke_metadata_ext = None
    try:
        invoke_metadata_ext = await extensions_service_getter().resolve_invoke_metadata(
            runtime=runtime
        )
    except A2AExtensionNotSupportedError:
        invoke_metadata_ext = None
    except A2AExtensionContractError as exc:
        log_warning_fn(
            logger=logger,
            message="Invoke metadata contract invalid; ignoring declared bindings",
            log_extra=log_extra,
            extra={"invoke_metadata_contract_error": str(exc)},
        )
    except A2AExtensionUpstreamError as exc:
        log_warning_fn(
            logger=logger,
            message="Invoke metadata capability resolution failed upstream",
            log_extra=log_extra,
            extra={"invoke_metadata_resolution_error": str(exc)},
        )

    provider, external_session_id = resolve_invoke_session_binding_hint(
        session_binding=payload.session_binding,
        metadata=payload.metadata,
    )
    invoke_metadata_resolution = apply_invoke_metadata_bindings(
        metadata=payload.metadata,
        ext=invoke_metadata_ext,
        defaults=getattr(runtime, "invoke_metadata_defaults", None),
    )
    cleaned_metadata = strip_session_binding_metadata(
        invoke_metadata_resolution.metadata
    )
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
        if invoke_metadata_ext is not None and (
            invoke_metadata_resolution.missing_required_fields
        ):
            raise InvokeMetadataBindingRequiredError(
                missing_fields=invoke_metadata_resolution.missing_required_fields,
                declared_fields=tuple(
                    summarize_invoke_metadata_fields(invoke_metadata_ext.fields)
                ),
            )
        if (
            cleaned_metadata == (payload.metadata or {})
            and payload.session_binding is None
        ):
            return payload
        return payload.model_copy(
            update={"metadata": cleaned_metadata, "session_binding": None}
        )

    next_metadata = apply_invoke_session_binding_metadata(
        cleaned_metadata,
        provider=provider,
        external_session_id=external_session_id,
    )
    if (
        invoke_metadata_ext is not None
        and invoke_metadata_resolution.missing_required_fields
    ):
        raise InvokeMetadataBindingRequiredError(
            missing_fields=invoke_metadata_resolution.missing_required_fields,
            declared_fields=tuple(
                summarize_invoke_metadata_fields(invoke_metadata_ext.fields)
            ),
        )
    return payload.model_copy(
        update={"metadata": next_metadata, "session_binding": None}
    )
