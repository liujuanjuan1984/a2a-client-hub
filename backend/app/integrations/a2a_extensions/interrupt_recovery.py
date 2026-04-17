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
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.shared_contract import (
    CODEX_INTERRUPT_RECOVERY_URI,
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

    resolved_uri = str(getattr(ext, "uri", INTERRUPT_RECOVERY_URI)).strip()
    required = bool(getattr(ext, "required", False))
    params = as_dict(getattr(ext, "params", None))
    raw_provider = params.get("provider")
    if raw_provider is None:
        provider = (
            "codex" if resolved_uri == CODEX_INTERRUPT_RECOVERY_URI else "opencode"
        )
    else:
        provider = require_str(raw_provider, field="params.provider").lower()

    methods = as_dict(params.get("methods"))
    list_method = normalize_method_name(
        methods.get("list"),
        field="methods.list",
    )
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
    recovery_scope = as_dict(params.get("recovery_scope"))

    raw_recovery_data_source = recovery_scope.get("data_source")
    recovery_data_source = (
        require_str(raw_recovery_data_source, field="recovery_scope.data_source")
        if raw_recovery_data_source is not None
        else None
    )

    raw_identity_scope = recovery_scope.get("identity_scope")
    identity_scope = (
        require_str(raw_identity_scope, field="recovery_scope.identity_scope")
        if raw_identity_scope is not None
        else None
    )

    raw_empty_result = recovery_scope.get("empty_result_when_identity_unavailable")
    if raw_empty_result is not None and not isinstance(raw_empty_result, bool):
        raise A2AExtensionContractError(
            "Extension contract missing/invalid "
            "'recovery_scope.empty_result_when_identity_unavailable'"
        )

    raw_implementation_scope = params.get("implementation_scope")
    implementation_scope = (
        require_str(
            raw_implementation_scope,
            field="params.implementation_scope",
        )
        if raw_implementation_scope is not None
        else None
    )

    return ResolvedInterruptRecoveryExtension(
        uri=resolved_uri or str(getattr(ext, "uri", INTERRUPT_RECOVERY_URI)),
        required=required,
        provider=provider,
        jsonrpc=resolve_jsonrpc_interface(card),
        methods={
            "list": list_method,
            "list_permissions": list_permissions_method,
            "list_questions": list_questions_method,
        },
        business_code_map=code_to_error,
        recovery_data_source=recovery_data_source,
        identity_scope=identity_scope,
        implementation_scope=implementation_scope,
        empty_result_when_identity_unavailable=(
            raw_empty_result if isinstance(raw_empty_result, bool) else None
        ),
    )
