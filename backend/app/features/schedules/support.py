"""Shared persistence helpers for A2A schedule services."""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.locking import set_postgres_local_timeouts
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.features.schedules.common import (
    A2AScheduleConflictError,
    A2AScheduleNotFoundError,
    A2AScheduleQuotaError,
    A2AScheduleValidationError,
)


class A2AScheduleSupport:
    """Shared low-level helpers used across schedule domains."""

    _default_write_lock_timeout_ms = 500
    _default_write_statement_timeout_ms = 5000

    async def apply_default_write_timeouts(self, db: AsyncSession) -> None:
        await set_postgres_local_timeouts(
            db,
            lock_timeout_ms=self._default_write_lock_timeout_ms,
            statement_timeout_ms=self._default_write_statement_timeout_ms,
        )

    async def apply_nowait_write_timeouts(self, db: AsyncSession) -> None:
        await set_postgres_local_timeouts(
            db,
            statement_timeout_ms=self._default_write_statement_timeout_ms,
        )

    async def apply_skip_locked_write_timeouts(self, db: AsyncSession) -> None:
        await set_postgres_local_timeouts(
            db,
            statement_timeout_ms=self._default_write_statement_timeout_ms,
        )

    async def lock_user_row_for_quota(self, db: AsyncSession, *, user_id: UUID) -> None:
        lock_key_str = f"a2a_schedule_quota_{user_id.hex}"
        hash_digest = hashlib.md5(lock_key_str.encode()).digest()
        lock_id = int.from_bytes(hash_digest[:8], byteorder="big", signed=True)

        stmt = text("SELECT pg_try_advisory_xact_lock(:lock_id)")
        lock_acquired = await db.scalar(stmt, {"lock_id": lock_id})

        if not lock_acquired:
            raise A2AScheduleConflictError(
                "Unable to acquire advisory lock for schedule quota check. Please try again."
            )

    async def get_task_for_update(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
    ) -> A2AScheduleTask:
        stmt = (
            select(A2AScheduleTask)
            .where(
                and_(
                    A2AScheduleTask.id == task_id,
                    A2AScheduleTask.user_id == user_id,
                    A2AScheduleTask.deleted_at.is_(None),
                    A2AScheduleTask.delete_requested_at.is_(None),
                )
            )
            .with_for_update(nowait=True)
            .limit(1)
        )
        task = await db.scalar(stmt)
        if task is None:
            raise A2AScheduleNotFoundError("Schedule task not found")
        return task

    async def get_task(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
    ) -> A2AScheduleTask:
        stmt = select(A2AScheduleTask).where(
            and_(
                A2AScheduleTask.id == task_id,
                A2AScheduleTask.user_id == user_id,
                A2AScheduleTask.deleted_at.is_(None),
                A2AScheduleTask.delete_requested_at.is_(None),
            )
        )
        task = await db.scalar(stmt)
        if task is None:
            raise A2AScheduleNotFoundError("Schedule task not found")
        return task

    async def ensure_agent_owned(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
    ) -> None:
        stmt = select(A2AAgent.id).where(
            and_(
                A2AAgent.id == agent_id,
                A2AAgent.user_id == user_id,
                A2AAgent.agent_scope == A2AAgent.SCOPE_PERSONAL,
                A2AAgent.enabled.is_(True),
                A2AAgent.deleted_at.is_(None),
            )
        )
        found = await db.scalar(stmt)
        if found is None:
            raise A2AScheduleValidationError(
                "Target agent is missing, disabled, or not owned by current user"
            )

    async def ensure_active_quota(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        is_superuser: bool,
    ) -> None:
        if is_superuser:
            return

        limit = max(settings.a2a_schedule_max_active_tasks_per_user, 0)
        if limit == 0:
            raise A2AScheduleQuotaError(
                "Scheduled tasks are currently disabled for non-admin users."
            )

        stmt = select(func.count(A2AScheduleTask.id)).where(
            and_(
                A2AScheduleTask.user_id == user_id,
                A2AScheduleTask.enabled.is_(True),
                A2AScheduleTask.deleted_at.is_(None),
                A2AScheduleTask.delete_requested_at.is_(None),
            )
        )
        active_count = int((await db.scalar(stmt)) or 0)

        if active_count >= limit:
            raise A2AScheduleQuotaError(
                f"Maximum active schedule tasks limit ({limit}) reached."
            )
