"""
Async person service layer.

This module provides the asynchronous implementations for Person/Anniversary CRUD so
routers, agents, and workflows can await DB operations without touching sync sessions.
"""

from __future__ import annotations

from typing import List, Literal, Optional, Tuple, Union
from uuid import UUID

from sqlalchemy import (
    Column,
    String,
    Text,
    and_,
    case,
    cast,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.actual_event import ActualEvent
from app.db.models.anniversary import Anniversary
from app.db.models.association import Association
from app.db.models.note import Note
from app.db.models.person import Person
from app.db.models.planned_event import PlannedEvent
from app.db.models.tag import Tag
from app.db.models.tag_associations import tag_associations
from app.db.models.task import Task
from app.db.models.vision import Vision
from app.db.transaction import commit_safely
from app.handlers.associations import LinkType, ModelName
from app.handlers.tag_associations import (
    add_tag_association,
    remove_tag_association,
    sync_entity_tags,
)
from app.schemas.person import (
    AnniversaryCreate,
    AnniversaryUpdate,
    PersonActivitiesResponse,
    PersonActivityItem,
    PersonCreate,
    PersonUpdate,
)


class PersonNotFoundError(Exception):
    """Raised when a person is not found."""


class PersonAlreadyExistsError(Exception):
    """Raised when a person with the same identifier already exists."""


class TagNotFoundError(Exception):
    """Raised when a tag is not found."""


class AnniversaryNotFoundError(Exception):
    """Raised when an anniversary is not found."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _person_filters(user_id: Union[UUID, Column]) -> List:
    return [Person.user_id == user_id, Person.deleted_at.is_(None)]


async def get_person(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    person_id: UUID,
) -> Optional[Person]:
    stmt = (
        select(Person)
        .options(selectinload(Person.tags), selectinload(Person.anniversaries))
        .where(Person.id == person_id, *_person_filters(user_id))
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


async def _require_person(
    db: AsyncSession, *, user_id: Union[UUID, Column], person_id: UUID
) -> Person:
    person = await get_person(db, user_id=user_id, person_id=person_id)
    if person is None:
        raise PersonNotFoundError("Person not found")
    return person


def _normalize_tag_ids(tag_ids: Optional[List[str]]) -> List[UUID]:
    if not tag_ids:
        return []
    return [UUID(str(tag_id)) for tag_id in tag_ids]


# ---------------------------------------------------------------------------
# Core CRUD
# ---------------------------------------------------------------------------


async def create_person(
    db: AsyncSession, *, user_id: Union[UUID, Column], person_in: PersonCreate
) -> Person:
    payload = person_in.model_dump(exclude={"tag_ids"})
    person = Person(**payload, user_id=user_id)
    db.add(person)
    await db.flush()

    tag_ids = _normalize_tag_ids(person_in.tag_ids)
    if tag_ids:
        await sync_entity_tags(
            db,
            user_id=user_id,
            entity_id=person.id,
            entity_type="person",
            desired_tag_ids=tag_ids,
            tag_entity_type="person",
            skip_missing=False,
            missing_tag_error=lambda: TagNotFoundError("One or more tag IDs not found"),
        )

    await commit_safely(db)
    await db.refresh(person)
    return await get_person(db, user_id=user_id, person_id=person.id)


async def list_persons(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    skip: int = 0,
    limit: int = 100,
    tag_filter: Optional[str] = None,
    tag_id: Optional[UUID] = None,
    search: Optional[str] = None,
    nickname_exact: Optional[str] = None,
) -> Tuple[List[Person], int]:
    stmt = (
        select(Person)
        .options(selectinload(Person.tags))
        .where(*_person_filters(user_id))
    )
    count_stmt = (
        select(func.count()).select_from(Person).where(*_person_filters(user_id))
    )

    if search:
        search_term = f"%{search.strip()}%"
        clause = or_(
            Person.name.ilike(search_term),
            cast(Person.nicknames, Text).ilike(search_term),
        )
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)

    if nickname_exact:
        nick = nickname_exact.strip()
        if nick:
            contains_expr = cast(Person.nicknames, postgresql.JSONB).contains([nick])
            stmt = stmt.where(contains_expr)
            count_stmt = count_stmt.where(contains_expr)

    if tag_id:
        join_condition = and_(
            tag_associations.c.entity_id == Person.id,
            tag_associations.c.entity_type == "person",
        )
        stmt = (
            stmt.join(tag_associations, join_condition)
            .join(Tag, tag_associations.c.tag_id == Tag.id)
            .where(
                Tag.id == tag_id,
                Tag.user_id == user_id,
                Tag.deleted_at.is_(None),
            )
        )
        count_stmt = (
            count_stmt.join(tag_associations, join_condition)
            .join(Tag, tag_associations.c.tag_id == Tag.id)
            .where(
                Tag.id == tag_id,
                Tag.user_id == user_id,
                Tag.deleted_at.is_(None),
            )
        )
    elif tag_filter:
        normalized = tag_filter.strip().lower()
        join_condition = and_(
            tag_associations.c.entity_id == Person.id,
            tag_associations.c.entity_type == "person",
        )
        stmt = (
            stmt.join(tag_associations, join_condition)
            .join(Tag, tag_associations.c.tag_id == Tag.id)
            .where(
                Tag.name == normalized,
                Tag.user_id == user_id,
                Tag.deleted_at.is_(None),
            )
        )
        count_stmt = (
            count_stmt.join(tag_associations, join_condition)
            .join(Tag, tag_associations.c.tag_id == Tag.id)
            .where(
                Tag.name == normalized,
                Tag.user_id == user_id,
                Tag.deleted_at.is_(None),
            )
        )

    stmt = stmt.order_by(Person.created_at.desc()).offset(skip).limit(limit)
    persons = (await db.execute(stmt)).scalars().all()

    total = (await db.execute(count_stmt)).scalar()
    return persons, int(total or 0)


def _build_persons_by_tag_stmt(
    *,
    user_id: Union[UUID, Column],
    tag_id: Optional[UUID],
    tag_name: Optional[str],
):
    stmt = (
        select(Person)
        .options(selectinload(Person.tags), selectinload(Person.anniversaries))
        .join(
            tag_associations,
            and_(
                Person.id == tag_associations.c.entity_id,
                tag_associations.c.entity_type == "person",
            ),
        )
        .join(Tag, Tag.id == tag_associations.c.tag_id)
        .where(*_person_filters(user_id))
    )
    if tag_id:
        stmt = stmt.where(
            Tag.id == tag_id,
            Tag.entity_type == "person",
            Tag.deleted_at.is_(None),
            Tag.user_id == user_id,
        )
    else:
        normalized = (tag_name or "").strip().lower()
        stmt = stmt.where(
            Tag.name == normalized,
            Tag.entity_type == "person",
            Tag.deleted_at.is_(None),
            Tag.user_id == user_id,
        )
    return stmt


async def search_persons_by_tag(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    tag_id: Optional[UUID] = None,
    tag_name: Optional[str] = None,
) -> List[Person]:
    stmt = _build_persons_by_tag_stmt(
        user_id=user_id,
        tag_id=tag_id,
        tag_name=tag_name,
    )

    persons = (await db.execute(stmt.order_by(Person.name))).scalars().all()
    if persons:
        return persons

    if tag_id:
        exists_stmt = (
            select(Tag.id)
            .where(
                Tag.id == tag_id,
                Tag.entity_type == "person",
                Tag.user_id == user_id,
                Tag.deleted_at.is_(None),
            )
            .limit(1)
        )
        exists = (await db.execute(exists_stmt)).first()
        if not exists:
            raise TagNotFoundError(f"Tag with ID {tag_id} not found")
    else:
        normalized = (tag_name or "").strip().lower()
        exists_stmt = (
            select(Tag.id)
            .where(
                Tag.name == normalized,
                Tag.entity_type == "person",
                Tag.user_id == user_id,
                Tag.deleted_at.is_(None),
            )
            .limit(1)
        )
        exists = (await db.execute(exists_stmt)).first()
        if not exists:
            raise TagNotFoundError(f"Tag with name '{tag_name}' not found")

    return persons


async def search_persons_by_tag_with_total(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    tag_id: Optional[UUID] = None,
    tag_name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Person], int]:
    stmt = _build_persons_by_tag_stmt(
        user_id=user_id,
        tag_id=tag_id,
        tag_name=tag_name,
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    stmt = stmt.order_by(Person.name).offset(offset).limit(limit)
    persons = (await db.execute(stmt)).scalars().all()
    total = await db.scalar(count_stmt)
    if persons:
        return persons, int(total or 0)

    if tag_id:
        exists_stmt = (
            select(Tag.id)
            .where(
                Tag.id == tag_id,
                Tag.entity_type == "person",
                Tag.user_id == user_id,
                Tag.deleted_at.is_(None),
            )
            .limit(1)
        )
        exists = (await db.execute(exists_stmt)).first()
        if not exists:
            raise TagNotFoundError(f"Tag with ID {tag_id} not found")
    else:
        normalized = (tag_name or "").strip().lower()
        exists_stmt = (
            select(Tag.id)
            .where(
                Tag.name == normalized,
                Tag.entity_type == "person",
                Tag.user_id == user_id,
                Tag.deleted_at.is_(None),
            )
            .limit(1)
        )
        exists = (await db.execute(exists_stmt)).first()
        if not exists:
            raise TagNotFoundError(f"Tag with name '{tag_name}' not found")

    return [], int(total or 0)


async def update_person(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    person_id: UUID,
    update_in: PersonUpdate,
) -> Optional[Person]:
    stmt = (
        select(Person)
        .options(selectinload(Person.tags), selectinload(Person.anniversaries))
        .where(Person.id == person_id, *_person_filters(user_id))
        .limit(1)
    )
    person = (await db.execute(stmt)).scalars().first()
    if person is None:
        return None

    update_data = update_in.model_dump(exclude_unset=True, exclude={"tag_ids"})
    for field, value in update_data.items():
        setattr(person, field, value)

    if update_in.tag_ids is not None:
        await sync_entity_tags(
            db,
            user_id=user_id,
            entity_id=person_id,
            entity_type="person",
            desired_tag_ids=_normalize_tag_ids(update_in.tag_ids),
            tag_entity_type="person",
            skip_missing=False,
            missing_tag_error=lambda: TagNotFoundError("One or more tag IDs not found"),
        )

    await commit_safely(db)
    await db.refresh(person)
    return await get_person(db, user_id=user_id, person_id=person.id)


async def delete_person(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    person_id: UUID,
    hard_delete: bool = False,
) -> bool:
    stmt = select(Person).where(Person.id == person_id, *_person_filters(user_id))
    person = (await db.execute(stmt.limit(1))).scalars().first()
    if person is None:
        return False

    if hard_delete:
        await db.delete(person)
    else:
        person.soft_delete()

    await commit_safely(db)
    return True


async def add_tag_to_person(
    db: AsyncSession, *, user_id: Union[UUID, Column], person_id: UUID, tag_id: UUID
) -> Optional[Person]:
    person = await _require_person(db, user_id=user_id, person_id=person_id)

    await add_tag_association(
        db,
        user_id=user_id,
        entity_id=person_id,
        entity_type="person",
        tag_id=tag_id,
        tag_entity_type="person",
        missing_tag_error=lambda: TagNotFoundError("Tag not found"),
        duplicate_error=lambda: PersonAlreadyExistsError(
            "Tag is already associated with this person"
        ),
    )
    await commit_safely(db)
    await db.refresh(person)
    return await get_person(db, user_id=user_id, person_id=person.id)


async def remove_tag_from_person(
    db: AsyncSession, *, user_id: Union[UUID, Column], person_id: UUID, tag_id: UUID
) -> Optional[Person]:
    person = await _require_person(db, user_id=user_id, person_id=person_id)

    await remove_tag_association(
        db,
        user_id=user_id,
        entity_id=person_id,
        entity_type="person",
        tag_id=tag_id,
        tag_entity_type="person",
        missing_tag_error=lambda: TagNotFoundError("Tag not found"),
        not_associated_error=lambda: PersonNotFoundError(
            "Tag is not associated with this person"
        ),
    )
    await commit_safely(db)
    await db.refresh(person)
    return await get_person(db, user_id=user_id, person_id=person.id)


# ---------------------------------------------------------------------------
# Anniversary helpers
# ---------------------------------------------------------------------------


async def create_anniversary(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    person_id: UUID,
    anniversary_data: AnniversaryCreate,
) -> Anniversary:
    await _require_person(db, user_id=user_id, person_id=person_id)

    anniversary = Anniversary(
        person_id=person_id, user_id=user_id, **anniversary_data.model_dump()
    )
    db.add(anniversary)
    await commit_safely(db)
    await db.refresh(anniversary)
    return anniversary


async def get_person_anniversaries(
    db: AsyncSession, *, user_id: Union[UUID, Column], person_id: UUID
) -> List[Anniversary]:
    await _require_person(db, user_id=user_id, person_id=person_id)
    stmt = (
        select(Anniversary)
        .where(Anniversary.person_id == person_id)
        .order_by(Anniversary.date)
    )
    return (await db.execute(stmt)).scalars().all()


async def delete_anniversary(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    person_id: UUID,
    anniversary_id: UUID,
) -> bool:
    stmt = (
        select(Anniversary)
        .join(Person)
        .where(
            Anniversary.id == anniversary_id,
            Anniversary.person_id == person_id,
            Person.user_id == user_id,
            Person.deleted_at.is_(None),
        )
        .limit(1)
    )
    anniversary = (await db.execute(stmt)).scalars().first()
    if anniversary is None:
        raise AnniversaryNotFoundError("Anniversary not found")

    await db.delete(anniversary)
    await commit_safely(db)
    return True


async def update_anniversary(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    person_id: UUID,
    anniversary_id: UUID,
    update_data: AnniversaryUpdate,
) -> Anniversary:
    stmt = (
        select(Anniversary)
        .join(Person)
        .where(
            Anniversary.id == anniversary_id,
            Anniversary.person_id == person_id,
            Person.user_id == user_id,
            Person.deleted_at.is_(None),
        )
        .limit(1)
    )
    anniversary = (await db.execute(stmt)).scalars().first()
    if anniversary is None:
        raise AnniversaryNotFoundError("Anniversary not found")

    payload = update_data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        setattr(anniversary, field, value)

    await commit_safely(db)
    await db.refresh(anniversary)
    return anniversary


# ---------------------------------------------------------------------------
# Activity timeline
# ---------------------------------------------------------------------------


async def get_person_activities(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    person_id: UUID,
    page: int = 1,
    size: int = 50,
    activity_type: Optional[
        Literal["vision", "task", "planned_event", "actual_event", "note"]
    ] = None,
) -> PersonActivitiesResponse:
    person = await _require_person(db, user_id=user_id, person_id=person_id)
    association_filters = (
        Association.target_model == ModelName.Person.value,
        Association.target_id == person_id,
        Association.deleted_at.is_(None),
        Association.user_id == user_id,
    )

    def build_activity_query(
        model,
        *,
        model_name: ModelName,
        link_type: LinkType,
        activity_label: str,
        title_expr,
        description_expr,
        date_expr,
        status_expr,
    ):
        return (
            select(
                model.id.label("id"),
                literal(activity_label).label("type"),
                cast(title_expr, Text).label("title"),
                cast(description_expr, Text).label("description"),
                date_expr.label("date"),
                cast(status_expr, String).label("status"),
            )
            .select_from(model)
            .join(
                Association,
                and_(
                    Association.source_model == model_name.value,
                    Association.source_id == model.id,
                    Association.link_type == link_type.value,
                    *association_filters,
                ),
            )
            .where(
                model.user_id == user_id,
                model.deleted_at.is_(None),
            )
        )

    queries = []
    if activity_type in (None, "vision"):
        queries.append(
            build_activity_query(
                Vision,
                model_name=ModelName.Vision,
                link_type=LinkType.INVOLVES,
                activity_label="vision",
                title_expr=Vision.name,
                description_expr=Vision.description,
                date_expr=Vision.created_at,
                status_expr=Vision.status,
            )
        )

    if activity_type in (None, "task"):
        note_count = func.coalesce(Task.notes_count, 0)
        task_description = case(
            (
                note_count > 0,
                func.concat(cast(note_count, String), literal(" related notes")),
            ),
            else_=literal(None),
        )
        queries.append(
            build_activity_query(
                Task,
                model_name=ModelName.Task,
                link_type=LinkType.INVOLVES,
                activity_label="task",
                title_expr=Task.content,
                description_expr=task_description,
                date_expr=Task.created_at,
                status_expr=Task.status,
            )
        )

    if activity_type in (None, "planned_event"):
        queries.append(
            build_activity_query(
                PlannedEvent,
                model_name=ModelName.PlannedEvent,
                link_type=LinkType.INVITED,
                activity_label="planned_event",
                title_expr=PlannedEvent.title,
                description_expr=literal(None),
                date_expr=PlannedEvent.start_time,
                status_expr=PlannedEvent.status,
            )
        )

    if activity_type in (None, "actual_event"):
        queries.append(
            build_activity_query(
                ActualEvent,
                model_name=ModelName.ActualEvent,
                link_type=LinkType.ATTENDED_BY,
                activity_label="actual_event",
                title_expr=ActualEvent.title,
                description_expr=ActualEvent.notes,
                date_expr=ActualEvent.start_time,
                status_expr=literal(None),
            )
        )

    if activity_type in (None, "note"):
        note_title = case(
            (
                func.length(Note.content) > 50,
                func.concat(func.substr(Note.content, 1, 50), literal("...")),
            ),
            else_=Note.content,
        )
        queries.append(
            build_activity_query(
                Note,
                model_name=ModelName.Note,
                link_type=LinkType.IS_ABOUT,
                activity_label="note",
                title_expr=note_title,
                description_expr=literal(None),
                date_expr=Note.created_at,
                status_expr=literal(None),
            )
        )

    if not queries:
        return PersonActivitiesResponse(
            items=[],
            pagination={
                "page": page,
                "size": size,
                "total": 0,
                "pages": 0,
            },
            meta={
                "person_id": person_id,
                "person_name": person.display_name,
                "activity_type": activity_type,
            },
        )

    union_subquery = queries[0].union_all(*queries[1:]).subquery()
    offset = (page - 1) * size
    ordered_stmt = (
        select(union_subquery)
        .order_by(union_subquery.c.date.desc())
        .offset(offset)
        .limit(size)
    )
    rows = (await db.execute(ordered_stmt)).mappings().all()
    total = (
        await db.execute(select(func.count()).select_from(union_subquery))
    ).scalar_one()

    activities = [
        PersonActivityItem(
            id=row["id"],
            type=row["type"],
            title=row["title"] or "",
            description=row["description"],
            date=row["date"],
            status=row["status"],
        )
        for row in rows
    ]

    pages = (total + size - 1) // size if size else 0
    return PersonActivitiesResponse(
        items=activities,
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={
            "person_id": person_id,
            "person_name": person.display_name,
            "activity_type": activity_type,
        },
    )


__all__ = [
    "AnniversaryNotFoundError",
    "PersonAlreadyExistsError",
    "PersonNotFoundError",
    "TagNotFoundError",
    "create_person",
    "get_person",
    "list_persons",
    "search_persons_by_tag",
    "search_persons_by_tag_with_total",
    "update_person",
    "delete_person",
    "add_tag_to_person",
    "remove_tag_from_person",
    "create_anniversary",
    "get_person_anniversaries",
    "delete_anniversary",
    "update_anniversary",
    "get_person_activities",
]
