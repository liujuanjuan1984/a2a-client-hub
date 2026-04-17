"""Shared helpers for A2A agent service validation and auth handling."""

from __future__ import annotations

import ipaddress
import json
from typing import Any, Optional, Type, cast
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_vault import SecretVaultNotConfiguredError
from app.db.models.a2a_agent_credential import A2AAgentCredential
from app.utils.auth_headers import (
    DEFAULT_AUTH_HEADER,
    DEFAULT_BASIC_AUTH_SCHEME,
    resolve_stored_auth_fields,
)

ALLOWED_AUTH_TYPES = {"none", "bearer", "basic"}
ALLOWED_AVAILABILITY_POLICIES = {"public", "allowlist"}
ALLOWED_SHARED_CREDENTIAL_MODES = {"none", "shared", "user"}


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
    if auth_type == "bearer":
        return resolve_stored_auth_fields(
            auth_header=auth_header,
            auth_scheme=auth_scheme,
            existing_auth_header=existing_auth_header,
            existing_auth_scheme=existing_auth_scheme,
        )
    if auth_type == "basic":
        return resolve_stored_auth_fields(
            auth_header=auth_header,
            auth_scheme=auth_scheme,
            existing_auth_header=existing_auth_header,
            existing_auth_scheme=existing_auth_scheme,
            default_header=DEFAULT_AUTH_HEADER,
            default_scheme=DEFAULT_BASIC_AUTH_SCHEME,
        )
    raise validation_error_cls("Unsupported auth_type")


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
        return cast(tuple[str, str], vault.encrypt(token.strip()))
    except SecretVaultNotConfiguredError as exc:
        raise validation_error_cls(str(exc)) from exc


def encrypt_auth_payload(
    *,
    vault: Any,
    auth_type: str,
    token: Optional[str],
    basic_username: Optional[str],
    basic_password: Optional[str],
    validation_error_cls: Type[Exception],
) -> tuple[str, str | None, str | None]:
    """Validate and encrypt auth payload, returning encrypted value and previews."""

    if auth_type == "bearer":
        encrypted_value, last4 = encrypt_bearer_token(
            vault=vault,
            token=token,
            validation_error_cls=validation_error_cls,
        )
        return encrypted_value, last4, None

    if auth_type == "basic":
        username = (basic_username or "").strip()
        password = (basic_password or "").strip()
        if not username:
            raise validation_error_cls("Basic username is required")
        if not password:
            raise validation_error_cls("Basic password is required")
        if not vault.is_configured:
            raise validation_error_cls("Credential encryption key is missing")
        payload = json.dumps(
            {"username": username, "password": password},
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            encrypted_value, _ = cast(tuple[str, str | None], vault.encrypt(payload))
        except SecretVaultNotConfiguredError as exc:
            raise validation_error_cls(str(exc)) from exc
        return encrypted_value, None, username

    raise validation_error_cls("Unsupported auth_type")


async def get_agent_credential(
    db: AsyncSession,
    *,
    agent_id: UUID,
) -> Optional[A2AAgentCredential]:
    """Fetch credential for an agent."""
    stmt = select(A2AAgentCredential).where(A2AAgentCredential.agent_id == agent_id)
    return cast(A2AAgentCredential | None, await db.scalar(stmt))


async def delete_agent_credentials(
    db: AsyncSession,
    *,
    agent_id: UUID,
) -> None:
    """Hard-delete all credentials for an agent."""
    await db.execute(
        delete(A2AAgentCredential).where(A2AAgentCredential.agent_id == agent_id)
    )


async def upsert_agent_credential(
    db: AsyncSession,
    *,
    vault: Any,
    auth_type: str = "bearer",
    agent_id: UUID,
    user_id: UUID,
    token: Optional[str],
    basic_username: Optional[str] = None,
    basic_password: Optional[str] = None,
    validation_error_cls: Type[Exception],
) -> str:
    """Validate, encrypt, and store agent credential."""
    encrypted_value, last4, username_hint = encrypt_auth_payload(
        vault=vault,
        auth_type=auth_type,
        token=token,
        basic_username=basic_username,
        basic_password=basic_password,
        validation_error_cls=validation_error_cls,
    )

    credential = await get_agent_credential(db, agent_id=agent_id)
    if credential is None:
        # Purge legacy rows (if any) to satisfy unique constraint
        await delete_agent_credentials(db, agent_id=agent_id)
        credential = A2AAgentCredential(
            agent_id=agent_id,
            created_by_user_id=user_id,
            encrypted_token=encrypted_value,
            token_last4=last4,
            username_hint=username_hint,
            encryption_version=1,
        )
        db.add(credential)
    else:
        setattr(credential, "encrypted_token", encrypted_value)
        setattr(credential, "token_last4", last4)
        setattr(credential, "username_hint", username_hint)
        setattr(credential, "created_by_user_id", user_id)

    return username_hint or last4 or ""


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
        trimmed = normalize_required_text(
            value=value,
            field_label="Card URL",
            validation_error_cls=self._validation_error_cls,
        )
        parsed = urlparse(trimmed)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise self._validation_error_cls("Card URL must be a valid http(s) address")

        host = parsed.hostname or ""
        if host == "localhost" or host.endswith(".localhost"):
            raise self._validation_error_cls("Card URL host is not allowed")

        try:
            ip_value = ipaddress.ip_address(host)
        except ValueError:
            ip_value = None

        if ip_value and (
            ip_value.is_private
            or ip_value.is_loopback
            or ip_value.is_link_local
            or ip_value.is_multicast
            or ip_value.is_reserved
            or ip_value.is_unspecified
        ):
            raise self._validation_error_cls(
                "Card URL points to a private or reserved IP address"
            )

        return trimmed

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
