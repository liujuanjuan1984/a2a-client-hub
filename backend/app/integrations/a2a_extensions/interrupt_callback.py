"""Shared interrupt callback extension resolver and helpers."""

from __future__ import annotations

from a2a.types import AgentCard

from app.integrations.a2a_extensions.contract_utils import (
    as_dict,
    build_business_code_map,
    normalize_method_name,
    require_str,
    resolve_jsonrpc_interface,
)
from app.integrations.a2a_extensions.errors import A2AExtensionNotSupportedError
from app.integrations.a2a_extensions.shared_contract import (
    SHARED_INTERRUPT_CALLBACK_URI,
    SUPPORTED_INTERRUPT_CALLBACK_URIS,
)
from app.integrations.a2a_extensions.types import (
    ResolvedInterruptCallbackExtension,
)


def resolve_interrupt_callback(
    card: AgentCard,
) -> ResolvedInterruptCallbackExtension:
    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        raise A2AExtensionNotSupportedError("Agent does not declare any extensions")

    ext = None
    for candidate in extensions:
        if getattr(candidate, "uri", None) in SUPPORTED_INTERRUPT_CALLBACK_URIS:
            ext = candidate
            break
    if ext is None:
        raise A2AExtensionNotSupportedError(
            "Shared interrupt callback extension not found"
        )

    required = bool(getattr(ext, "required", False))
    params = as_dict(getattr(ext, "params", None))
    raw_provider = params.get("provider")
    if raw_provider is None:
        provider = "opencode"
    else:
        provider = require_str(raw_provider, field="params.provider").lower()
    methods = as_dict(params.get("methods"))
    reply_permission_method = normalize_method_name(
        methods.get("reply_permission"),
        field="methods.reply_permission",
    )
    reply_question_method = normalize_method_name(
        methods.get("reply_question"),
        field="methods.reply_question",
    )
    reject_question_method = normalize_method_name(
        methods.get("reject_question"),
        field="methods.reject_question",
    )

    errors = as_dict(params.get("errors"))
    code_to_error = build_business_code_map(errors.get("business_codes"))

    return ResolvedInterruptCallbackExtension(
        uri=str(getattr(ext, "uri", SHARED_INTERRUPT_CALLBACK_URI)),
        required=required,
        provider=provider,
        jsonrpc=resolve_jsonrpc_interface(card),
        methods={
            "reply_permission": reply_permission_method,
            "reply_question": reply_question_method,
            "reject_question": reject_question_method,
        },
        business_code_map=code_to_error,
    )


__all__ = ["resolve_interrupt_callback"]
