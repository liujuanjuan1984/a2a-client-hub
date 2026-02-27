"""OpenCode interrupt callback extension resolver and helpers."""

from __future__ import annotations

from a2a.types import AgentCard

from app.integrations.a2a_extensions.contract_utils import (
    as_dict,
    build_business_code_map,
    normalize_method_name,
    resolve_jsonrpc_interface,
)
from app.integrations.a2a_extensions.errors import A2AExtensionNotSupportedError
from app.integrations.a2a_extensions.types import (
    ResolvedInterruptCallbackExtension,
)

OPENCODE_INTERRUPT_CALLBACK_URI = "urn:opencode-a2a:opencode-interrupt-callback/v1"


def resolve_opencode_interrupt_callback(
    card: AgentCard,
) -> ResolvedInterruptCallbackExtension:
    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        raise A2AExtensionNotSupportedError("Agent does not declare any extensions")

    ext = None
    for candidate in extensions:
        if getattr(candidate, "uri", None) == OPENCODE_INTERRUPT_CALLBACK_URI:
            ext = candidate
            break
    if ext is None:
        raise A2AExtensionNotSupportedError(
            "OpenCode interrupt callback extension not found"
        )

    required = bool(getattr(ext, "required", False))
    params = as_dict(getattr(ext, "params", None))
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
        uri=OPENCODE_INTERRUPT_CALLBACK_URI,
        required=required,
        jsonrpc=resolve_jsonrpc_interface(card),
        methods={
            "reply_permission": reply_permission_method,
            "reply_question": reply_question_method,
            "reject_question": reject_question_method,
        },
        business_code_map=code_to_error,
    )


__all__ = [
    "OPENCODE_INTERRUPT_CALLBACK_URI",
    "resolve_opencode_interrupt_callback",
]
