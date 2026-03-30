"""Interrupt recovery extension resolver and helpers."""

from __future__ import annotations

from a2a.types import AgentCard

from app.integrations.a2a_extensions.contract_utils import (
    as_dict,
    build_business_code_map,
    normalize_method_name,
    require_str,
    resolve_jsonrpc_interface,
)
from app.integrations.a2a_extensions.errors import (
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.shared_contract import (
    INTERRUPT_RECOVERY_URI,
    SUPPORTED_INTERRUPT_RECOVERY_URIS,
    is_supported_extension_uri,
)
from app.integrations.a2a_extensions.types import (
    ResolvedInterruptRecoveryExtension,
)


def resolve_interrupt_recovery(
    card: AgentCard,
) -> ResolvedInterruptRecoveryExtension:
    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        raise A2AExtensionNotSupportedError("Agent does not declare any extensions")

    ext = None
    for candidate in extensions:
        if is_supported_extension_uri(
            getattr(candidate, "uri", None),
            SUPPORTED_INTERRUPT_RECOVERY_URIS,
        ):
            ext = candidate
            break
    if ext is None:
        raise A2AExtensionNotSupportedError("Interrupt recovery extension not found")

    required = bool(getattr(ext, "required", False))
    params = as_dict(getattr(ext, "params", None))
    raw_provider = params.get("provider")
    if raw_provider is None:
        provider = "opencode"
    else:
        provider = require_str(raw_provider, field="params.provider").lower()

    methods = as_dict(params.get("methods"))
    list_permissions_method = normalize_method_name(
        methods.get("list_permissions"),
        field="methods.list_permissions",
    )
    list_questions_method = normalize_method_name(
        methods.get("list_questions"),
        field="methods.list_questions",
    )

    errors = as_dict(params.get("errors"))
    code_to_error = build_business_code_map(errors.get("business_codes"))

    return ResolvedInterruptRecoveryExtension(
        uri=str(getattr(ext, "uri", INTERRUPT_RECOVERY_URI)),
        required=required,
        provider=provider,
        jsonrpc=resolve_jsonrpc_interface(card),
        methods={
            "list_permissions": list_permissions_method,
            "list_questions": list_questions_method,
        },
        business_code_map=code_to_error,
    )


__all__ = ["resolve_interrupt_recovery"]
