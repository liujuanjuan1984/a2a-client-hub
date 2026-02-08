"""Service layer for managing actual event quick templates (async)."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.actual_event_quick_template import ActualEventQuickTemplate
from app.db.transaction import commit_safely
from app.handlers.associations import LinkType, ModelName
from app.handlers.associations_async import attach_persons_for_sources, set_links
from app.schemas.actual_event_quick_template import (
    ActualEventQuickTemplateCreate,
    ActualEventQuickTemplateUpdate,
)
from app.utils.person_utils import convert_persons_to_summary


class ActualEventQuickTemplateAlreadyExistsError(Exception):
    """Raised when a template with the same normalized title already exists."""


class ActualEventQuickTemplateNotFoundError(Exception):
    """Raised when a template cannot be located for the user."""


def _normalize_title(title: str) -> str:
    return title.strip().lower()


def _base_query(user_id: UUID):
    return select(ActualEventQuickTemplate).where(
        ActualEventQuickTemplate.user_id == user_id,
        ActualEventQuickTemplate.deleted_at.is_(None),
    )


async def _get_next_position(db: AsyncSession, user_id: UUID) -> int:
    stmt = select(func.max(ActualEventQuickTemplate.position)).where(
        ActualEventQuickTemplate.user_id == user_id,
        ActualEventQuickTemplate.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    current_max = result.scalar()
    return (current_max or 0) + 1


async def _hydrate_template_persons(
    db: AsyncSession,
    *,
    templates: Sequence[ActualEventQuickTemplate],
    user_id: UUID,
) -> None:
    if not templates:
        return

    await attach_persons_for_sources(
        db,
        source_model=ModelName.ActualEventQuickTemplate,
        items=templates,
        link_type=LinkType.QUICK_TEMPLATE_INVOLVES,
        user_id=user_id,
    )

    for template in templates:
        persons = [
            person
            for person in (getattr(template, "persons", []) or [])
            if getattr(person, "id", None)
        ]
        # 排序保证 person_ids 返回值可预测，方便测试与前端消费。
        ordered_person_ids = sorted(
            (person.id for person in persons), key=lambda value: str(value)
        )
        summary = convert_persons_to_summary(persons)
        template.persons = summary  # type: ignore[attr-defined]
        template.person_ids = ordered_person_ids  # type: ignore[attr-defined]


async def _load_template_with_details(
    db: AsyncSession,
    *,
    user_id: UUID,
    template_id: UUID,
) -> Optional[ActualEventQuickTemplate]:
    stmt = (
        _base_query(user_id)
        .options(selectinload(ActualEventQuickTemplate.dimension))
        .where(ActualEventQuickTemplate.id == template_id)
    )
    template = (await db.execute(stmt)).scalars().first()
    if template:
        await _hydrate_template_persons(db, templates=[template], user_id=user_id)
    return template


async def list_templates(
    db: AsyncSession,
    *,
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
    order_by: str = "position",
) -> Tuple[List[ActualEventQuickTemplate], int]:
    order_clause = {
        "position": (
            ActualEventQuickTemplate.position.asc(),
            ActualEventQuickTemplate.title.asc(),
        ),
        "usage": (
            ActualEventQuickTemplate.usage_count.desc(),
            ActualEventQuickTemplate.last_used_at.desc(),
            ActualEventQuickTemplate.position.asc(),
        ),
        "recent": (
            ActualEventQuickTemplate.last_used_at.desc(),
            ActualEventQuickTemplate.updated_at.desc(),
        ),
    }.get(order_by, (ActualEventQuickTemplate.position.asc(),))

    total_stmt = select(func.count()).select_from(
        select(ActualEventQuickTemplate.id)
        .where(
            ActualEventQuickTemplate.user_id == user_id,
            ActualEventQuickTemplate.deleted_at.is_(None),
        )
        .subquery()
    )
    total = (await db.execute(total_stmt)).scalar_one()

    stmt = (
        _base_query(user_id)
        .options(selectinload(ActualEventQuickTemplate.dimension))
        .order_by(*order_clause)
        .offset(offset)
        .limit(limit)
    )
    items = (await db.execute(stmt)).scalars().all()
    await _hydrate_template_persons(db, templates=items, user_id=user_id)
    return items, total


async def create_template(
    db: AsyncSession,
    *,
    user_id: UUID,
    template_in: ActualEventQuickTemplateCreate,
) -> ActualEventQuickTemplate:
    normalized_title = _normalize_title(template_in.title)
    exists_stmt = _base_query(user_id).where(
        ActualEventQuickTemplate.title_normalized == normalized_title
    )
    existing = await db.execute(exists_stmt)
    if existing.scalars().first():
        raise ActualEventQuickTemplateAlreadyExistsError(
            "Template title already exists for this user"
        )

    position = (
        template_in.position
        if template_in.position is not None
        else await _get_next_position(db, user_id)
    )

    db_template = ActualEventQuickTemplate(
        user_id=user_id,
        title=template_in.title.strip(),
        title_normalized=normalized_title,
        dimension_id=template_in.dimension_id,
        default_duration_minutes=template_in.default_duration_minutes,
        position=position,
        usage_count=template_in.usage_count or 0,
        last_used_at=template_in.last_used_at,
    )

    db.add(db_template)
    await db.flush()

    person_ids = list(template_in.person_ids or [])
    await set_links(
        db,
        source_model=ModelName.ActualEventQuickTemplate,
        source_id=db_template.id,
        target_model=ModelName.Person,
        target_ids=person_ids,
        link_type=LinkType.QUICK_TEMPLATE_INVOLVES,
        replace=True,
        user_id=user_id,
    )

    await commit_safely(db)
    template = await _load_template_with_details(
        db,
        user_id=user_id,
        template_id=db_template.id,
    )
    if not template:
        raise ActualEventQuickTemplateNotFoundError("Template not found")
    return template


async def update_template(
    db: AsyncSession,
    *,
    user_id: UUID,
    template_id: UUID,
    update_in: ActualEventQuickTemplateUpdate,
) -> ActualEventQuickTemplate:
    stmt = (
        _base_query(user_id)
        .options(selectinload(ActualEventQuickTemplate.dimension))
        .where(ActualEventQuickTemplate.id == template_id)
    )
    db_template = (await db.execute(stmt)).scalars().first()
    if not db_template:
        raise ActualEventQuickTemplateNotFoundError("Template not found")

    update_data = update_in.model_dump(exclude_unset=True)

    if "person_ids" in update_data:
        person_ids = update_data.pop("person_ids") or []
        await set_links(
            db,
            source_model=ModelName.ActualEventQuickTemplate,
            source_id=db_template.id,
            target_model=ModelName.Person,
            target_ids=person_ids,
            link_type=LinkType.QUICK_TEMPLATE_INVOLVES,
            replace=True,
            user_id=user_id,
        )

    if "title" in update_data:
        new_title = update_data["title"].strip()
        normalized = _normalize_title(new_title)
        conflict_stmt = _base_query(user_id).where(
            ActualEventQuickTemplate.title_normalized == normalized,
            ActualEventQuickTemplate.id != template_id,
        )
        conflict = (await db.execute(conflict_stmt)).scalars().first()
        if conflict:
            raise ActualEventQuickTemplateAlreadyExistsError(
                "Template title already exists for this user"
            )
        db_template.title = new_title
        db_template.title_normalized = normalized
        update_data.pop("title")

    for field, value in update_data.items():
        setattr(db_template, field, value)

    await commit_safely(db)
    updated = await _load_template_with_details(
        db,
        user_id=user_id,
        template_id=db_template.id,
    )
    if not updated:
        raise ActualEventQuickTemplateNotFoundError("Template not found")
    return updated


async def delete_template(
    db: AsyncSession,
    *,
    user_id: UUID,
    template_id: UUID,
) -> None:
    stmt = (
        update(ActualEventQuickTemplate)
        .where(
            ActualEventQuickTemplate.id == template_id,
            ActualEventQuickTemplate.user_id == user_id,
            ActualEventQuickTemplate.deleted_at.is_(None),
        )
        .values(deleted_at=func.now())
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:
        raise ActualEventQuickTemplateNotFoundError("Template not found")
    await commit_safely(db)


async def reorder_templates(
    db: AsyncSession,
    *,
    user_id: UUID,
    order_pairs: Sequence[Tuple[UUID, int]],
) -> None:
    if not order_pairs:
        return

    template_ids = {tpl_id for tpl_id, _ in order_pairs}
    existing_stmt = _base_query(user_id).where(
        ActualEventQuickTemplate.id.in_(template_ids)
    )
    existing_ids = {tpl.id for tpl in (await db.execute(existing_stmt)).scalars().all()}
    missing = template_ids - existing_ids
    if missing:
        missing_str = ", ".join(str(mid) for mid in missing)
        raise ActualEventQuickTemplateNotFoundError(
            f"Templates not found: {missing_str}"
        )

    for tpl_id, position in order_pairs:
        await db.execute(
            update(ActualEventQuickTemplate)
            .where(
                ActualEventQuickTemplate.id == tpl_id,
                ActualEventQuickTemplate.user_id == user_id,
            )
            .values(position=position)
        )

    await commit_safely(db)


async def bump_template_usage(
    db: AsyncSession,
    *,
    user_id: UUID,
    template_id: UUID,
    when,
) -> ActualEventQuickTemplate:
    stmt = _base_query(user_id).where(ActualEventQuickTemplate.id == template_id)
    db_template = (await db.execute(stmt)).scalars().first()
    if not db_template:
        raise ActualEventQuickTemplateNotFoundError("Template not found")

    db_template.touch_usage(when=when)
    await commit_safely(db)
    updated = await _load_template_with_details(
        db,
        user_id=user_id,
        template_id=db_template.id,
    )
    if not updated:
        raise ActualEventQuickTemplateNotFoundError("Template not found")
    return updated
