"""Shared auth resolution helpers for runtime builders."""

from __future__ import annotations

from typing import Any, Tuple, Type

from app.core.secret_vault import SecretVaultNotConfiguredError
from app.integrations.a2a_client.service import ResolvedAgent
from app.utils.auth_headers import build_auth_header_pair


def resolve_runtime_auth_headers(
    *,
    headers: dict[str, str],
    auth_type: str,
    auth_header: str | None,
    auth_scheme: str | None,
    credential: Any | None,
    vault: Any,
    validation_error_cls: Type[Exception],
) -> Tuple[dict[str, str], str | None]:
    """Resolve runtime auth headers and optional token_last4 for logging."""

    resolved_headers = dict(headers)

    if auth_type == "none":
        return resolved_headers, None
    if auth_type != "bearer":
        raise validation_error_cls("Unsupported auth_type")
    if credential is None:
        raise validation_error_cls("Bearer token is required")
    if not vault.is_configured:
        raise validation_error_cls("Credential encryption key is missing")

    try:
        decrypted = vault.decrypt(credential.encrypted_token)
    except SecretVaultNotConfiguredError as exc:
        raise validation_error_cls(str(exc)) from exc

    header_name, header_value = build_auth_header_pair(
        auth_header=auth_header,
        auth_scheme=auth_scheme,
        token=decrypted.value,
    )
    resolved_headers[header_name] = header_value
    token_last4 = decrypted.last4 or getattr(credential, "token_last4", None)
    return resolved_headers, token_last4


def build_resolved_runtime_agent(
    *,
    name: str,
    card_url: str,
    extra_headers: dict[str, str] | None,
    auth_type: str,
    auth_header: str | None,
    auth_scheme: str | None,
    credential: Any | None,
    vault: Any,
    validation_error_cls: Type[Exception],
) -> tuple[ResolvedAgent, str | None]:
    """Build a ResolvedAgent and optional token_last4 for runtime execution."""

    headers, token_last4 = resolve_runtime_auth_headers(
        headers=dict(extra_headers or {}),
        auth_type=auth_type,
        auth_header=auth_header,
        auth_scheme=auth_scheme,
        credential=credential,
        vault=vault,
        validation_error_cls=validation_error_cls,
    )
    resolved = ResolvedAgent(
        name=name,
        url=card_url,
        description=None,
        metadata={},
        headers=headers,
    )
    return resolved, token_last4


__all__ = ["build_resolved_runtime_agent", "resolve_runtime_auth_headers"]
