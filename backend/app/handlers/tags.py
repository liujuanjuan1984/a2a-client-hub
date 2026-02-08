"""
Async implementations for the unified tag handlers.

Routers和其它 async 调用方可以直接使用本模块，避免再通过
``run_with_session`` 桥接同步 Session。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Union
from uuid import UUID

from sqlalchemy import Column, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tag import Tag
from app.db.transaction import commit_safely
from app.handlers.tag_associations import count_tag_usage_for_entity
from app.schemas.tag import (
    VALID_TAG_CATEGORIES,
    TagCategoryOption,
    TagCreate,
    TagUpdate,
)


class TagNotFoundError(Exception):
    """Raised when a tag is not found."""


class TagAlreadyExistsError(Exception):
    """Raised when a tag with the same name and entity type already exists."""


class InvalidEntityTypeError(Exception):
    """Raised when an invalid entity type is provided."""


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


async def create_tag(
    db: AsyncSession, *, user_id: Union[UUID, Column], tag_in: TagCreate
) -> Tag:
    stmt = (
        select(Tag)
        .where(
            Tag.user_id == user_id,
            Tag.name == tag_in.name,
            Tag.entity_type == tag_in.entity_type,
            Tag.category == tag_in.category,
            Tag.deleted_at.is_(None),
        )
        .limit(1)
    )
    existing = (await db.execute(stmt)).scalars().first()
    if existing:
        return existing

    tag = Tag(**tag_in.model_dump(), user_id=user_id)
    db.add(tag)
    await commit_safely(db)
    await db.refresh(tag)
    return tag


async def get_tag(
    db: AsyncSession, *, user_id: Union[UUID, Column], tag_id: UUID
) -> Optional[Tag]:
    stmt = (
        select(Tag)
        .where(
            Tag.user_id == user_id,
            Tag.id == tag_id,
            Tag.deleted_at.is_(None),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


async def list_tags(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    entity_type: Optional[str] = None,
    category: Optional[str] = None,
    name: Optional[str] = None,
) -> List[Tag]:
    stmt = _build_tags_query(
        user_id=user_id,
        entity_type=entity_type,
        category=category,
        name=name,
    )
    stmt = stmt.order_by(Tag.name)
    result = await db.execute(stmt)
    return result.scalars().all()


def _build_tags_query(
    *,
    user_id: Union[UUID, Column],
    entity_type: Optional[str],
    category: Optional[str],
    name: Optional[str],
):
    stmt = select(Tag).where(Tag.user_id == user_id, Tag.deleted_at.is_(None))
    if entity_type is not None:
        stmt = stmt.where(Tag.entity_type == entity_type)
    if category is not None:
        stmt = stmt.where(Tag.category == category)
    if name is not None:
        normalized = name.strip().lower()
        stmt = stmt.where(Tag.name == normalized)
    return stmt


async def list_tags_with_total(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    entity_type: Optional[str] = None,
    category: Optional[str] = None,
    name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[List[Tag], int]:
    stmt = _build_tags_query(
        user_id=user_id,
        entity_type=entity_type,
        category=category,
        name=name,
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    stmt = stmt.order_by(Tag.name).offset(offset).limit(limit)
    result = await db.execute(stmt)
    total = await db.scalar(count_stmt)
    return result.scalars().all(), int(total or 0)


async def update_tag(
    db: AsyncSession,
    *,
    user_id: UUID,
    tag_id: UUID,
    update_in: TagUpdate,
) -> Optional[Tag]:
    stmt = (
        select(Tag)
        .where(
            Tag.user_id == user_id,
            Tag.id == tag_id,
            Tag.deleted_at.is_(None),
        )
        .limit(1)
    )
    tag = (await db.execute(stmt)).scalars().first()
    if tag is None:
        return None

    update_data = update_in.model_dump(exclude_unset=True)
    if "category" in update_data and update_data["category"] is None:
        update_data["category"] = "general"
    if (
        "entity_type" in update_data
        and update_data["entity_type"] not in get_entity_types()
    ):
        raise InvalidEntityTypeError("Unsupported entity type for tag")

    updated_name = update_data.get("name", tag.name)
    updated_entity_type = update_data.get("entity_type", tag.entity_type)
    updated_category = update_data.get("category", tag.category)
    if (
        updated_name != tag.name
        or updated_entity_type != tag.entity_type
        or updated_category != tag.category
    ):
        conflict_stmt = (
            select(Tag.id)
            .where(
                Tag.user_id == user_id,
                Tag.name == updated_name,
                Tag.entity_type == updated_entity_type,
                Tag.category == updated_category,
                Tag.id != tag_id,
                Tag.deleted_at.is_(None),
            )
            .limit(1)
        )
        conflict = (await db.execute(conflict_stmt)).first()
        if conflict:
            raise TagAlreadyExistsError(
                f"A tag with name '{updated_name}' already exists for this entity type and category"
            )

    for field, value in update_data.items():
        setattr(tag, field, value)

    await commit_safely(db)
    await db.refresh(tag)
    return tag


async def delete_tag(
    db: AsyncSession,
    *,
    user_id: UUID,
    tag_id: UUID,
    hard_delete: bool = False,
) -> bool:
    stmt = (
        select(Tag)
        .where(
            Tag.user_id == user_id,
            Tag.id == tag_id,
            Tag.deleted_at.is_(None),
        )
        .limit(1)
    )
    tag = (await db.execute(stmt)).scalars().first()
    if tag is None:
        return False

    if hard_delete:
        await db.delete(tag)
    else:
        tag.soft_delete()

    await commit_safely(db)
    return True


async def get_tag_usage(
    db: AsyncSession, *, user_id: Union[UUID, Column], tag_id: UUID
) -> Optional[Dict]:
    tag = await get_tag(db, user_id=user_id, tag_id=tag_id)
    if tag is None:
        return None

    entity_types = ["person", "note", "task", "vision"]
    usage_stats = {}
    for entity_type in entity_types:
        usage_stats[entity_type] = await count_tag_usage_for_entity(
            db,
            user_id=user_id,
            tag_id=tag_id,
            entity_type=entity_type,
        )

    return {
        "tag_id": tag_id,
        "tag_name": tag.name,
        "entity_type": tag.entity_type,
        "category": tag.category,
        "usage_by_entity_type": usage_stats,
        "total_usage": sum(usage_stats.values()),
    }


def get_entity_types() -> List[str]:
    """Return the list of supported entity types."""
    return ["person", "note", "task", "vision", "general"]


def get_categories() -> List[TagCategoryOption]:
    """Return the list of supported tag categories."""
    return [
        TagCategoryOption(value=category, label=category.replace("_", " ").title())
        for category in VALID_TAG_CATEGORIES
    ]


__all__ = [
    "InvalidEntityTypeError",
    "TagAlreadyExistsError",
    "TagNotFoundError",
    "create_tag",
    "get_tag",
    "list_tags",
    "list_tags_with_total",
    "update_tag",
    "delete_tag",
    "get_tag_usage",
    "get_entity_types",
    "get_categories",
]
