"""Shared logic for A2A runtime builders."""

from __future__ import annotations

from typing import Any, Optional, Type
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.a2a_agent_credential import A2AAgentCredential


class BaseA2ARuntimeBuilder:
    """Base class for building resolved runtime configuration."""

    def __init__(self, vault: Any, validation_error_cls: Type[Exception]) -> None:
        self._vault = vault
        self._validation_error_cls = validation_error_cls

    async def _get_credential(
        self, db: AsyncSession, *, agent_id: UUID
    ) -> Optional[A2AAgentCredential]:
        stmt = select(A2AAgentCredential).where(A2AAgentCredential.agent_id == agent_id)
        return await db.scalar(stmt)
