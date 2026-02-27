"""Shared helpers for A2A agent service validation and auth handling."""

from __future__ import annotations

import ipaddress
from typing import Any, Dict, Iterable, List, Optional, Type
from urllib.parse import urlparse
from uuid import UUID

from app.core.secret_vault import SecretVaultNotConfiguredError
from app.utils.auth_headers import resolve_stored_auth_fields


from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.a2a_agent_credential import A2AAgentCredential


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


class BaseAgentService(AgentValidationMixin):
    """Base business logic for A2A agent management."""

    _vault: Any

    async def _get_credential(
        self,
        db: AsyncSession,
        *,
        agent_id: UUID,
    ) -> Optional[A2AAgentCredential]:
        stmt = select(A2AAgentCredential).where(A2AAgentCredential.agent_id == agent_id)
        return await db.scalar(stmt)

    async def _delete_credentials(
        self,
        db: AsyncSession,
        *,
        agent_id: UUID,
    ) -> None:
        # Hard-delete credential rows to minimize secret retention.
        await db.execute(
            delete(A2AAgentCredential).where(A2AAgentCredential.agent_id == agent_id)
        )

    async def _upsert_credential(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
        token: Optional[str],
    ) -> Optional[str]:
        encrypted_value, last4 = encrypt_bearer_token(
            vault=self._vault,
            token=token,
            validation_error_cls=self._validation_error_cls,
        )

        credential = await self._get_credential(db, agent_id=agent_id)
        if credential is None:
            # Purge legacy soft-deleted rows before insert to satisfy unique constraint.
            await self._delete_credentials(db, agent_id=agent_id)
            credential = A2AAgentCredential(
                agent_id=agent_id,
                created_by_user_id=user_id,
                encrypted_token=encrypted_value,
                token_last4=last4,
                encryption_version=1,
            )
            db.add(credential)
        else:
            credential.encrypted_token = encrypted_value
            credential.token_last4 = last4
            credential.created_by_user_id = user_id

        return last4

    def _normalize_tags(self, tags: Optional[Iterable[str]]) -> List[str]:
        if tags is None:
            return []
        seen: set[str] = set()
        normalized: List[str] = []
        for tag in tags:
            if tag is None:
                continue
            value = str(tag).strip()
            if not value:
                continue
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(value)
        return normalized

    def _normalize_headers(self, headers: Optional[Dict[str, str]]) -> Dict[str, str]:
        if headers is None:
            return {}
        if not isinstance(headers, dict):
            raise self._validation_error_cls("extra_headers must be a dictionary")
        normalized: Dict[str, str] = {}
        for key, value in headers.items():
            if key is None:
                continue
            header_key = str(key).strip()
            if not header_key:
                # HubA2AAgentService allowed empty keys but A2AAgentService didn't.
                # Standardizing on strict validation.
                continue
            header_value = "" if value is None else str(value).strip()
            normalized[header_key] = header_value
        return normalized


__all__ = [
    "AgentValidationMixin",
    "BaseAgentService",
    "encrypt_bearer_token",
    "normalize_auth_type",
    "normalize_required_text",
    "resolve_agent_auth_fields",
]
