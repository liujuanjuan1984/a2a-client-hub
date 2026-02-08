"""
Async equivalents for association helpers.

These implementations mirror the synchronous logic in ``associations.py`` but
operate with SQLAlchemy ``AsyncSession`` so that handlers can avoid
``run_with_session`` bridging during the migration phase.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Set, Union
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.association import Association
from app.db.models.person import Person
from app.db.models.task import Task
from app.handlers.associations import MODEL_MAP, LinkType, ModelName
from app.utils.data_protocol import validate_uuid_field


async def _assert_entities_exist(
    db: AsyncSession,
    model_name: ModelName,
    ids: Iterable[Union[UUID, object]],
    *,
    user_id: Optional[UUID] = None,
) -> Set[UUID]:
    cleaned_ids: List[UUID] = []
    for raw_id in ids:
        try:
            cleaned = validate_uuid_field(raw_id, "entity_id")
            if cleaned is not None:
                cleaned_ids.append(cleaned)
        except ValueError:
            continue

    if not cleaned_ids:
        return set()

    model_cls = MODEL_MAP[model_name]
    stmt = select(model_cls.id).where(model_cls.id.in_(cleaned_ids))
    if hasattr(model_cls, "deleted_at"):
        stmt = stmt.where(getattr(model_cls, "deleted_at").is_(None))
    if user_id is not None and hasattr(model_cls, "user_id"):
        stmt = stmt.where(getattr(model_cls, "user_id") == user_id)

    result = await db.execute(stmt)
    return set(result.scalars().all())


async def get_target_ids_for_sources(
    db: AsyncSession,
    *,
    source_model: ModelName,
    source_ids: Sequence[UUID],
    target_model: ModelName,
    link_type: Optional[LinkType] = None,
    user_id: Optional[UUID] = None,
) -> Dict[UUID, List[UUID]]:
    if not source_ids:
        return {}

    stmt = select(Association.source_id, Association.target_id).where(
        Association.source_model == source_model.value,
        Association.source_id.in_(source_ids),
        Association.target_model == target_model.value,
        Association.deleted_at.is_(None),
    )
    if link_type is not None:
        stmt = stmt.where(Association.link_type == link_type.value)
    if user_id is not None:
        stmt = stmt.where(Association.user_id == user_id)

    rows = await db.execute(stmt)
    mapping: Dict[UUID, List[UUID]] = defaultdict(list)
    for source_id, target_id in rows.all():
        mapping[source_id].append(target_id)
    return mapping


async def get_source_ids_for_target(
    db: AsyncSession,
    *,
    source_model: ModelName,
    target_model: ModelName,
    target_id: UUID,
    link_type: Optional[LinkType] = None,
    user_id: Optional[UUID] = None,
) -> List[UUID]:
    stmt = select(Association.source_id).where(
        Association.source_model == source_model.value,
        Association.target_model == target_model.value,
        Association.target_id == target_id,
        Association.deleted_at.is_(None),
    )
    if link_type is not None:
        stmt = stmt.where(Association.link_type == link_type.value)
    if user_id is not None:
        stmt = stmt.where(Association.user_id == user_id)

    rows = await db.execute(stmt)
    return [row[0] for row in rows.all()]


async def load_persons_for_sources(
    db: AsyncSession,
    *,
    source_model: ModelName,
    source_ids: Sequence[UUID],
    link_type: Optional[LinkType] = None,
    user_id: Optional[UUID] = None,
) -> Dict[UUID, List[Person]]:
    if not source_ids:
        return {}

    link_type_value = (
        link_type.value if link_type is not None else LinkType.IS_ABOUT.value
    )
    mapping = await get_target_ids_for_sources(
        db,
        source_model=source_model,
        source_ids=source_ids,
        target_model=ModelName.Person,
        link_type=LinkType(link_type_value),
        user_id=user_id,
    )
    all_person_ids = {pid for ids in mapping.values() for pid in ids}
    if not all_person_ids:
        return {}

    stmt = (
        select(Person)
        .options(selectinload(Person.tags))
        .where(Person.id.in_(all_person_ids), Person.deleted_at.is_(None))
    )
    if user_id is not None:
        stmt = stmt.where(Person.user_id == user_id)

    persons = (await db.execute(stmt)).scalars().all()
    by_id = {person.id: person for person in persons}
    return {
        sid: [by_id[pid] for pid in ids if pid in by_id] for sid, ids in mapping.items()
    }


async def attach_persons_for_sources(
    db: AsyncSession,
    *,
    source_model: ModelName,
    items: Sequence[object],
    link_type: Optional[LinkType] = None,
    attr_name: str = "persons",
    user_id: Optional[UUID] = None,
) -> None:
    item_ids: List[UUID] = []
    for item in items:
        value = getattr(item, "id", None)
        if isinstance(value, UUID):
            item_ids.append(value)
    if not item_ids:
        return

    mapping = await load_persons_for_sources(
        db,
        source_model=source_model,
        source_ids=item_ids,
        link_type=link_type,
        user_id=user_id,
    )
    for item in items:
        value = getattr(item, "id", None)
        if isinstance(value, UUID):
            setattr(item, attr_name, mapping.get(value, []))


async def recompute_task_notes_count(
    db: AsyncSession,
    task_ids: Set[UUID],
    *,
    user_id: Optional[UUID] = None,
) -> None:
    if not task_ids:
        return

    stmt = (
        select(Association.target_id, func.count(Association.id))
        .where(
            Association.target_id.in_(task_ids),
            Association.target_model == ModelName.Task.value,
            Association.source_model == ModelName.Note.value,
            Association.link_type == LinkType.RELATES_TO.value,
            Association.deleted_at.is_(None),
        )
        .group_by(Association.target_id)
    )
    if user_id is not None:
        stmt = stmt.where(Association.user_id == user_id)

    rows = await db.execute(stmt)
    counts = {task_id: count for task_id, count in rows.all()}

    for task_id in task_ids:
        await db.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(notes_count=counts.get(task_id, 0))
        )


async def set_links(
    db: AsyncSession,
    *,
    source_model: ModelName,
    source_id: Union[UUID, object],
    target_model: ModelName,
    target_ids: Sequence[UUID],
    link_type: LinkType,
    replace: bool = True,
    user_id: Optional[UUID] = None,
) -> None:
    existing_source = await _assert_entities_exist(
        db, source_model, [source_id], user_id=user_id
    )
    if not existing_source:
        raise ValueError(f"Source {source_model}#{source_id} not found")

    valid_target_ids = await _assert_entities_exist(
        db, target_model, target_ids, user_id=user_id
    )

    affected_tasks: Set[UUID] = set()
    needs_task_recompute = (
        source_model == ModelName.Note
        and target_model == ModelName.Task
        and link_type == LinkType.RELATES_TO
    )
    if needs_task_recompute:
        stmt = select(Association.target_id).where(
            Association.source_model == source_model.value,
            Association.source_id == source_id,
            Association.target_model == target_model.value,
            Association.link_type == link_type.value,
            Association.deleted_at.is_(None),
        )
        if user_id is not None:
            stmt = stmt.where(Association.user_id == user_id)
        existing_rows = await db.execute(stmt)
        affected_tasks.update(row[0] for row in existing_rows.all())

    if replace:
        delete_stmt = delete(Association).where(
            Association.source_model == source_model.value,
            Association.source_id == source_id,
            Association.target_model == target_model.value,
        )
        if user_id is not None:
            delete_stmt = delete_stmt.where(Association.user_id == user_id)
        await db.execute(delete_stmt)

    existing_targets: Set[UUID] = set()
    if valid_target_ids and not replace:
        existing_stmt = select(Association.target_id).where(
            Association.source_model == source_model.value,
            Association.source_id == source_id,
            Association.target_model == target_model.value,
            Association.target_id.in_(valid_target_ids),
            Association.link_type == link_type.value,
            Association.deleted_at.is_(None),
        )
        if user_id is not None:
            existing_stmt = existing_stmt.where(Association.user_id == user_id)
        existing_rows = await db.execute(existing_stmt)
        existing_targets = {row[0] for row in existing_rows.all()}

    inserted_targets: Set[UUID] = set()
    for target_id in valid_target_ids:
        if not replace and target_id in existing_targets:
            continue

        db.add(
            Association(
                user_id=user_id,
                source_model=source_model.value,
                source_id=source_id,
                target_model=target_model.value,
                target_id=target_id,
                link_type=link_type.value,
            )
        )
        inserted_targets.add(target_id)

    if needs_task_recompute:
        affected_tasks.update(inserted_targets)
        if affected_tasks:
            await db.flush()
            await recompute_task_notes_count(db, affected_tasks, user_id=user_id)


__all__ = [
    "LinkType",
    "ModelName",
    "attach_persons_for_sources",
    "get_source_ids_for_target",
    "get_target_ids_for_sources",
    "load_persons_for_sources",
    "recompute_task_notes_count",
    "set_links",
]
