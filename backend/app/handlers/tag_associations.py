"""
Tag association helpers backed by ``AsyncSession``.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, Optional, Sequence, Set
from uuid import UUID

from sqlalchemy import and_, delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.note import Note
from app.db.models.person import Person
from app.db.models.tag import Tag
from app.db.models.tag_associations import tag_associations
from app.db.models.task import Task
from app.db.models.vision import Vision

ExceptionFactory = Optional[Callable[[], Exception]]


def _raise(factory: ExceptionFactory, default_message: str) -> None:
    if factory is not None:
        raise factory()
    raise RuntimeError(default_message)


async def _fetch_allowed_tag_ids(
    db: AsyncSession,
    *,
    user_id: UUID,
    tag_ids: Iterable[UUID],
    tag_entity_type: Optional[str],
) -> Set[UUID]:
    ids = [UUID(str(tag_id)) for tag_id in tag_ids]
    if not ids:
        return set()

    stmt = select(Tag.id).where(
        Tag.id.in_(ids),
        Tag.user_id == user_id,
        Tag.deleted_at.is_(None),
    )
    if tag_entity_type is not None:
        stmt = stmt.where(Tag.entity_type == tag_entity_type)

    rows = await db.execute(stmt)
    return set(rows.scalars().all())


async def sync_entity_tags(
    db: AsyncSession,
    *,
    user_id: UUID,
    entity_id: UUID,
    entity_type: str,
    desired_tag_ids: Sequence[UUID],
    tag_entity_type: Optional[str] = None,
    skip_missing: bool = True,
    missing_tag_error: ExceptionFactory = None,
) -> None:
    allowed_ids = await _fetch_allowed_tag_ids(
        db,
        user_id=user_id,
        tag_ids=desired_tag_ids,
        tag_entity_type=tag_entity_type,
    )
    missing = set(map(UUID, map(str, desired_tag_ids))) - allowed_ids
    if missing and not skip_missing:
        _raise(missing_tag_error, "One or more tags are invalid")

    delete_stmt = delete(tag_associations).where(
        and_(
            tag_associations.c.entity_id == entity_id,
            tag_associations.c.entity_type == entity_type,
        )
    )
    await db.execute(delete_stmt)

    if not allowed_ids:
        return

    payload = [
        {"entity_id": entity_id, "entity_type": entity_type, "tag_id": tag_id}
        for tag_id in allowed_ids
    ]
    await db.execute(insert(tag_associations), payload)


async def add_tag_association(
    db: AsyncSession,
    *,
    user_id: UUID,
    entity_id: UUID,
    entity_type: str,
    tag_id: UUID,
    tag_entity_type: Optional[str] = None,
    missing_tag_error: ExceptionFactory = None,
    duplicate_error: ExceptionFactory = None,
) -> None:
    allowed = await _fetch_allowed_tag_ids(
        db,
        user_id=user_id,
        tag_ids=[tag_id],
        tag_entity_type=tag_entity_type,
    )
    canonical_id = UUID(str(tag_id))
    if canonical_id not in allowed:
        _raise(missing_tag_error, "Tag not found or inaccessible")

    exists_stmt = select(tag_associations.c.entity_id).where(
        tag_associations.c.entity_id == entity_id,
        tag_associations.c.entity_type == entity_type,
        tag_associations.c.tag_id == canonical_id,
    )
    existing = await db.execute(exists_stmt.limit(1))
    if existing.first():
        _raise(duplicate_error, "Tag already associated")

    await db.execute(
        insert(tag_associations).values(
            entity_id=entity_id,
            entity_type=entity_type,
            tag_id=canonical_id,
        )
    )


async def remove_tag_association(
    db: AsyncSession,
    *,
    user_id: UUID,
    entity_id: UUID,
    entity_type: str,
    tag_id: UUID,
    tag_entity_type: Optional[str] = None,
    missing_tag_error: ExceptionFactory = None,
    not_associated_error: ExceptionFactory = None,
) -> None:
    allowed = await _fetch_allowed_tag_ids(
        db,
        user_id=user_id,
        tag_ids=[tag_id],
        tag_entity_type=tag_entity_type,
    )
    canonical_id = UUID(str(tag_id))
    if canonical_id not in allowed:
        _raise(missing_tag_error, "Tag not found or inaccessible")

    delete_stmt = delete(tag_associations).where(
        and_(
            tag_associations.c.entity_id == entity_id,
            tag_associations.c.entity_type == entity_type,
            tag_associations.c.tag_id == canonical_id,
        )
    )
    result = await db.execute(delete_stmt)
    if result.rowcount == 0:
        _raise(not_associated_error, "Tag not associated with entity")


_ENTITY_MODEL_MAP: Dict[str, type] = {
    "person": Person,
    "note": Note,
    "task": Task,
    "vision": Vision,
}


async def count_tag_usage_for_entity(
    db: AsyncSession,
    *,
    user_id: UUID,
    tag_id: UUID,
    entity_type: str,
) -> int:
    model = _ENTITY_MODEL_MAP.get(entity_type)
    if model is None:
        return 0

    canonical_tag_id = UUID(str(tag_id))
    join_condition = model.id == tag_associations.c.entity_id

    filters = [
        tag_associations.c.tag_id == canonical_tag_id,
        tag_associations.c.entity_type == entity_type,
        model.user_id == user_id,
    ]
    if hasattr(model, "deleted_at"):
        filters.append(model.deleted_at.is_(None))

    stmt = (
        select(func.count())
        .select_from(tag_associations.join(model, join_condition))
        .where(*filters)
    )
    result = await db.execute(stmt)
    count = result.scalar()
    return int(count or 0)


__all__ = [
    "add_tag_association",
    "count_tag_usage_for_entity",
    "remove_tag_association",
    "sync_entity_tags",
]
