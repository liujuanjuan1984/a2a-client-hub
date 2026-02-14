"""Shared helpers for A2A agent service validation and auth handling."""

from __future__ import annotations

from typing import Any, Optional, Type

from app.core.secret_vault import SecretVaultNotConfiguredError
from app.utils.auth_headers import resolve_stored_auth_fields


def normalize_required_text(
    *,
    value: str,
    field_label: str,
    validation_error_cls: Type[Exception],
) -> str:
    """Normalize required text fields and raise service-specific errors."""

    trimmed = (value or "").strip()
    if not trimmed:
        raise validation_error_cls(f"{field_label} is required")
    return trimmed


def normalize_auth_type(
    *,
    value: str,
    allowed_auth_types: set[str],
    validation_error_cls: Type[Exception],
) -> str:
    """Normalize and validate auth_type."""

    normalized = (value or "").strip().lower()
    if normalized not in allowed_auth_types:
        raise validation_error_cls("Unsupported auth_type")
    return normalized


def resolve_agent_auth_fields(
    *,
    auth_type: str,
    auth_header: Optional[str],
    auth_scheme: Optional[str],
    existing_auth_header: Optional[str],
    existing_auth_scheme: Optional[str],
    validation_error_cls: Type[Exception],
) -> tuple[Optional[str], Optional[str]]:
    """Resolve stored auth fields for supported auth types."""

    if auth_type == "none":
        return None, None
    if auth_type != "bearer":
        raise validation_error_cls("Unsupported auth_type")

    return resolve_stored_auth_fields(
        auth_header=auth_header,
        auth_scheme=auth_scheme,
        existing_auth_header=existing_auth_header,
        existing_auth_scheme=existing_auth_scheme,
    )


def encrypt_bearer_token(
    *,
    vault: Any,
    token: Optional[str],
    validation_error_cls: Type[Exception],
) -> tuple[str, str]:
    """Validate and encrypt bearer token, returning encrypted value and last4."""

    if token is None or not token.strip():
        raise validation_error_cls("Bearer token is required")
    if not vault.is_configured:
        raise validation_error_cls("Credential encryption key is missing")

    try:
        return vault.encrypt(token.strip())
    except SecretVaultNotConfiguredError as exc:
        raise validation_error_cls(str(exc)) from exc


class AgentValidationMixin:
    """Shared validation helpers for agent service classes."""

    _validation_error_cls: Type[Exception]
    _allowed_auth_types: set[str]

    def _normalize_name(self, value: str) -> str:
        return normalize_required_text(
            value=value,
            field_label="Name",
            validation_error_cls=self._validation_error_cls,
        )

    def _normalize_card_url(self, value: str) -> str:
        return normalize_required_text(
            value=value,
            field_label="Card URL",
            validation_error_cls=self._validation_error_cls,
        )

    def _normalize_auth_type(self, value: str) -> str:
        return normalize_auth_type(
            value=value,
            allowed_auth_types=self._allowed_auth_types,
            validation_error_cls=self._validation_error_cls,
        )

    def _resolve_auth_fields(
        self,
        auth_type: str,
        auth_header: Optional[str],
        auth_scheme: Optional[str],
        existing: Any | None,
    ) -> tuple[Optional[str], Optional[str]]:
        return resolve_agent_auth_fields(
            auth_type=auth_type,
            auth_header=auth_header,
            auth_scheme=auth_scheme,
            existing_auth_header=getattr(existing, "auth_header", None),
            existing_auth_scheme=getattr(existing, "auth_scheme", None),
            validation_error_cls=self._validation_error_cls,
        )


__all__ = [
    "AgentValidationMixin",
    "encrypt_bearer_token",
    "normalize_auth_type",
    "normalize_required_text",
    "resolve_agent_auth_fields",
]
