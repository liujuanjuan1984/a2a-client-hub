"""Hub A2A agent feature service and credential helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, cast
from uuid import UUID

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_vault import hub_a2a_secret_vault
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_agent_credential import A2AAgentCredential
from app.db.models.hub_a2a_agent_allowlist import HubA2AAgentAllowlistEntry
from app.db.models.user import User
from app.db.transaction import commit_safely
from app.features.agents_shared.common import (
    ALLOWED_AUTH_TYPES,
    ALLOWED_AVAILABILITY_POLICIES,
    AgentValidationMixin,
    delete_agent_credentials,
    get_agent_credential,
    upsert_agent_credential,
)


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
    id: UUID
    name: str
    card_url: str
    availability_policy: str
    auth_type: str
    auth_header: str | None
    auth_scheme: str | None
    enabled: bool
    tags: list[str]
    extra_headers: dict[str, str]
    has_credential: bool
    token_last4: Optional[str]
    created_by_user_id: UUID | None
    updated_by_user_id: UUID | None
    created_at: object
    updated_at: object


@dataclass(frozen=True)
class HubA2AAllowlistRecord:
    id: UUID
    agent_id: UUID
    user_id: UUID
    user_email: Optional[str]
    user_name: Optional[str]
    created_by_user_id: UUID
    created_at: object


class HubA2AAgentService(AgentValidationMixin):
    """Business logic wrapper for hub A2A agent CRUD and credential handling."""

    _validation_error_cls = HubA2AAgentValidationError
    _allowed_auth_types = ALLOWED_AUTH_TYPES

    def __init__(self) -> None:
        self._vault = hub_a2a_secret_vault

    @staticmethod
    def _build_agent_record(
        agent: A2AAgent,
        *,
        has_credential: bool,
        token_last4: Optional[str],
    ) -> HubA2AAgentRecord:
        return HubA2AAgentRecord(
            id=cast(UUID, agent.id),
            name=cast(str, agent.name),
            card_url=cast(str, agent.card_url),
            availability_policy=cast(str, agent.availability_policy),
            auth_type=cast(str, agent.auth_type),
            auth_header=cast(str | None, agent.auth_header),
            auth_scheme=cast(str | None, agent.auth_scheme),
            enabled=bool(getattr(agent, "enabled", True)),
            tags=cast(list[str], agent.tags or []),
            extra_headers=cast(dict[str, str], agent.extra_headers or {}),
            has_credential=has_credential,
            token_last4=token_last4,
            created_by_user_id=cast(UUID | None, agent.created_by_user_id),
            updated_by_user_id=cast(UUID | None, agent.updated_by_user_id),
            created_at=cast(object, agent.created_at),
            updated_at=cast(object, agent.updated_at),
        )

    @staticmethod
    def _build_allowlist_record(
        entry: HubA2AAgentAllowlistEntry,
        *,
        user_email: Optional[str],
        user_name: Optional[str],
    ) -> HubA2AAllowlistRecord:
        return HubA2AAllowlistRecord(
            id=cast(UUID, entry.id),
            agent_id=cast(UUID, entry.agent_id),
            user_id=cast(UUID, entry.user_id),
            user_email=user_email,
            user_name=user_name,
            created_by_user_id=cast(UUID, entry.created_by_user_id),
            created_at=cast(object, entry.created_at),
        )

    async def list_agents_admin(
        self, db: AsyncSession, *, page: int, size: int
    ) -> tuple[list[HubA2AAgentRecord], int]:
        offset = (page - 1) * size
        base_stmt = (
            select(A2AAgent, A2AAgentCredential.token_last4)
            .outerjoin(
                A2AAgentCredential,
                A2AAgentCredential.agent_id == A2AAgent.id,
            )
            .where(
                and_(
                    A2AAgent.agent_scope == A2AAgent.SCOPE_SHARED,
                    A2AAgent.deleted_at.is_(None),
                )
            )
        )
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        stmt = (
            base_stmt.order_by(A2AAgent.created_at.asc(), A2AAgent.id.asc())
            .offset(offset)
            .limit(size)
        )
        result = await db.execute(stmt)
        rows = result.all()
        total = await db.scalar(count_stmt)
        records: list[HubA2AAgentRecord] = []
        for agent, token_last4 in rows:
            records.append(
                self._build_agent_record(
                    cast(A2AAgent, agent),
                    has_credential=token_last4 is not None,
                    token_last4=cast(str | None, token_last4),
                )
            )
        return records, int(total or 0)

    async def get_agent_admin(
        self, db: AsyncSession, *, agent_id: UUID
    ) -> HubA2AAgentRecord:
        stmt = (
            select(A2AAgent, A2AAgentCredential.token_last4)
            .outerjoin(
                A2AAgentCredential,
                A2AAgentCredential.agent_id == A2AAgent.id,
            )
            .where(
                and_(
                    A2AAgent.id == agent_id,
                    A2AAgent.agent_scope == A2AAgent.SCOPE_SHARED,
                    A2AAgent.deleted_at.is_(None),
                )
            )
        )
        result = await db.execute(stmt)
        row = result.first()
        if not row:
            raise HubA2AAgentNotFoundError("Hub A2A agent not found")
        agent, token_last4 = row
        return self._build_agent_record(
            cast(A2AAgent, agent),
            has_credential=token_last4 is not None,
            token_last4=cast(str | None, token_last4),
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
        agent = A2AAgent(
            user_id=admin_user_id,
            name=normalized_name,
            card_url=normalized_url,
            agent_scope=A2AAgent.SCOPE_SHARED,
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
                agent_id=cast(UUID, agent.id),
                token=token,
            )
            has_credential = True

        await commit_safely(db)
        await db.refresh(agent)
        return self._build_agent_record(
            agent,
            has_credential=has_credential,
            token_last4=token_last4,
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
            setattr(agent, "name", self._normalize_name(name))
        if card_url is not None:
            setattr(agent, "card_url", self._normalize_card_url(card_url))
        if availability_policy is not None:
            setattr(
                agent,
                "availability_policy",
                self._normalize_availability_policy(availability_policy),
            )
        if enabled is not None:
            setattr(agent, "enabled", bool(enabled))
        if tags is not None:
            setattr(agent, "tags", self._normalize_tags(tags) or None)
        if extra_headers is not None:
            setattr(
                agent, "extra_headers", self._normalize_headers(extra_headers) or None
            )

        if auth_type is not None:
            setattr(agent, "auth_type", self._normalize_auth_type(auth_type))

        auth_header_value, auth_scheme_value = self._resolve_auth_fields(
            cast(str, agent.auth_type),
            auth_header,
            auth_scheme,
            existing=agent,
        )
        setattr(agent, "auth_header", auth_header_value)
        setattr(agent, "auth_scheme", auth_scheme_value)

        if token is not None and cast(str, agent.auth_type) == "none":
            raise HubA2AAgentValidationError("Bearer token provided for auth_type=none")

        token_last4, has_credential = await self._sync_credentials(
            db,
            admin_user_id=admin_user_id,
            agent=agent,
            token=token,
        )

        setattr(agent, "updated_by_user_id", admin_user_id)
        await commit_safely(db)
        await db.refresh(agent)
        return self._build_agent_record(
            agent,
            has_credential=has_credential,
            token_last4=token_last4,
        )

    async def delete_agent_admin(
        self, db: AsyncSession, *, admin_user_id: UUID, agent_id: UUID
    ) -> None:
        agent = await self._get_agent(db, agent_id=agent_id)
        agent.soft_delete()
        setattr(agent, "updated_by_user_id", admin_user_id)
        # Hub agents are admin-managed, and "delete" should also purge any stored
        # credential/allowlist rows to reduce long-term secret exposure.
        agent_pk = cast(UUID, agent.id)
        await delete_agent_credentials(db, agent_id=agent_pk)
        await db.execute(
            delete(HubA2AAgentAllowlistEntry).where(
                HubA2AAgentAllowlistEntry.agent_id == agent_pk
            )
        )
        await commit_safely(db)

    @staticmethod
    def _build_visible_agent_ids_subquery(user_id: UUID) -> Any:
        allowlisted_stmt = (
            select(A2AAgent.id)
            .join(
                HubA2AAgentAllowlistEntry,
                HubA2AAgentAllowlistEntry.agent_id == A2AAgent.id,
            )
            .where(
                and_(
                    HubA2AAgentAllowlistEntry.user_id == user_id,
                    A2AAgent.agent_scope == A2AAgent.SCOPE_SHARED,
                    A2AAgent.deleted_at.is_(None),
                    A2AAgent.enabled.is_(True),
                    A2AAgent.availability_policy == "allowlist",
                )
            )
        )
        public_stmt = select(A2AAgent.id).where(
            and_(
                A2AAgent.agent_scope == A2AAgent.SCOPE_SHARED,
                A2AAgent.deleted_at.is_(None),
                A2AAgent.enabled.is_(True),
                A2AAgent.availability_policy == "public",
            )
        )
        return public_stmt.union(allowlisted_stmt).subquery()

    async def list_all_visible_agents_for_user(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
    ) -> list[A2AAgent]:
        visible_ids = self._build_visible_agent_ids_subquery(user_id)
        items_stmt = (
            select(A2AAgent)
            .join(visible_ids, visible_ids.c.id == A2AAgent.id)
            .where(A2AAgent.agent_scope == A2AAgent.SCOPE_SHARED)
            .order_by(A2AAgent.created_at.desc(), A2AAgent.id.desc())
        )
        result = await db.execute(items_stmt)
        return list(result.scalars().all())

    async def list_visible_agents_for_user(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        page: int,
        size: int,
    ) -> tuple[List[A2AAgent], int]:
        visible_ids = self._build_visible_agent_ids_subquery(user_id)
        total_stmt = select(func.count()).select_from(visible_ids)
        total = int((await db.execute(total_stmt)).scalar() or 0)
        offset = max(page - 1, 0) * size
        items_stmt = (
            select(A2AAgent)
            .join(visible_ids, visible_ids.c.id == A2AAgent.id)
            .where(A2AAgent.agent_scope == A2AAgent.SCOPE_SHARED)
            .order_by(A2AAgent.created_at.desc(), A2AAgent.id.desc())
            .offset(offset)
            .limit(size)
        )
        result = await db.execute(items_stmt)
        return list(result.scalars().all()), total

    async def ensure_visible_for_user(
        self, db: AsyncSession, *, user_id: UUID, agent_id: UUID
    ) -> A2AAgent:
        stmt = select(A2AAgent).where(
            and_(
                A2AAgent.id == agent_id,
                A2AAgent.agent_scope == A2AAgent.SCOPE_SHARED,
                A2AAgent.deleted_at.is_(None),
                A2AAgent.enabled.is_(True),
            )
        )
        agent = cast(A2AAgent | None, await db.scalar(stmt))
        if agent is None:
            raise HubA2AAgentNotFoundError("Hub A2A agent not found")
        availability_policy = cast(str, agent.availability_policy)
        if availability_policy == "public":
            return agent
        if availability_policy != "allowlist":
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
            self._build_allowlist_record(
                cast(HubA2AAgentAllowlistEntry, row[0]),
                user_email=cast(str | None, row[1]),
                user_name=cast(str | None, row[2]),
            )
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
        return self._build_allowlist_record(
            entry,
            user_email=cast(str | None, resolved_user.email),
            user_name=cast(str | None, resolved_user.name),
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

    async def replace_allowlist_entries_admin(
        self,
        db: AsyncSession,
        *,
        admin_user_id: UUID,
        agent_id: UUID,
        entries: Sequence[dict[str, Optional[UUID | str]]],
    ) -> List[HubA2AAllowlistRecord]:
        await self._get_agent(db, agent_id=agent_id)

        resolved_users: list[User] = []
        seen_user_ids: set[UUID] = set()
        for item in entries:
            raw_user_id = item.get("user_id")
            resolved_user_id = raw_user_id if isinstance(raw_user_id, UUID) else None
            raw_email = item.get("email")
            resolved_email = raw_email if isinstance(raw_email, str) else None
            user = await self._resolve_user(
                db,
                user_id=resolved_user_id,
                email=resolved_email,
            )
            user_id_value = cast(UUID, user.id)
            if user_id_value in seen_user_ids:
                continue
            seen_user_ids.add(user_id_value)
            resolved_users.append(user)

        await db.execute(
            delete(HubA2AAgentAllowlistEntry).where(
                HubA2AAgentAllowlistEntry.agent_id == agent_id
            )
        )
        for user in resolved_users:
            db.add(
                HubA2AAgentAllowlistEntry(
                    agent_id=agent_id,
                    user_id=cast(UUID, user.id),
                    created_by_user_id=admin_user_id,
                )
            )
        await commit_safely(db)
        return await self.list_allowlist_entries_admin(db, agent_id=agent_id)

    async def _get_agent(self, db: AsyncSession, *, agent_id: UUID) -> A2AAgent:
        stmt = select(A2AAgent).where(
            and_(
                A2AAgent.id == agent_id,
                A2AAgent.agent_scope == A2AAgent.SCOPE_SHARED,
                A2AAgent.deleted_at.is_(None),
            )
        )
        agent = cast(A2AAgent | None, await db.scalar(stmt))
        if agent is None:
            raise HubA2AAgentNotFoundError("Hub A2A agent not found")
        return agent

    async def _sync_credentials(
        self,
        db: AsyncSession,
        *,
        admin_user_id: UUID,
        agent: A2AAgent,
        token: Optional[str],
    ) -> tuple[Optional[str], bool]:
        auth_type = cast(str, agent.auth_type)
        agent_id = cast(UUID, agent.id)
        if auth_type == "none":
            await delete_agent_credentials(db, agent_id=agent_id)
            return None, False

        if auth_type != "bearer":
            raise HubA2AAgentValidationError("Unsupported auth_type")

        credential = await get_agent_credential(db, agent_id=agent_id)
        if token is None:
            if credential is None:
                raise HubA2AAgentValidationError("Bearer token is required")
            return cast(str | None, credential.token_last4), True

        last4 = await self._upsert_credential(
            db,
            admin_user_id=admin_user_id,
            agent_id=agent_id,
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
        return await upsert_agent_credential(
            db,
            vault=self._vault,
            agent_id=agent_id,
            user_id=admin_user_id,
            token=token,
            validation_error_cls=HubA2AAgentValidationError,
        )

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
            user = cast(User | None, await db.scalar(stmt))
            if user is None:
                raise HubA2AUserNotFoundError("User not found")
            return user

        stmt = select(User).where(
            and_(User.id == resolved_user_id, User.deleted_at.is_(None))
        )
        user = cast(User | None, await db.scalar(stmt))
        if user is None:
            raise HubA2AUserNotFoundError("User not found")
        return user

    def _normalize_availability_policy(self, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in ALLOWED_AVAILABILITY_POLICIES:
            raise HubA2AAgentValidationError("Unsupported availability_policy")
        return normalized

    def _normalize_tags(self, value: Optional[Iterable[str]]) -> List[str]:
        if value is None:
            return []
        seen: set[str] = set()
        items: list[str] = []
        for raw in value:
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
