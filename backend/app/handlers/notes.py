"""Async helpers for note CRUD and batch operations."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.db.models.actual_event import ActualEvent
from app.db.models.association import Association
from app.db.models.note import Note
from app.db.models.person import Person
from app.db.models.tag import Tag
from app.db.models.tag_associations import tag_associations
from app.db.models.task import Task
from app.db.transaction import commit_safely
from app.handlers.associations import LinkType, ModelName
from app.handlers.associations_async import (
    get_target_ids_for_sources,
    load_persons_for_sources,
    recompute_task_notes_count,
    set_links,
)
from app.handlers.notes_exceptions import (
    InvalidOperationError,
    NoteNotFoundError,
    TagAlreadyAssociatedError,
    TagNotAssociatedError,
    TagNotFoundError,
)
from app.handlers.tag_associations import (
    add_tag_association,
    remove_tag_association,
    sync_entity_tags,
)
from app.schemas.note import (
    NoteAdvancedSearchRequest,
    NoteBatchContentUpdate,
    NoteBatchDeleteRequest,
    NoteBatchDeleteResponse,
    NoteBatchPersonUpdate,
    NoteBatchTagUpdate,
    NoteBatchTaskUpdate,
    NoteBatchUpdateRequest,
    NoteBatchUpdateResponse,
    NoteCreate,
    NoteUpdate,
)
from app.utils.timezone_util import utc_now

logger = get_logger(__name__)


def _active_note_filters(user_id: UUID):
    return [
        Note.user_id == user_id,
        Note.deleted_at.is_(None),
    ]


async def _load_note(
    db: AsyncSession,
    *,
    user_id: UUID,
    note_id: UUID,
    with_tags: bool = False,
) -> Note:
    stmt = select(Note).where(*_active_note_filters(user_id), Note.id == note_id)
    if with_tags:
        stmt = stmt.options(selectinload(Note.tags))
    result = await db.execute(stmt.limit(1))
    note = result.scalars().first()
    if note is None:
        raise NoteNotFoundError("Note not found")
    return note


async def create_note(
    db: AsyncSession,
    *,
    user_id: UUID,
    note_in: NoteCreate,
) -> Note:
    data = note_in.model_dump()
    person_ids = data.pop("person_ids", None)
    tag_ids = data.pop("tag_ids", None)
    task_id = data.pop("task_id", None)
    event_ids = data.pop("actual_event_ids", None)

    note = Note(**data, user_id=user_id)
    db.add(note)
    await db.flush()

    if person_ids:
        await set_links(
            db,
            source_model=ModelName.Note,
            source_id=note.id,
            target_model=ModelName.Person,
            target_ids=person_ids,
            link_type=LinkType.IS_ABOUT,
            replace=True,
            user_id=user_id,
        )
    if task_id:
        await set_links(
            db,
            source_model=ModelName.Note,
            source_id=note.id,
            target_model=ModelName.Task,
            target_ids=[task_id],
            link_type=LinkType.RELATES_TO,
            replace=True,
            user_id=user_id,
        )
    if tag_ids:
        await sync_entity_tags(
            db,
            user_id=user_id,
            entity_id=note.id,
            entity_type="note",
            desired_tag_ids=tag_ids,
            tag_entity_type="note",
        )
    if event_ids:
        await set_links(
            db,
            source_model=ModelName.Note,
            source_id=note.id,
            target_model=ModelName.ActualEvent,
            target_ids=event_ids,
            link_type=LinkType.CAPTURED_FROM,
            replace=True,
            user_id=user_id,
        )

    await commit_safely(db)

    stmt = (
        select(Note)
        .where(*_active_note_filters(user_id), Note.id == note.id)
        .options(selectinload(Note.tags))
    )
    result = await db.execute(stmt.limit(1))
    return result.scalars().first()


async def batch_create_notes(
    db: AsyncSession,
    *,
    user_id: UUID,
    note_inputs: List[NoteCreate],
) -> Tuple[List[Note], List[Dict[str, Any]]]:
    created: List[Note] = []
    failed: List[Dict[str, Any]] = []
    abort_remaining = False

    for index, payload in enumerate(note_inputs, start=1):
        if abort_remaining:
            failed.append(
                {
                    "index": index,
                    "content": payload.content,
                    "error": "Skipped due to previous failure",
                }
            )
            continue

        try:
            note = await create_note(db, user_id=user_id, note_in=payload)
            if note:
                created.append(note)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            logger.error(
                "Failed to batch create note #%s for user %s",
                index,
                user_id,
                exc_info=exc,
            )
            failed.append(
                {"index": index, "content": payload.content, "error": str(exc)}
            )
            abort_remaining = True
    return created, failed


async def get_note(
    db: AsyncSession,
    *,
    user_id: UUID,
    note_id: UUID,
) -> Note:
    return await _load_note(db, user_id=user_id, note_id=note_id, with_tags=True)


def _build_notes_query(
    *,
    user_id: UUID,
    tag_id: Optional[UUID],
    person_id: Optional[UUID],
    task_id: Optional[UUID],
    actual_event_id: Optional[UUID],
    keyword: Optional[str],
    untagged: Optional[bool],
    content_exact: Optional[str],
) -> Any:
    if tag_id and untagged:
        raise InvalidOperationError(
            "Cannot use 'tag_id' and 'untagged' filters at the same time"
        )

    stmt = (
        select(Note)
        .where(*_active_note_filters(user_id))
        .options(selectinload(Note.tags))
    )

    if untagged:
        tag_exists = (
            select(tag_associations.c.entity_id)
            .join(Tag, Tag.id == tag_associations.c.tag_id)
            .where(
                tag_associations.c.entity_id == Note.id,
                tag_associations.c.entity_type == "note",
                Tag.deleted_at.is_(None),
                Tag.user_id == user_id,
            )
        )
        stmt = stmt.where(~exists(tag_exists))
    elif tag_id:
        stmt = stmt.join(Note.tags).where(
            Tag.id == tag_id, Tag.deleted_at.is_(None), Tag.user_id == user_id
        )

    if person_id:
        stmt = stmt.join(
            Association,
            and_(
                Note.id == Association.source_id,
                Association.source_model == ModelName.Note,
                Association.target_model == ModelName.Person,
                Association.link_type == LinkType.IS_ABOUT,
                Association.target_id == person_id,
                Association.deleted_at.is_(None),
                Association.user_id == user_id,
            ),
        )

    if task_id:
        stmt = stmt.join(
            Association,
            and_(
                Note.id == Association.source_id,
                Association.source_model == ModelName.Note,
                Association.target_model == ModelName.Task,
                Association.link_type == LinkType.RELATES_TO,
                Association.target_id == task_id,
                Association.deleted_at.is_(None),
                Association.user_id == user_id,
            ),
        )

    if actual_event_id:
        event_exists = (
            select(Association.id)
            .where(
                Association.source_model == ModelName.Note,
                Association.source_id == Note.id,
                Association.target_model == ModelName.ActualEvent,
                Association.target_id == actual_event_id,
                Association.link_type == LinkType.CAPTURED_FROM,
                Association.deleted_at.is_(None),
                Association.user_id == user_id,
            )
            .limit(1)
        )
        stmt = stmt.where(exists(event_exists))

    if keyword:
        tokens = [kw.strip() for kw in keyword.split() if kw.strip()]
        if tokens:
            conditions = [Note.content.ilike(f"%{kw}%") for kw in tokens]
            stmt = stmt.where(or_(*conditions))

    if content_exact:
        normalized = content_exact.strip()
        if normalized:
            stmt = stmt.where(Note.content == normalized)

    return stmt


async def list_notes(
    db: AsyncSession,
    *,
    user_id: UUID,
    limit: Optional[int] = 50,
    offset: int = 0,
    tag_id: Optional[UUID] = None,
    person_id: Optional[UUID] = None,
    task_id: Optional[UUID] = None,
    actual_event_id: Optional[UUID] = None,
    keyword: Optional[str] = None,
    untagged: Optional[bool] = None,
    content_exact: Optional[str] = None,
) -> List[Note]:
    stmt = _build_notes_query(
        user_id=user_id,
        tag_id=tag_id,
        person_id=person_id,
        task_id=task_id,
        actual_event_id=actual_event_id,
        keyword=keyword,
        untagged=untagged,
        content_exact=content_exact,
    )

    stmt = stmt.order_by(Note.created_at.desc())
    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    return result.scalars().all()


async def list_notes_with_total(
    db: AsyncSession,
    *,
    user_id: UUID,
    limit: Optional[int] = 50,
    offset: int = 0,
    tag_id: Optional[UUID] = None,
    person_id: Optional[UUID] = None,
    task_id: Optional[UUID] = None,
    actual_event_id: Optional[UUID] = None,
    keyword: Optional[str] = None,
    untagged: Optional[bool] = None,
    content_exact: Optional[str] = None,
) -> Tuple[List[Note], int]:
    stmt = _build_notes_query(
        user_id=user_id,
        tag_id=tag_id,
        person_id=person_id,
        task_id=task_id,
        actual_event_id=actual_event_id,
        keyword=keyword,
        untagged=untagged,
        content_exact=content_exact,
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())

    stmt = stmt.order_by(Note.created_at.desc())
    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    total = await db.scalar(count_stmt)
    return result.scalars().all(), int(total or 0)


async def _sync_person_links(
    db: AsyncSession,
    *,
    user_id: UUID,
    note_id: UUID,
    payload: Optional[Sequence[UUID]],
    replace: bool,
) -> None:
    if payload is None:
        return
    await set_links(
        db,
        source_model=ModelName.Note,
        source_id=note_id,
        target_model=ModelName.Person,
        target_ids=list(payload),
        link_type=LinkType.IS_ABOUT,
        replace=replace,
        user_id=user_id,
    )


async def update_note(
    db: AsyncSession,
    *,
    user_id: UUID,
    note_id: UUID,
    note_in: NoteUpdate,
) -> Note:
    note = await _load_note(db, user_id=user_id, note_id=note_id, with_tags=True)
    data = note_in.model_dump(exclude_unset=True)
    person_ids = data.pop("person_ids", None)
    tag_ids = data.pop("tag_ids", None)
    task_id = data.pop("task_id", None)
    event_ids = data.pop("actual_event_ids", None)

    for field, value in data.items():
        setattr(note, field, value)

    if person_ids is not None:
        await _sync_person_links(
            db,
            user_id=user_id,
            note_id=note.id,
            payload=person_ids or [],
            replace=True,
        )

    if tag_ids is not None:
        await sync_entity_tags(
            db,
            user_id=user_id,
            entity_id=note.id,
            entity_type="note",
            desired_tag_ids=tag_ids or [],
            tag_entity_type="note",
        )

    if task_id is not None:
        targets = [] if task_id is None else [task_id]
        await set_links(
            db,
            source_model=ModelName.Note,
            source_id=note.id,
            target_model=ModelName.Task,
            target_ids=targets,
            link_type=LinkType.RELATES_TO,
            replace=True,
            user_id=user_id,
        )
    if event_ids is not None:
        await set_links(
            db,
            source_model=ModelName.Note,
            source_id=note.id,
            target_model=ModelName.ActualEvent,
            target_ids=event_ids or [],
            link_type=LinkType.CAPTURED_FROM,
            replace=True,
            user_id=user_id,
        )

    await commit_safely(db)
    await db.refresh(note)
    return note


async def delete_note(
    db: AsyncSession,
    *,
    user_id: UUID,
    note_id: UUID,
    hard_delete: bool = False,
) -> bool:
    note = await _load_note(db, user_id=user_id, note_id=note_id)
    note.soft_delete()

    stmt = select(Association).where(
        Association.source_model == ModelName.Note,
        Association.source_id == note_id,
        Association.deleted_at.is_(None),
        Association.user_id == user_id,
    )
    associations = (await db.execute(stmt)).scalars().all()
    affected_tasks: set[UUID] = set()
    for assoc in associations:
        if (
            assoc.target_model == ModelName.Task.value
            and assoc.link_type == LinkType.RELATES_TO.value
            and assoc.target_id
        ):
            affected_tasks.add(assoc.target_id)
        assoc.soft_delete()

    if affected_tasks:
        await db.flush()
        await recompute_task_notes_count(db, affected_tasks, user_id=user_id)

    await commit_safely(db)
    return True


async def get_note_task(
    db: AsyncSession,
    *,
    user_id: UUID,
    note_id: UUID,
):
    """Return the task associated with the note, if any."""

    note = await _load_note(db, user_id=user_id, note_id=note_id)
    assoc = await get_notes_with_associations(db, user_id=user_id, notes=[note])
    payload = assoc.get(note.id, {})
    return payload.get("task")


async def get_notes_stats(db: AsyncSession, *, user_id: UUID) -> Dict[str, int]:
    stmt = select(func.count()).select_from(
        select(Note.id).where(*_active_note_filters(user_id)).subquery()
    )
    result = await db.execute(stmt)
    return {"total_notes": int(result.scalar() or 0)}


async def get_notes_person_stats(
    db: AsyncSession, *, user_id: UUID
) -> Dict[str, List[Dict[str, Any]]]:
    assoc_join = (
        Association.source_model == ModelName.Note,
        Association.target_model == ModelName.Person,
        Association.link_type == LinkType.IS_ABOUT,
        Association.deleted_at.is_(None),
        Association.user_id == user_id,
    )
    stmt = (
        select(
            Person.id,
            Person.name,
            func.count(Association.id).label("usage_count"),
        )
        .select_from(
            Person.__table__.join(Association, Person.id == Association.target_id).join(
                Note.__table__,
                and_(Note.id == Association.source_id, Note.deleted_at.is_(None)),
            )
        )
        .where(Person.user_id == user_id, Person.deleted_at.is_(None), *assoc_join)
        .group_by(Person.id, Person.name)
        .order_by(Person.name)
    )
    rows = await db.execute(stmt)
    stats = []
    for row in rows:
        temp_person = Person()
        temp_person.id = row.id
        temp_person.name = row.name
        stats.append(
            {
                "id": row.id,
                "name": row.name,
                "display_name": temp_person.display_name,
                "usage_count": row.usage_count,
            }
        )
    stats.sort(key=lambda entry: entry["display_name"])
    return {"person_stats": stats}


async def add_tag_to_note(
    db: AsyncSession,
    *,
    user_id: UUID,
    note_id: UUID,
    tag_id: UUID,
) -> Note:
    await _load_note(db, user_id=user_id, note_id=note_id)
    await add_tag_association(
        db,
        user_id=user_id,
        entity_id=note_id,
        entity_type="note",
        tag_id=tag_id,
        missing_tag_error=lambda: TagNotFoundError("Tag not found"),
        duplicate_error=lambda: TagAlreadyAssociatedError(
            "Tag is already associated with this note"
        ),
    )
    await commit_safely(db)
    return await _load_note(db, user_id=user_id, note_id=note_id, with_tags=True)


async def remove_tag_from_note(
    db: AsyncSession,
    *,
    user_id: UUID,
    note_id: UUID,
    tag_id: UUID,
) -> Note:
    await _load_note(db, user_id=user_id, note_id=note_id)
    await remove_tag_association(
        db,
        user_id=user_id,
        entity_id=note_id,
        entity_type="note",
        tag_id=tag_id,
        missing_tag_error=lambda: TagNotFoundError("Tag not found"),
        not_associated_error=lambda: TagNotAssociatedError(
            "Tag is not associated with this note"
        ),
    )
    await commit_safely(db)
    return await _load_note(db, user_id=user_id, note_id=note_id, with_tags=True)


async def get_notes_with_associations(
    db: AsyncSession,
    *,
    user_id: UUID,
    notes: Sequence[Note],
) -> Dict[UUID, Dict[str, Any]]:
    if not notes:
        return {}
    note_ids = [note.id for note in notes]
    persons_map = await load_persons_for_sources(
        db,
        source_model=ModelName.Note,
        source_ids=note_ids,
        link_type=LinkType.IS_ABOUT,
        user_id=user_id,
    )
    stmt = select(Association).where(
        Association.source_model == ModelName.Note,
        Association.source_id.in_(note_ids),
        Association.target_model == ModelName.Task,
        Association.link_type == LinkType.RELATES_TO,
        Association.deleted_at.is_(None),
        Association.user_id == user_id,
    )
    task_associations = (await db.execute(stmt)).scalars().all()
    task_ids = [assoc.target_id for assoc in task_associations if assoc.target_id]
    tasks_map: Dict[UUID, Task] = {}
    if task_ids:
        tasks_stmt = (
            select(Task)
            .where(
                Task.id.in_(task_ids),
                Task.user_id == user_id,
                Task.deleted_at.is_(None),
            )
            .options(selectinload(Task.vision), selectinload(Task.parent_task))
        )
        rows = await db.execute(tasks_stmt)
        tasks_map = {task.id: task for task in rows.scalars().all()}

    note_task_map = {}
    for assoc in task_associations:
        if assoc.target_id in tasks_map:
            note_task_map[assoc.source_id] = tasks_map[assoc.target_id]

    timelog_map = await get_target_ids_for_sources(
        db,
        source_model=ModelName.Note,
        source_ids=note_ids,
        target_model=ModelName.ActualEvent,
        link_type=LinkType.CAPTURED_FROM,
        user_id=user_id,
    )
    all_timelog_ids = {event_id for ids in timelog_map.values() for event_id in ids}
    timelogs_by_id: Dict[UUID, ActualEvent] = {}
    if all_timelog_ids:
        events_stmt = (
            select(ActualEvent)
            .where(
                ActualEvent.id.in_(all_timelog_ids),
                ActualEvent.user_id == user_id,
                ActualEvent.deleted_at.is_(None),
            )
            .options(
                selectinload(ActualEvent.dimension),
                selectinload(ActualEvent.task).selectinload(Task.vision),
            )
        )
        rows = await db.execute(events_stmt)
        timelogs_by_id = {event.id: event for event in rows.scalars().all()}

    result: Dict[UUID, Dict[str, Any]] = {}
    for note in notes:
        note_timelogs = [
            timelogs_by_id[event_id]
            for event_id in timelog_map.get(note.id, [])
            if event_id in timelogs_by_id
        ]
        setattr(note, "timelogs", note_timelogs)
        result[note.id] = {
            "persons": persons_map.get(note.id, []),
            "task": note_task_map.get(note.id),
            "timelogs": note_timelogs,
        }
    return result


async def advanced_search_notes(
    db: AsyncSession,
    *,
    user_id: UUID,
    request: NoteAdvancedSearchRequest,
) -> List[Tuple[Note, List[Person], Optional[Task]]]:
    if (
        request.start_date is not None
        and request.end_date is not None
        and request.end_date < request.start_date
    ):
        raise InvalidOperationError(
            "end_date must be greater than or equal to start_date"
        )

    stmt = (
        select(Note)
        .where(*_active_note_filters(user_id))
        .options(selectinload(Note.tags))
    )

    if request.start_date:
        stmt = stmt.where(Note.created_at >= request.start_date)
    if request.end_date:
        stmt = stmt.where(Note.created_at <= request.end_date)

    if request.tag_mode == "none":
        tag_exists = (
            select(tag_associations.c.entity_id)
            .join(Tag, tag_associations.c.tag_id == Tag.id)
            .where(
                tag_associations.c.entity_type == "note",
                tag_associations.c.entity_id == Note.id,
                Tag.user_id == user_id,
                Tag.deleted_at.is_(None),
            )
        )
        stmt = stmt.where(~exists(tag_exists))
    elif request.tag_ids:
        if request.tag_mode == "all":
            for tid in request.tag_ids:
                tag_exists = (
                    select(tag_associations.c.entity_id)
                    .join(Tag, tag_associations.c.tag_id == Tag.id)
                    .where(
                        tag_associations.c.entity_type == "note",
                        tag_associations.c.entity_id == Note.id,
                        Tag.user_id == user_id,
                        Tag.deleted_at.is_(None),
                        tag_associations.c.tag_id == tid,
                    )
                )
                stmt = stmt.where(exists(tag_exists))
        else:
            tag_exists_any = (
                select(tag_associations.c.entity_id)
                .join(Tag, tag_associations.c.tag_id == Tag.id)
                .where(
                    tag_associations.c.entity_type == "note",
                    tag_associations.c.entity_id == Note.id,
                    Tag.user_id == user_id,
                    Tag.deleted_at.is_(None),
                    tag_associations.c.tag_id.in_(request.tag_ids),
                )
            )
            stmt = stmt.where(exists(tag_exists_any))

    assoc_person = select(Association.source_id).where(
        Association.source_model == ModelName.Note,
        Association.source_id == Note.id,
        Association.target_model == ModelName.Person,
        Association.link_type == LinkType.IS_ABOUT,
        Association.deleted_at.is_(None),
        Association.user_id == user_id,
    )

    if request.person_mode == "none":
        stmt = stmt.where(~exists(assoc_person))
    elif request.person_ids:
        if request.person_mode == "all":
            for pid in request.person_ids:
                stmt = stmt.where(
                    exists(assoc_person.where(Association.target_id == pid))
                )
        else:
            stmt = stmt.where(
                exists(
                    assoc_person.where(Association.target_id.in_(request.person_ids))
                )
            )

    assoc_task = select(Association.source_id).where(
        Association.source_model == ModelName.Note,
        Association.source_id == Note.id,
        Association.target_model == ModelName.Task,
        Association.link_type == LinkType.RELATES_TO,
        Association.deleted_at.is_(None),
        Association.user_id == user_id,
    )

    if request.task_filter == "none":
        stmt = stmt.where(~exists(assoc_task))
    elif request.task_filter == "has":
        stmt = stmt.where(exists(assoc_task))
    elif request.task_filter == "specific" and request.task_id:
        stmt = stmt.where(
            exists(assoc_task.where(Association.target_id == request.task_id))
        )

    if request.keyword:
        tokens = [kw.strip() for kw in request.keyword.split() if kw.strip()]
        if tokens:
            stmt = stmt.where(or_(*[Note.content.ilike(f"%{kw}%") for kw in tokens]))

    stmt = stmt.order_by(Note.created_at.desc())
    result = await db.execute(stmt)
    notes = result.scalars().all()
    reverse = request.sort_order != "asc"
    notes = sorted(
        notes,
        key=lambda note: note.created_at or note.updated_at,
        reverse=reverse,
    )
    associations = await get_notes_with_associations(db, user_id=user_id, notes=notes)
    enriched: List[Tuple[Note, List[Person], Optional[Task]]] = []
    for note in notes:
        assoc = associations.get(note.id, {})
        enriched.append(
            (
                note,
                assoc.get("persons", []),
                assoc.get("task"),
            )
        )
    return enriched


async def _apply_tag_batch_operation(
    db: AsyncSession,
    *,
    note: Note,
    payload: NoteBatchTagUpdate,
    user_id: UUID,
) -> None:
    existing_ids = {tag.id for tag in note.tags or []}
    if payload.mode == "replace":
        target_ids = payload.tag_ids or []
    else:
        target_ids = list(existing_ids.union(payload.tag_ids or []))

    await sync_entity_tags(
        db,
        user_id=user_id,
        entity_id=note.id,
        entity_type="note",
        desired_tag_ids=target_ids,
        tag_entity_type="note",
    )


async def _apply_person_batch_operation(
    db: AsyncSession,
    *,
    note: Note,
    payload: NoteBatchPersonUpdate,
    user_id: UUID,
) -> None:
    if payload.mode == "replace":
        await _sync_person_links(
            db,
            user_id=user_id,
            note_id=note.id,
            payload=payload.person_ids or [],
            replace=True,
        )
    else:
        if payload.person_ids:
            await _sync_person_links(
                db,
                user_id=user_id,
                note_id=note.id,
                payload=payload.person_ids,
                replace=False,
            )


async def _apply_task_batch_operation(
    db: AsyncSession,
    *,
    note: Note,
    payload: NoteBatchTaskUpdate,
    user_id: UUID,
) -> None:
    if payload.mode == "clear":
        await set_links(
            db,
            source_model=ModelName.Note,
            source_id=note.id,
            target_model=ModelName.Task,
            target_ids=[],
            link_type=LinkType.RELATES_TO,
            replace=True,
            user_id=user_id,
        )
    elif payload.task_id is not None:
        await set_links(
            db,
            source_model=ModelName.Note,
            source_id=note.id,
            target_model=ModelName.Task,
            target_ids=[payload.task_id],
            link_type=LinkType.RELATES_TO,
            replace=True,
            user_id=user_id,
        )


def _apply_content_batch_operation(
    *,
    note: Note,
    payload: NoteBatchContentUpdate,
) -> int:
    original = note.content or ""
    if payload.case_sensitive:
        occurrences = original.count(payload.find_text)
        if occurrences:
            note.content = original.replace(payload.find_text, payload.replace_text)
        return occurrences
    pattern = re.compile(re.escape(payload.find_text), re.IGNORECASE)
    new_content, replacements = pattern.subn(payload.replace_text, original)
    if replacements:
        note.content = new_content
    return replacements


async def batch_update_notes(
    db: AsyncSession,
    *,
    user_id: UUID,
    request: NoteBatchUpdateRequest,
) -> NoteBatchUpdateResponse:
    updated = 0
    failed: List[UUID] = []
    errors: List[str] = []

    for note_id in dict.fromkeys(request.note_ids):
        try:
            note = await _load_note(
                db, user_id=user_id, note_id=note_id, with_tags=True
            )
            if request.operation == "tags":
                if request.tags is None:
                    raise InvalidOperationError("Missing tags configuration")
                await _apply_tag_batch_operation(
                    db,
                    note=note,
                    payload=request.tags,
                    user_id=user_id,
                )
            elif request.operation == "persons":
                if request.persons is None:
                    raise InvalidOperationError("Missing persons configuration")
                await _apply_person_batch_operation(
                    db,
                    note=note,
                    payload=request.persons,
                    user_id=user_id,
                )
            elif request.operation == "task":
                if request.task is None:
                    raise InvalidOperationError("Missing task configuration")
                await _apply_task_batch_operation(
                    db,
                    note=note,
                    payload=request.task,
                    user_id=user_id,
                )
            elif request.operation == "content":
                if request.content is None:
                    raise InvalidOperationError("Missing content configuration")
                _apply_content_batch_operation(note=note, payload=request.content)
            else:
                raise InvalidOperationError("Unsupported batch operation")

            note.updated_at = utc_now()
            await commit_safely(db)
            updated += 1
        except (NoteNotFoundError, InvalidOperationError) as exc:
            await db.rollback()
            failed.append(note_id)
            errors.append(str(exc))
        except Exception as exc:  # pragma: no cover
            await db.rollback()
            failed.append(note_id)
            errors.append(str(exc))
            logger.exception("Unexpected error during batch note update", exc_info=exc)

    return NoteBatchUpdateResponse(
        updated_count=updated,
        failed_ids=failed,
        errors=errors,
    )


async def batch_delete_notes(
    db: AsyncSession,
    *,
    user_id: UUID,
    request: NoteBatchDeleteRequest,
) -> NoteBatchDeleteResponse:
    deleted = 0
    failed: List[UUID] = []
    errors: List[str] = []

    for note_id in dict.fromkeys(request.note_ids):
        try:
            await delete_note(db, user_id=user_id, note_id=note_id, hard_delete=False)
            deleted += 1
        except NoteNotFoundError as exc:
            await db.rollback()
            failed.append(note_id)
            errors.append(str(exc))
        except Exception as exc:  # pragma: no cover
            await db.rollback()
            failed.append(note_id)
            errors.append(str(exc))
            logger.exception("Unexpected error during batch note delete", exc_info=exc)

    return NoteBatchDeleteResponse(
        deleted_count=deleted,
        failed_ids=failed,
        errors=errors,
    )


__all__ = [
    "InvalidOperationError",
    "NoteNotFoundError",
    "TagAlreadyAssociatedError",
    "TagNotAssociatedError",
    "TagNotFoundError",
    "create_note",
    "batch_create_notes",
    "get_note",
    "get_note_task",
    "list_notes",
    "list_notes_with_total",
    "advanced_search_notes",
    "update_note",
    "delete_note",
    "get_notes_with_associations",
    "get_notes_stats",
    "get_notes_person_stats",
    "add_tag_to_note",
    "remove_tag_from_note",
    "batch_update_notes",
    "batch_delete_notes",
]
