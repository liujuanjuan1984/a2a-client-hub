"""
Service helpers for managing user-supplied LLM credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID

import litellm
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm.client import LLMClient
from app.core.config import settings
from app.core.logging import get_logger
from app.core.secret_vault import (
    DecryptionResult,
    SecretVaultNotConfiguredError,
    user_llm_secret_vault,
)
from app.db.models.user_llm_credential import UserLlmCredential
from app.db.transaction import commit_safely
from app.utils.timezone_util import utc_now

logger = get_logger(__name__)


class UserLlmCredentialError(RuntimeError):
    """Base error for BYOT credential failures."""


class UserLlmCredentialDisabledError(UserLlmCredentialError):
    """Raised when BYOT feature is disabled."""


class UserLlmCredentialNotFoundError(UserLlmCredentialError):
    """Raised when the requested credential cannot be located."""


class UserLlmCredentialValidationError(UserLlmCredentialError):
    """Raised when payload validation fails."""


@dataclass(frozen=True)
class ResolvedLlmCredential:
    """Decrypted credential ready for use by AgentService."""

    credential_id: UUID
    provider: str
    api_key: str
    api_base: Optional[str]
    model_override: Optional[str]
    token_last4: Optional[str]


class UserLlmCredentialService:
    """Business logic wrapper for CRUD and resolution operations."""

    def __init__(self) -> None:
        self._vault = user_llm_secret_vault

    def is_enabled(self) -> bool:
        return (
            settings.user_llm_credentials_enabled
            and settings.user_llm_token_encryption_key.strip() != ""
            and self._vault.is_configured
        )

    # ----------------------
    # CRUD helpers
    # ----------------------
    async def list_credentials(
        self, db: AsyncSession, *, user_id: UUID
    ) -> List[UserLlmCredential]:
        if not self.is_enabled():
            return []
        stmt = (
            select(UserLlmCredential)
            .where(
                and_(
                    UserLlmCredential.user_id == user_id,
                    UserLlmCredential.deleted_at.is_(None),
                )
            )
            .order_by(
                UserLlmCredential.is_default.desc(),
                UserLlmCredential.created_at.asc(),
            )
        )
        result = await db.scalars(stmt)
        return result.all()

    async def create_credential(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        provider: str,
        api_key: str,
        display_name: Optional[str] = None,
        api_base: Optional[str] = None,
        model_override: Optional[str] = None,
        make_default: bool = True,
    ) -> UserLlmCredential:
        self._ensure_enabled()

        if not api_key or not api_key.strip():
            raise UserLlmCredentialValidationError("API Key is required")
        normalized_provider = provider.strip().lower() or "openai"
        normalized_label = await self._normalize_display_name(
            db, user_id, display_name, normalized_provider
        )

        encrypted_value, last4 = self._vault.encrypt(api_key.strip())
        credential = UserLlmCredential(
            user_id=user_id,
            provider=normalized_provider,
            display_name=normalized_label,
            api_base=(api_base or "").strip() or None,
            model_override=(model_override or "").strip() or None,
            encrypted_api_key=encrypted_value,
            token_last4=last4,
            encryption_version=1,
            is_default=False,
        )
        db.add(credential)
        await commit_safely(db)
        await db.refresh(credential)

        if make_default or not await self._has_default(db, user_id):
            await self.set_default(db, user_id=user_id, credential_id=credential.id)

        return credential

    async def update_credential(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        credential_id: UUID,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        display_name: Optional[str] = None,
        api_base: Optional[str] = None,
        model_override: Optional[str] = None,
        make_default: Optional[bool] = None,
    ) -> UserLlmCredential:
        self._ensure_enabled()
        credential = await self._get_user_credential(db, user_id, credential_id)

        if provider:
            credential.provider = provider.strip().lower() or credential.provider
        if display_name is not None:
            credential.display_name = await self._normalize_display_name(
                db, user_id, display_name, credential.provider, exclude_id=credential.id
            )
        if api_base is not None:
            credential.api_base = api_base.strip() or None
        if model_override is not None:
            credential.model_override = model_override.strip() or None
        if api_key is not None and api_key.strip():
            encrypted_value, last4 = self._vault.encrypt(api_key.strip())
            credential.encrypted_api_key = encrypted_value
            credential.token_last4 = last4

        await commit_safely(db)
        await db.refresh(credential)

        if make_default:
            await self.set_default(db, user_id=user_id, credential_id=credential.id)

        return credential

    async def delete_credential(
        self, db: AsyncSession, *, user_id: UUID, credential_id: UUID
    ) -> None:
        self._ensure_enabled()
        credential = await self._get_user_credential(db, user_id, credential_id)
        credential.soft_delete()
        await commit_safely(db)
        if credential.is_default:
            await self._promote_next_default(db, user_id)

    async def set_default(
        self, db: AsyncSession, *, user_id: UUID, credential_id: UUID
    ) -> UserLlmCredential:
        self._ensure_enabled()
        credential = await self._get_user_credential(db, user_id, credential_id)
        stmt = (
            update(UserLlmCredential)
            .where(
                and_(
                    UserLlmCredential.user_id == user_id,
                    UserLlmCredential.deleted_at.is_(None),
                )
            )
            .values(is_default=False)
        )
        await db.execute(stmt)
        credential.is_default = True
        await commit_safely(db)
        await db.refresh(credential)
        return credential

    # ----------------------
    # Resolution helpers
    # ----------------------
    async def resolve_active_credential(
        self, db: AsyncSession, *, user_id: UUID
    ) -> Optional[ResolvedLlmCredential]:
        if not self.is_enabled():
            return None

        stmt = (
            select(UserLlmCredential)
            .where(
                and_(
                    UserLlmCredential.user_id == user_id,
                    UserLlmCredential.deleted_at.is_(None),
                )
            )
            .order_by(
                UserLlmCredential.is_default.desc(),
                UserLlmCredential.updated_at.desc(),
            )
            .limit(1)
        )
        credential = await db.scalar(stmt)
        if credential is None:
            return None

        try:
            decrypted: DecryptionResult = self._vault.decrypt(
                credential.encrypted_api_key
            )
        except SecretVaultNotConfiguredError as exc:
            logger.error("Failed to decrypt BYOT credential: %s", exc)
            return None

        credential.last_used_at = utc_now()
        await commit_safely(db)

        return ResolvedLlmCredential(
            credential_id=credential.id,
            provider=credential.provider,
            api_key=decrypted.value,
            api_base=credential.api_base,
            model_override=credential.model_override,
            token_last4=credential.token_last4 or decrypted.last4,
        )

    # ----------------------
    # Internal helpers
    # ----------------------
    def _ensure_enabled(self) -> None:
        if not self.is_enabled():
            raise UserLlmCredentialDisabledError(
                "User-provided LLM credentials are disabled"
            )

    def test_credential(
        self,
        *,
        provider: str,
        api_key: str,
        api_base: Optional[str],
        model_override: Optional[str],
    ) -> tuple[bool, str]:
        """Quick connectivity check using the provided BYOT parameters.

        Keep logic minimal to avoid masking real issues—just attempt a tiny
        completion call with the supplied key/base/model.
        """

        self._ensure_enabled()

        client = LLMClient()
        model = (model_override or settings.litellm_model).strip()
        try:
            params = client.build_params(
                messages=[{"role": "user", "content": "ping"}],
                model=model,
                api_key=api_key.strip(),
                api_base=(api_base or "").strip() or None,
                temperature=0.0,
                max_tokens=16,
                timeout=min(settings.litellm_timeout, 15),
            )
            # Provider is carried in the model name for most gateways; avoid
            # custom headers or provider overrides that may break auth.
            litellm.completion(**params)
            return True, "ok"
        except Exception as exc:  # pragma: no cover - pass-through failure
            return False, str(exc)

    async def _normalize_display_name(
        self,
        db: AsyncSession,
        user_id: UUID,
        display_name: Optional[str],
        provider: str,
        *,
        exclude_id: Optional[UUID] = None,
    ) -> str:
        label = (display_name or "").strip()
        if label:
            base_label = label
        else:
            base_label = f"{provider.title()} Token"

        candidate = base_label
        counter = 2
        while await self._label_exists(db, user_id, candidate, exclude_id=exclude_id):
            candidate = f"{base_label} ({counter})"
            counter += 1
        return candidate

    async def _get_user_credential(
        self, db: AsyncSession, user_id: UUID, credential_id: UUID
    ) -> UserLlmCredential:
        stmt = (
            select(UserLlmCredential)
            .where(
                and_(
                    UserLlmCredential.id == credential_id,
                    UserLlmCredential.user_id == user_id,
                    UserLlmCredential.deleted_at.is_(None),
                )
            )
            .limit(1)
        )
        credential = await db.scalar(stmt)
        if credential is None:
            raise UserLlmCredentialNotFoundError("Credential not found")
        return credential

    async def _promote_next_default(self, db: AsyncSession, user_id: UUID) -> None:
        stmt = (
            select(UserLlmCredential)
            .where(
                and_(
                    UserLlmCredential.user_id == user_id,
                    UserLlmCredential.deleted_at.is_(None),
                )
            )
            .order_by(UserLlmCredential.updated_at.desc())
            .limit(1)
        )
        next_candidate = await db.scalar(stmt)
        if next_candidate:
            next_candidate.is_default = True
            await commit_safely(db)

    async def _has_default(self, db: AsyncSession, user_id: UUID) -> bool:
        stmt = (
            select(func.count())
            .select_from(UserLlmCredential)
            .where(
                and_(
                    UserLlmCredential.user_id == user_id,
                    UserLlmCredential.deleted_at.is_(None),
                    UserLlmCredential.is_default.is_(True),
                )
            )
        )
        count = await db.scalar(stmt)
        return (count or 0) > 0

    async def _label_exists(
        self,
        db: AsyncSession,
        user_id: UUID,
        display_name: str,
        *,
        exclude_id: Optional[UUID] = None,
    ) -> bool:
        stmt = (
            select(func.count())
            .select_from(UserLlmCredential)
            .where(
                and_(
                    UserLlmCredential.user_id == user_id,
                    UserLlmCredential.deleted_at.is_(None),
                    UserLlmCredential.display_name == display_name,
                )
            )
        )
        if exclude_id:
            stmt = stmt.where(UserLlmCredential.id != exclude_id)
        count = await db.scalar(stmt)
        return (count or 0) > 0


user_llm_credential_service = UserLlmCredentialService()

__all__ = [
    "user_llm_credential_service",
    "ResolvedLlmCredential",
    "UserLlmCredentialError",
    "UserLlmCredentialNotFoundError",
    "UserLlmCredentialValidationError",
    "UserLlmCredentialDisabledError",
]
