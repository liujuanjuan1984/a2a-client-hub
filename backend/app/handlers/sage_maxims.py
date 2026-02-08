"""Business logic for Sage Maxims (public wisdom quotes)."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.sage_maxim import SageMaxim, SageMaximReaction
from app.db.models.user import User
from app.db.transaction import commit_safely

logger = get_logger(__name__)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50


class SageMaximNotFoundError(Exception):
    """Raised when the requested maxim cannot be found."""


class SageMaximReactionError(Exception):
    """Raised when reaction updates fail."""


def _clamp_page_size(limit: Optional[int]) -> int:
    if not limit or limit <= 0:
        return DEFAULT_PAGE_SIZE
    return min(limit, MAX_PAGE_SIZE)


async def create_sage_maxim(
    db: AsyncSession,
    *,
    author: User,
    content: str,
    language: Optional[str] = None,
) -> SageMaxim:
    """Create a new maxim owned by the given user."""

    trimmed = content.strip()
    if not trimmed:
        raise ValueError("Maxim content cannot be empty")
    if len(trimmed) > 280:
        trimmed = trimmed[:280]

    maxim = SageMaxim(
        user_id=author.id,
        content=trimmed,
        language=language or "zh-CN",
    )
    maxim.author = author
    maxim.refresh_random_weight()

    db.add(maxim)
    await commit_safely(db)
    await db.refresh(maxim)

    return maxim


async def list_sage_maxims(
    db: AsyncSession,
    *,
    viewer_id: UUID,
    sort: str = "random",
    limit: Optional[int] = None,
    offset: int = 0,
) -> Tuple[List[SageMaxim], int, Dict[UUID, str], int]:
    """Return maxims plus viewer reactions for the requested window."""

    base_stmt = select(SageMaxim).where(SageMaxim.deleted_at.is_(None))
    if sort == "latest":
        base_stmt = base_stmt.order_by(SageMaxim.created_at.desc())
    elif sort == "top":
        score = SageMaxim.like_count - SageMaxim.dislike_count
        base_stmt = base_stmt.order_by(score.desc(), SageMaxim.created_at.desc())
    else:
        base_stmt = base_stmt.order_by(func.random())

    count_stmt = (
        select(func.count())
        .select_from(SageMaxim)
        .where(SageMaxim.deleted_at.is_(None))
    )
    total = await db.scalar(count_stmt) or 0
    page_size = _clamp_page_size(limit)
    stmt = base_stmt.offset(max(offset, 0)).limit(page_size)
    result = await db.scalars(stmt)
    items = result.all()

    if not items:
        return [], total, {}, page_size

    maxim_ids = [item.id for item in items]
    if not maxim_ids:
        return [], total, {}, page_size

    reaction_stmt = select(SageMaximReaction).where(
        SageMaximReaction.user_id == viewer_id,
        SageMaximReaction.maxim_id.in_(maxim_ids),
    )
    reaction_result = await db.scalars(reaction_stmt)
    reactions = reaction_result.all()

    reaction_map = {reaction.maxim_id: reaction.reaction_type for reaction in reactions}
    return items, total, reaction_map, page_size


async def _get_maxim_for_update(db: AsyncSession, maxim_id: UUID) -> SageMaxim:
    stmt = (
        select(SageMaxim)
        .where(SageMaxim.id == maxim_id, SageMaxim.deleted_at.is_(None))
        .limit(1)
    )
    maxim = await db.scalar(stmt)
    if maxim is None:
        raise SageMaximNotFoundError(f"Sage maxim {maxim_id} not found")
    return maxim


async def set_reaction(
    db: AsyncSession,
    *,
    maxim_id: UUID,
    user_id: UUID,
    reaction_type: str,
) -> SageMaxim:
    """Create or update a reaction, ensuring counters stay in sync."""

    if reaction_type not in {"like", "dislike"}:
        raise SageMaximReactionError("Unsupported reaction type")

    maxim = await _get_maxim_for_update(db, maxim_id)

    stmt = (
        select(SageMaximReaction)
        .where(
            SageMaximReaction.maxim_id == maxim_id,
            SageMaximReaction.user_id == user_id,
        )
        .limit(1)
    )
    existing = await db.scalar(stmt)

    if existing and existing.reaction_type == reaction_type:
        return maxim

    try:
        if existing:
            existing.reaction_type = reaction_type
        else:
            db.add(
                SageMaximReaction(
                    maxim_id=maxim_id,
                    user_id=user_id,
                    reaction_type=reaction_type,
                )
            )
        await commit_safely(db)
    except IntegrityError as exc:  # pragma: no cover - defensive retry
        await db.rollback()
        logger.warning("Failed to upsert reaction for maxim %s: %s", maxim_id, exc)
        raise SageMaximReactionError("Failed to update reaction") from exc

    await _recompute_reaction_counts(db, maxim)
    return maxim


async def remove_reaction(
    db: AsyncSession,
    *,
    maxim_id: UUID,
    user_id: UUID,
) -> SageMaxim:
    """Remove user's reaction if present and refresh counters."""

    maxim = await _get_maxim_for_update(db, maxim_id)

    delete_stmt = delete(SageMaximReaction).where(
        SageMaximReaction.maxim_id == maxim_id,
        SageMaximReaction.user_id == user_id,
    )
    result = await db.execute(delete_stmt)
    deleted = result.rowcount or 0

    if deleted:
        await commit_safely(db)
        await _recompute_reaction_counts(db, maxim)

    return maxim


async def _recompute_reaction_counts(db: AsyncSession, maxim: SageMaxim) -> None:
    """Recalculate like/dislike counters for the maxim."""

    stats_stmt = (
        select(
            SageMaximReaction.reaction_type,
            func.count(SageMaximReaction.id),
        )
        .where(SageMaximReaction.maxim_id == maxim.id)
        .group_by(SageMaximReaction.reaction_type)
    )
    stats_result = await db.execute(stats_stmt)
    counts = {reaction_type: count for reaction_type, count in stats_result.all()}
    maxim.like_count = counts.get("like", 0)
    maxim.dislike_count = counts.get("dislike", 0)
    await commit_safely(db)
    await db.refresh(maxim)


__all__ = [
    "create_sage_maxim",
    "list_sage_maxims",
    "remove_reaction",
    "set_reaction",
    "SageMaximNotFoundError",
    "SageMaximReactionError",
]
