"""Admin maintenance handlers (async)."""

from typing import List, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.task import Task
from app.db.models.vision import Vision
from app.db.transaction import commit_safely
from app.handlers.metrics.effort_async import recompute_subtree_totals

logger = get_logger(__name__)


class AdminMaintenanceError(Exception):
    """Base exception for admin maintenance handlers."""


class ResourceNotFoundError(AdminMaintenanceError):
    """Raised when requested entities do not exist."""


async def _load_active_vision(db: AsyncSession, vision_id: UUID) -> Vision:
    stmt = select(Vision).where(
        Vision.id == vision_id,
        Vision.deleted_at.is_(None),  # type: ignore[attr-defined]
    )
    result = await db.execute(stmt)
    vision = result.scalar_one_or_none()
    if not vision:
        raise ResourceNotFoundError("Vision not found")
    return vision


async def _load_active_task(db: AsyncSession, task_id: UUID) -> Task:
    stmt = select(Task).where(
        Task.id == task_id,
        Task.deleted_at.is_(None),  # type: ignore[attr-defined]
    )
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    if not task:
        raise ResourceNotFoundError("Task not found")
    return task


async def recompute_vision_efforts(
    db: AsyncSession, *, vision_id: UUID
) -> Sequence[UUID]:
    """Recompute accumulated effort metrics for all root tasks under a vision."""

    vision = await _load_active_vision(db, vision_id)

    stmt = select(Task).where(
        Task.vision_id == vision.id,
        Task.parent_task_id.is_(None),
        Task.deleted_at.is_(None),  # type: ignore[attr-defined]
    )
    result = await db.execute(stmt)
    roots: List[Task] = result.scalars().all()

    if not roots:
        logger.info("Vision %s has no root tasks to recompute", vision_id)

    for root in roots:
        await recompute_subtree_totals(db, root.id)

    await commit_safely(db)
    return [task.id for task in roots]


async def recompute_task_efforts(db: AsyncSession, *, task_id: UUID) -> UUID:
    """Recompute accumulated effort metrics for a single task subtree."""

    task = await _load_active_task(db, task_id)
    await recompute_subtree_totals(db, task.id)
    await commit_safely(db)
    return task.id
