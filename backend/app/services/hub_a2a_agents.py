"""Service helpers for managing hub (admin-managed) A2A agents and credentials."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence
from uuid import UUID

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_vault import hub_a2a_secret_vault
from app.db.models.hub_a2a_agent import HubA2AAgent
from app.db.models.hub_a2a_agent_allowlist import HubA2AAgentAllowlistEntry
from app.db.models.hub_a2a_agent_credential import HubA2AAgentCredential
from app.db.models.user import User
from app.db.transaction import commit_safely
from app.services.agent_common import (
    encrypt_bearer_token,
    normalize_auth_type,
    normalize_required_text,
    resolve_agent_auth_fields,
)

ALLOWED_AUTH_TYPES = {"none", "bearer"}
ALLOWED_AVAILABILITY_POLICIES = {"public", "allowlist"}


class HubA2AAgentError(RuntimeError):
    """Base error for hub A2A agent management."""


class HubA2AAgentNotFoundError(HubA2AAgentError):
    """Raised when a hub agent cannot be located."""


class HubA2AAgentValidationError(HubA2AAgentError):
    """Raised when hub agent payload validation fails."""


class HubA2AAllowlistConflictError(HubA2AAgentError):
    """Raised when attempting to add a duplicate allowlist entry."""


class HubA2AUserNotFoundError(HubA2AAgentError):
    """Raised when resolving an allowlist user fails."""


@dataclass(frozen=True)
class HubA2AAgentRecord:
    agent: HubA2AAgent
    has_credential: bool
    token_last4: Optional[str]


@dataclass(frozen=True)
class HubA2AAllowlistRecord:
    entry: HubA2AAgentAllowlistEntry
    user_email: Optional[str]
    user_name: Optional[str]


class HubA2AAgentService:
    """Business logic wrapper for hub A2A agent CRUD and credential handling."""

    def __init__(self) -> None:
        self._vault = hub_a2a_secret_vault

    async def list_agents_admin(self, db: AsyncSession) -> List[HubA2AAgentRecord]:
        stmt = (
            select(HubA2AAgent, HubA2AAgentCredential.token_last4)
            .outerjoin(
                HubA2AAgentCredential,
                HubA2AAgentCredential.agent_id == HubA2AAgent.id,
            )
            .where(HubA2AAgent.deleted_at.is_(None))
            .order_by(HubA2AAgent.created_at.asc())
        )
        result = await db.execute(stmt)
        rows = result.all()
        records: list[HubA2AAgentRecord] = []
        for agent, token_last4 in rows:
            records.append(
                HubA2AAgentRecord(
                    agent=agent,
                    has_credential=token_last4 is not None,
                    token_last4=token_last4,
                )
            )
        return records

    async def get_agent_admin(
        self, db: AsyncSession, *, agent_id: UUID
    ) -> HubA2AAgentRecord:
        stmt = (
            select(HubA2AAgent, HubA2AAgentCredential.token_last4)
            .outerjoin(
                HubA2AAgentCredential,
                HubA2AAgentCredential.agent_id == HubA2AAgent.id,
            )
            .where(and_(HubA2AAgent.id == agent_id, HubA2AAgent.deleted_at.is_(None)))
        )
        result = await db.execute(stmt)
        row = result.first()
        if not row:
            raise HubA2AAgentNotFoundError("Hub A2A agent not found")
        agent, token_last4 = row
        return HubA2AAgentRecord(
            agent=agent,
            has_credential=token_last4 is not None,
            token_last4=token_last4,
        )

    async def create_agent_admin(
        self,
        db: AsyncSession,
        *,
        admin_user_id: UUID,
        name: str,
        card_url: str,
        availability_policy: str,
        auth_type: str,
        auth_header: Optional[str],
        auth_scheme: Optional[str],
        enabled: bool,
        tags: Optional[Iterable[str]],
        extra_headers: Optional[Dict[str, str]],
        token: Optional[str],
    ) -> HubA2AAgentRecord:
        normalized_name = self._normalize_name(name)
        normalized_url = self._normalize_card_url(card_url)
        normalized_policy = self._normalize_availability_policy(availability_policy)
        normalized_auth_type = self._normalize_auth_type(auth_type)

        auth_header_value, auth_scheme_value = self._resolve_auth_fields(
            normalized_auth_type, auth_header, auth_scheme, existing=None
        )
        agent = HubA2AAgent(
            name=normalized_name,
            card_url=normalized_url,
            availability_policy=normalized_policy,
            auth_type=normalized_auth_type,
            auth_header=auth_header_value,
            auth_scheme=auth_scheme_value,
            enabled=bool(enabled),
            tags=self._normalize_tags(tags) or None,
            extra_headers=self._normalize_headers(extra_headers) or None,
            created_by_user_id=admin_user_id,
            updated_by_user_id=None,
        )
        db.add(agent)
        await db.flush()

        token_last4: Optional[str] = None
        has_credential = False
        if normalized_auth_type == "none" and token is not None:
            raise HubA2AAgentValidationError("Bearer token provided for auth_type=none")
        if normalized_auth_type == "bearer":
            token_last4 = await self._upsert_credential(
                db,
                admin_user_id=admin_user_id,
                agent_id=agent.id,
                token=token,
            )
            has_credential = True

        await commit_safely(db)
        await db.refresh(agent)
        return HubA2AAgentRecord(
            agent=agent, has_credential=has_credential, token_last4=token_last4
        )

    async def update_agent_admin(
        self,
        db: AsyncSession,
        *,
        admin_user_id: UUID,
        agent_id: UUID,
        name: Optional[str] = None,
        card_url: Optional[str] = None,
        availability_policy: Optional[str] = None,
        auth_type: Optional[str] = None,
        auth_header: Optional[str] = None,
        auth_scheme: Optional[str] = None,
        enabled: Optional[bool] = None,
        tags: Optional[Sequence[str]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        token: Optional[str] = None,
    ) -> HubA2AAgentRecord:
        agent = await self._get_agent(db, agent_id=agent_id)

        if name is not None:
            agent.name = self._normalize_name(name)
        if card_url is not None:
            agent.card_url = self._normalize_card_url(card_url)
        if availability_policy is not None:
            agent.availability_policy = self._normalize_availability_policy(
                availability_policy
            )
        if enabled is not None:
            agent.enabled = bool(enabled)
        if tags is not None:
            agent.tags = self._normalize_tags(tags) or None
        if extra_headers is not None:
            agent.extra_headers = self._normalize_headers(extra_headers) or None

        if auth_type is not None:
            agent.auth_type = self._normalize_auth_type(auth_type)

        auth_header_value, auth_scheme_value = self._resolve_auth_fields(
            agent.auth_type,
            auth_header,
            auth_scheme,
            existing=agent,
        )
        agent.auth_header = auth_header_value
        agent.auth_scheme = auth_scheme_value

        if token is not None and agent.auth_type == "none":
            raise HubA2AAgentValidationError("Bearer token provided for auth_type=none")

        token_last4, has_credential = await self._sync_credentials(
            db,
            admin_user_id=admin_user_id,
            agent=agent,
            token=token,
        )

        agent.updated_by_user_id = admin_user_id
        await commit_safely(db)
        await db.refresh(agent)
        return HubA2AAgentRecord(
            agent=agent,
            has_credential=has_credential,
            token_last4=token_last4,
        )

    async def delete_agent_admin(
        self, db: AsyncSession, *, admin_user_id: UUID, agent_id: UUID
    ) -> None:
        agent = await self._get_agent(db, agent_id=agent_id)
        agent.soft_delete()
        agent.updated_by_user_id = admin_user_id
        # Hub agents are admin-managed, and "delete" should also purge any stored
        # credential/allowlist rows to reduce long-term secret exposure.
        await db.execute(
            delete(HubA2AAgentCredential).where(
                HubA2AAgentCredential.agent_id == agent.id
            )
        )
        await db.execute(
            delete(HubA2AAgentAllowlistEntry).where(
                HubA2AAgentAllowlistEntry.agent_id == agent.id
            )
        )
        await commit_safely(db)

    async def list_visible_agents_for_user(
        self, db: AsyncSession, *, user_id: UUID
    ) -> List[HubA2AAgent]:
        allowlisted_stmt = (
            select(HubA2AAgent.id)
            .join(
                HubA2AAgentAllowlistEntry,
                HubA2AAgentAllowlistEntry.agent_id == HubA2AAgent.id,
            )
            .where(
                and_(
                    HubA2AAgentAllowlistEntry.user_id == user_id,
                    HubA2AAgent.deleted_at.is_(None),
                    HubA2AAgent.enabled.is_(True),
                    HubA2AAgent.availability_policy == "allowlist",
                )
            )
        )
        public_stmt = select(HubA2AAgent.id).where(
            and_(
                HubA2AAgent.deleted_at.is_(None),
                HubA2AAgent.enabled.is_(True),
                HubA2AAgent.availability_policy == "public",
            )
        )
        ids_stmt = select(HubA2AAgent).where(
            and_(
                HubA2AAgent.id.in_(public_stmt.union_all(allowlisted_stmt)),
            )
        )
        result = await db.execute(ids_stmt.order_by(HubA2AAgent.created_at.asc()))
        return list(result.scalars().all())

    async def ensure_visible_for_user(
        self, db: AsyncSession, *, user_id: UUID, agent_id: UUID
    ) -> HubA2AAgent:
        stmt = select(HubA2AAgent).where(
            and_(
                HubA2AAgent.id == agent_id,
                HubA2AAgent.deleted_at.is_(None),
                HubA2AAgent.enabled.is_(True),
            )
        )
        agent = await db.scalar(stmt)
        if agent is None:
            raise HubA2AAgentNotFoundError("Hub A2A agent not found")
        if agent.availability_policy == "public":
            return agent
        if agent.availability_policy != "allowlist":
            raise HubA2AAgentNotFoundError("Hub A2A agent not found")
        allow_stmt = select(HubA2AAgentAllowlistEntry.id).where(
            and_(
                HubA2AAgentAllowlistEntry.agent_id == agent_id,
                HubA2AAgentAllowlistEntry.user_id == user_id,
            )
        )
        allowed = await db.scalar(allow_stmt)
        if allowed is None:
            raise HubA2AAgentNotFoundError("Hub A2A agent not found")
        return agent

    async def list_allowlist_entries_admin(
        self, db: AsyncSession, *, agent_id: UUID
    ) -> List[HubA2AAllowlistRecord]:
        await self._get_agent(db, agent_id=agent_id)
        stmt = (
            select(HubA2AAgentAllowlistEntry, User.email, User.name)
            .join(User, User.id == HubA2AAgentAllowlistEntry.user_id)
            .where(HubA2AAgentAllowlistEntry.agent_id == agent_id)
            .order_by(HubA2AAgentAllowlistEntry.created_at.asc())
        )
        result = await db.execute(stmt)
        rows = result.all()
        return [
            HubA2AAllowlistRecord(entry=row[0], user_email=row[1], user_name=row[2])
            for row in rows
        ]

    async def add_allowlist_entry_admin(
        self,
        db: AsyncSession,
        *,
        admin_user_id: UUID,
        agent_id: UUID,
        user_id: Optional[UUID] = None,
        email: Optional[str] = None,
    ) -> HubA2AAllowlistRecord:
        await self._get_agent(db, agent_id=agent_id)
        resolved_user = await self._resolve_user(db, user_id=user_id, email=email)
        exists_stmt = select(HubA2AAgentAllowlistEntry.id).where(
            and_(
                HubA2AAgentAllowlistEntry.agent_id == agent_id,
                HubA2AAgentAllowlistEntry.user_id == resolved_user.id,
            )
        )
        exists = await db.scalar(exists_stmt)
        if exists is not None:
            raise HubA2AAllowlistConflictError("Allowlist entry already exists")

        entry = HubA2AAgentAllowlistEntry(
            agent_id=agent_id,
            user_id=resolved_user.id,
            created_by_user_id=admin_user_id,
        )
        db.add(entry)
        await commit_safely(db)
        await db.refresh(entry)
        return HubA2AAllowlistRecord(
            entry=entry, user_email=resolved_user.email, user_name=resolved_user.name
        )

    async def remove_allowlist_entry_admin(
        self,
        db: AsyncSession,
        *,
        agent_id: UUID,
        user_id: UUID,
    ) -> None:
        await self._get_agent(db, agent_id=agent_id)
        stmt = delete(HubA2AAgentAllowlistEntry).where(
            and_(
                HubA2AAgentAllowlistEntry.agent_id == agent_id,
                HubA2AAgentAllowlistEntry.user_id == user_id,
            )
        )
        await db.execute(stmt)
        await commit_safely(db)

    async def _get_agent(self, db: AsyncSession, *, agent_id: UUID) -> HubA2AAgent:
        stmt = select(HubA2AAgent).where(
            and_(HubA2AAgent.id == agent_id, HubA2AAgent.deleted_at.is_(None))
        )
        agent = await db.scalar(stmt)
        if agent is None:
            raise HubA2AAgentNotFoundError("Hub A2A agent not found")
        return agent

    async def _get_credential(
        self, db: AsyncSession, *, agent_id: UUID
    ) -> Optional[HubA2AAgentCredential]:
        stmt = select(HubA2AAgentCredential).where(
            HubA2AAgentCredential.agent_id == agent_id
        )
        return await db.scalar(stmt)

    async def _sync_credentials(
        self,
        db: AsyncSession,
        *,
        admin_user_id: UUID,
        agent: HubA2AAgent,
        token: Optional[str],
    ) -> tuple[Optional[str], bool]:
        if agent.auth_type == "none":
            credential = await self._get_credential(db, agent_id=agent.id)
            if credential:
                await db.execute(
                    delete(HubA2AAgentCredential).where(
                        HubA2AAgentCredential.agent_id == agent.id
                    )
                )
            return None, False

        if agent.auth_type != "bearer":
            raise HubA2AAgentValidationError("Unsupported auth_type")

        credential = await self._get_credential(db, agent_id=agent.id)
        if token is None:
            if credential is None:
                raise HubA2AAgentValidationError("Bearer token is required")
            return credential.token_last4, True

        last4 = await self._upsert_credential(
            db,
            admin_user_id=admin_user_id,
            agent_id=agent.id,
            token=token,
        )
        return last4, True

    async def _upsert_credential(
        self,
        db: AsyncSession,
        *,
        admin_user_id: UUID,
        agent_id: UUID,
        token: Optional[str],
    ) -> Optional[str]:
        encrypted_value, last4 = encrypt_bearer_token(
            vault=self._vault,
            token=token,
            validation_error_cls=HubA2AAgentValidationError,
        )

        credential = await self._get_credential(db, agent_id=agent_id)
        if credential is None:
            credential = HubA2AAgentCredential(
                agent_id=agent_id,
                encrypted_token=encrypted_value,
                token_last4=last4,
                encryption_version=1,
                created_by_user_id=admin_user_id,
            )
            db.add(credential)
        else:
            credential.encrypted_token = encrypted_value
            credential.token_last4 = last4
            credential.created_by_user_id = admin_user_id

        return last4

    async def _resolve_user(
        self, db: AsyncSession, *, user_id: Optional[UUID], email: Optional[str]
    ) -> User:
        resolved_user_id = user_id
        if resolved_user_id is None:
            trimmed = (email or "").strip().lower()
            if not trimmed:
                raise HubA2AAgentValidationError("user_id or email is required")
            stmt = select(User).where(
                and_(User.email == trimmed, User.deleted_at.is_(None))
            )
            user = await db.scalar(stmt)
            if user is None:
                raise HubA2AUserNotFoundError("User not found")
            return user

        stmt = select(User).where(
            and_(User.id == resolved_user_id, User.deleted_at.is_(None))
        )
        user = await db.scalar(stmt)
        if user is None:
            raise HubA2AUserNotFoundError("User not found")
        return user

    def _normalize_name(self, value: str) -> str:
        return normalize_required_text(
            value=value,
            field_label="Name",
            validation_error_cls=HubA2AAgentValidationError,
        )

    def _normalize_card_url(self, value: str) -> str:
        return normalize_required_text(
            value=value,
            field_label="Card URL",
            validation_error_cls=HubA2AAgentValidationError,
        )

    def _normalize_auth_type(self, value: str) -> str:
        return normalize_auth_type(
            value=value,
            allowed_auth_types=ALLOWED_AUTH_TYPES,
            validation_error_cls=HubA2AAgentValidationError,
        )

    def _normalize_availability_policy(self, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in ALLOWED_AVAILABILITY_POLICIES:
            raise HubA2AAgentValidationError("Unsupported availability_policy")
        return normalized

    def _resolve_auth_fields(
        self,
        auth_type: str,
        auth_header: Optional[str],
        auth_scheme: Optional[str],
        existing: Optional[HubA2AAgent],
    ) -> tuple[Optional[str], Optional[str]]:
        normalized_header, normalized_scheme = resolve_agent_auth_fields(
            auth_type=auth_type,
            auth_header=auth_header,
            auth_scheme=auth_scheme,
            existing_auth_header=existing.auth_header if existing else None,
            existing_auth_scheme=existing.auth_scheme if existing else None,
            validation_error_cls=HubA2AAgentValidationError,
        )
        return normalized_header, normalized_scheme

    def _normalize_tags(self, value: Optional[Iterable[str]]) -> List[str]:
        if value is None:
            return []
        seen: set[str] = set()
        items: list[str] = []
        for raw in value:
            if raw is None:
                continue
            trimmed = str(raw).strip()
            if not trimmed:
                continue
            lowered = trimmed.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            items.append(trimmed)
        return items

    def _normalize_headers(self, value: Optional[Dict[str, str]]) -> Dict[str, str]:
        if value is None:
            return {}
        normalized: dict[str, str] = {}
        for key, header_value in value.items():
            if key is None:
                continue
            k = str(key).strip()
            if not k:
                continue
            v = "" if header_value is None else str(header_value)
            normalized[k] = v
        return normalized


hub_a2a_agent_service = HubA2AAgentService()

__all__ = [
    "HubA2AAgentService",
    "HubA2AAgentRecord",
    "HubA2AAllowlistRecord",
    "hub_a2a_agent_service",
    "HubA2AAgentError",
    "HubA2AAgentNotFoundError",
    "HubA2AAgentValidationError",
    "HubA2AAllowlistConflictError",
    "HubA2AUserNotFoundError",
]
