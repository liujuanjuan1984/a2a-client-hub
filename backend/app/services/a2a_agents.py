"""
Service helpers for managing user-managed A2A agents and credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_vault import user_llm_secret_vault
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_agent_credential import A2AAgentCredential
from app.db.transaction import commit_safely
from app.services.agent_common import (
    ALLOWED_AUTH_TYPES,
    AgentValidationMixin,
    delete_agent_credentials,
    get_agent_credential,
    upsert_agent_credential,
)


class A2AAgentError(RuntimeError):
    """Base error for A2A agent management."""


class A2AAgentNotFoundError(A2AAgentError):
    """Raised when the requested agent cannot be located."""


class A2AAgentValidationError(A2AAgentError):
    """Raised when payload validation fails."""


@dataclass(frozen=True)
class A2AAgentRecord:
    agent: A2AAgent
    token_last4: Optional[str]


class A2AAgentService(AgentValidationMixin):
    """Business logic wrapper for A2A agent CRUD and credential handling."""

    _validation_error_cls = A2AAgentValidationError
    _allowed_auth_types = ALLOWED_AUTH_TYPES

    def __init__(self) -> None:
        self._vault = user_llm_secret_vault

    async def list_agents(
        self, db: AsyncSession, *, user_id: UUID
    ) -> List[A2AAgentRecord]:
        stmt = (
            select(A2AAgent, A2AAgentCredential.token_last4)
            .outerjoin(
                A2AAgentCredential,
                and_(
                    A2AAgentCredential.agent_id == A2AAgent.id,
                ),
            )
            .where(
                and_(
                    A2AAgent.user_id == user_id,
                    A2AAgent.agent_scope == A2AAgent.SCOPE_PERSONAL,
                    A2AAgent.deleted_at.is_(None),
                )
            )
            .order_by(A2AAgent.created_at.asc())
        )
        result = await db.execute(stmt)
        rows = result.all()
        return [A2AAgentRecord(agent=row[0], token_last4=row[1]) for row in rows]

    async def get_agent(
        self, db: AsyncSession, *, user_id: UUID, agent_id: UUID
    ) -> A2AAgent:
        """Return a single agent owned by the user."""

        return await self._get_agent(db, user_id=user_id, agent_id=agent_id)

    async def create_agent(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        name: str,
        card_url: str,
        auth_type: str,
        auth_header: Optional[str] = None,
        auth_scheme: Optional[str] = None,
        enabled: bool = True,
        tags: Optional[Iterable[str]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        token: Optional[str] = None,
    ) -> A2AAgentRecord:
        normalized_name = self._normalize_name(name)
        normalized_url = self._normalize_card_url(card_url)
        await self._ensure_card_url_unique(db, user_id, normalized_url)

        normalized_auth_type = self._normalize_auth_type(auth_type)
        normalized_tags = self._normalize_tags(tags)
        normalized_headers = self._normalize_headers(extra_headers)

        auth_header_value, auth_scheme_value = self._resolve_auth_fields(
            normalized_auth_type, auth_header, auth_scheme, existing=None
        )

        agent = A2AAgent(
            user_id=user_id,
            name=normalized_name,
            card_url=normalized_url,
            agent_scope=A2AAgent.SCOPE_PERSONAL,
            availability_policy="public",
            auth_type=normalized_auth_type,
            auth_header=auth_header_value,
            auth_scheme=auth_scheme_value,
            enabled=enabled,
            tags=normalized_tags or None,
            extra_headers=normalized_headers or None,
        )
        db.add(agent)
        await db.flush()

        token_last4: Optional[str] = None
        if normalized_auth_type == "none" and token is not None:
            raise A2AAgentValidationError("Bearer token provided for auth_type=none")
        if normalized_auth_type == "bearer":
            token_last4 = await self._upsert_credential(
                db,
                user_id=user_id,
                agent_id=agent.id,
                token=token,
            )

        await commit_safely(db)
        await db.refresh(agent)
        return A2AAgentRecord(agent=agent, token_last4=token_last4)

    async def update_agent(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
        name: Optional[str] = None,
        card_url: Optional[str] = None,
        auth_type: Optional[str] = None,
        auth_header: Optional[str] = None,
        auth_scheme: Optional[str] = None,
        enabled: Optional[bool] = None,
        tags: Optional[Iterable[str]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        token: Optional[str] = None,
    ) -> A2AAgentRecord:
        agent = await self._get_agent(db, user_id=user_id, agent_id=agent_id)

        if name is not None:
            agent.name = self._normalize_name(name)
        if card_url is not None:
            normalized_url = self._normalize_card_url(card_url)
            await self._ensure_card_url_unique(
                db, user_id, normalized_url, exclude_id=agent.id
            )
            agent.card_url = normalized_url

        if enabled is not None:
            agent.enabled = enabled

        if tags is not None:
            normalized_tags = self._normalize_tags(tags)
            agent.tags = normalized_tags or None

        if extra_headers is not None:
            normalized_headers = self._normalize_headers(extra_headers)
            agent.extra_headers = normalized_headers or None

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
            raise A2AAgentValidationError("Bearer token provided for auth_type=none")

        token_last4: Optional[str] = await self._sync_credentials(
            db,
            user_id=user_id,
            agent=agent,
            token=token,
        )

        await commit_safely(db)
        await db.refresh(agent)
        return A2AAgentRecord(agent=agent, token_last4=token_last4)

    async def delete_agent(
        self, db: AsyncSession, *, user_id: UUID, agent_id: UUID
    ) -> None:
        agent = await self._get_agent(db, user_id=user_id, agent_id=agent_id)
        agent.soft_delete()
        await delete_agent_credentials(db, agent_id=agent.id)
        await commit_safely(db)

    # ----------------------
    # Internal helpers
    # ----------------------
    async def _get_agent(
        self, db: AsyncSession, *, user_id: UUID, agent_id: UUID
    ) -> A2AAgent:
        stmt = select(A2AAgent).where(
            and_(
                A2AAgent.id == agent_id,
                A2AAgent.user_id == user_id,
                A2AAgent.agent_scope == A2AAgent.SCOPE_PERSONAL,
                A2AAgent.deleted_at.is_(None),
            )
        )
        agent = await db.scalar(stmt)
        if agent is None:
            raise A2AAgentNotFoundError("A2A agent not found")
        return agent

    async def _ensure_card_url_unique(
        self,
        db: AsyncSession,
        user_id: UUID,
        card_url: str,
        exclude_id: Optional[UUID] = None,
    ) -> None:
        stmt = select(A2AAgent.id).where(
            and_(
                A2AAgent.user_id == user_id,
                A2AAgent.agent_scope == A2AAgent.SCOPE_PERSONAL,
                A2AAgent.card_url == card_url,
                A2AAgent.deleted_at.is_(None),
            )
        )
        if exclude_id:
            stmt = stmt.where(A2AAgent.id != exclude_id)
        existing = await db.scalar(stmt)
        if existing is not None:
            raise A2AAgentValidationError("Agent card URL already exists")

    async def _sync_credentials(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent: A2AAgent,
        token: Optional[str],
    ) -> Optional[str]:
        if agent.auth_type == "none":
            await delete_agent_credentials(db, agent_id=agent.id)
            return None

        if agent.auth_type != "bearer":
            raise A2AAgentValidationError("Unsupported auth_type")

        credential = await get_agent_credential(db, agent_id=agent.id)
        if token is None:
            if credential is None:
                raise A2AAgentValidationError("Bearer token is required")
            return credential.token_last4

        return await self._upsert_credential(
            db,
            user_id=user_id,
            agent_id=agent.id,
            token=token,
        )

    async def _upsert_credential(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
        token: Optional[str],
    ) -> Optional[str]:
        return await upsert_agent_credential(
            db,
            vault=self._vault,
            agent_id=agent_id,
            user_id=user_id,
            token=token,
            validation_error_cls=A2AAgentValidationError,
        )

    def _normalize_tags(self, tags: Optional[Iterable[str]]) -> List[str]:
        if tags is None:
            return []
        normalized: List[str] = []
        for tag in tags:
            if tag is None:
                continue
            value = str(tag).strip()
            if value:
                normalized.append(value)
        return normalized

    def _normalize_headers(self, headers: Optional[Dict[str, str]]) -> Dict[str, str]:
        if headers is None:
            return {}
        if not isinstance(headers, dict):
            raise A2AAgentValidationError("extra_headers must be a dictionary")
        normalized: Dict[str, str] = {}
        for key, value in headers.items():
            if key is None:
                continue
            header_key = str(key).strip()
            if not header_key:
                raise A2AAgentValidationError("extra_headers contains empty key")
            header_value = "" if value is None else str(value).strip()
            normalized[header_key] = header_value
        return normalized


a2a_agent_service = A2AAgentService()

__all__ = [
    "A2AAgentError",
    "A2AAgentNotFoundError",
    "A2AAgentValidationError",
    "A2AAgentRecord",
    "a2a_agent_service",
]
