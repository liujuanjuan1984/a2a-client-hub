"""
Async implementations for actual event handlers.

为 Agent 工具及 API 提供真正的 AsyncSession 支持，逐步淘汰
``run_with_session`` 的同步包装。
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from uuid import UUID

from sqlalchemy import Column, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger, log_exception
from app.db.models.actual_event import ActualEvent
from app.db.models.association import Association
from app.db.models.dimension import Dimension
from app.db.models.note import Note
from app.db.models.person import Person
from app.db.models.task import Task
from app.db.transaction import commit_safely
from app.handlers.associations import LinkType, ModelName
from app.handlers.associations_async import load_persons_for_sources, set_links
from app.handlers.metrics.stats import recompute_daily_stats_for_event
from app.schemas.actual_event import (
    ActualEventCreate,
    ActualEventUpdate,
    EnergyInjectionResult,
)
from app.serialization.entities import (
    build_task_summary,
    normalize_task_summary,
    serialize_person_summary,
)
from app.services.work_recalc import schedule_recalc_jobs
from app.utils.data_protocol import validate_uuid_field
from app.utils.person_utils import convert_persons_to_summary
from app.utils.timezone_util import utc_now

logger = get_logger(__name__)


# Shared limits for search endpoints
DEFAULT_MAX_SEARCH_DAYS = 31
DEFAULT_MAX_SEARCH_RESULTS = 2000


# Business Exceptions
class ActualEventNotFoundError(Exception):
    """Raised when an actual event is not found."""


class ActualEventNotDeletedError(Exception):
    """Raised when trying to restore a non-deleted event."""


class AssociatedTaskNotFoundError(Exception):
    """Raised when associated task is not found."""


class DeprecatedFieldError(Exception):
    """Raised when deprecated fields are used."""


class ActualEventResultTooLargeError(Exception):
    """Raised when search results exceed configured upper bounds."""


async def _reload_event_with_relations(
    db: AsyncSession, *, user_id: Union[UUID, Column], event_id: UUID
) -> Optional[ActualEvent]:
    stmt = (
        select(ActualEvent)
        .options(
            selectinload(ActualEvent.dimension),
            selectinload(ActualEvent.task).selectinload(Task.vision),
        )
        .where(
            ActualEvent.id == event_id,
            ActualEvent.user_id == user_id,
            ActualEvent.deleted_at.is_(None),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _task_exists(
    db: AsyncSession, *, user_id: Union[UUID, Column], task_id: UUID
) -> bool:
    stmt = (
        select(Task.id)
        .where(
            Task.id == task_id,
            Task.user_id == user_id,
            Task.deleted_at.is_(None),
        )
        .limit(1)
    )
    return (await db.scalar(stmt)) is not None


async def _get_task_vision_id(
    db: AsyncSession, *, user_id: Union[UUID, Column], task_id: Optional[UUID]
) -> Optional[UUID]:
    if task_id is None:
        return None
    stmt = (
        select(Task.vision_id)
        .where(
            Task.id == task_id,
            Task.user_id == user_id,
            Task.deleted_at.is_(None),
        )
        .limit(1)
    )
    return await db.scalar(stmt)


def _serialize_person_summaries(persons: Sequence[Any]) -> List[Dict[str, Any]]:
    return [serialize_person_summary(summary) for summary in persons]


async def _attach_notes_to_events(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    events: Sequence[ActualEvent],
) -> None:
    if not events:
        return

    event_ids = [event.id for event in events if isinstance(event.id, UUID)]
    if not event_ids:
        for event in events:
            setattr(event, "associated_notes", [])
            setattr(event, "associated_notes_count", 0)
        return

    assoc_stmt = select(Association.target_id, Association.source_id).where(
        Association.source_model == ModelName.Note.value,
        Association.target_model == ModelName.ActualEvent.value,
        Association.link_type == LinkType.CAPTURED_FROM.value,
        Association.user_id == user_id,
        Association.target_id.in_(event_ids),
        Association.deleted_at.is_(None),
    )
    assoc_rows = await db.execute(assoc_stmt)
    event_note_ids: Dict[UUID, List[UUID]] = {}
    for target_id, source_id in assoc_rows.all():
        event_note_ids.setdefault(target_id, []).append(source_id)

    all_note_ids = {nid for ids in event_note_ids.values() for nid in ids}
    notes_by_id: Dict[UUID, Note] = {}
    if all_note_ids:
        note_stmt = (
            select(Note)
            .where(
                Note.user_id == user_id,
                Note.id.in_(all_note_ids),
                Note.deleted_at.is_(None),
            )
            .order_by(Note.created_at.desc())
        )
        notes = (await db.execute(note_stmt)).scalars().all()
        notes_by_id = {note.id: note for note in notes}

    for event in events:
        linked_ids = event_note_ids.get(event.id, [])
        linked_notes = [notes_by_id[nid] for nid in linked_ids if nid in notes_by_id]
        setattr(event, "associated_notes", linked_notes)
        setattr(event, "associated_notes_count", len(linked_notes))


async def _attach_note_counts_to_events(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    events: Sequence[ActualEvent],
) -> None:
    if not events:
        return

    event_ids = [event.id for event in events if isinstance(event.id, UUID)]
    if not event_ids:
        for event in events:
            setattr(event, "associated_notes", [])
            setattr(event, "associated_notes_count", 0)
        return

    stmt = (
        select(Association.target_id, func.count(Association.id))
        .where(
            Association.source_model == ModelName.Note.value,
            Association.target_model == ModelName.ActualEvent.value,
            Association.link_type == LinkType.CAPTURED_FROM.value,
            Association.user_id == user_id,
            Association.target_id.in_(event_ids),
            Association.deleted_at.is_(None),
        )
        .group_by(Association.target_id)
    )
    rows = await db.execute(stmt)
    counts = {target_id: count for target_id, count in rows.all()}

    for event in events:
        setattr(event, "associated_notes", [])
        setattr(event, "associated_notes_count", counts.get(event.id, 0))


async def _get_dimension_id_by_name(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    dimension_name: str,
) -> UUID:
    stmt = (
        select(Dimension.id)
        .where(
            Dimension.user_id == user_id,
            Dimension.name == dimension_name,
            Dimension.is_active.is_(True),
        )
        .limit(1)
    )
    dimension_id = await db.scalar(stmt)
    if not dimension_id:
        raise ActualEventNotFoundError(
            f"Dimension '{dimension_name}' not found or not active"
        )
    return dimension_id


async def _recompute_daily_stats(
    db: AsyncSession, event: ActualEvent, *, user_id: Union[UUID, Column]
) -> None:
    merged = await db.merge(event, load=False)
    await recompute_daily_stats_for_event(db, merged, user_id=user_id)


async def _schedule_recalc_jobs(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    task_ids: Sequence[UUID],
    vision_ids: Sequence[UUID],
    reason: str,
    run_async: bool = False,
) -> None:
    # 使用独立 session 以避免 work_recalc 调度导致当前 ORM 状态失效。
    await schedule_recalc_jobs(
        None,
        user_id=user_id,
        task_ids=task_ids,
        vision_ids=vision_ids,
        reason=reason,
        run_async=run_async,
    )


async def search_actual_events(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    event_id: Optional[UUID] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    tracking_method: Optional[str] = None,
    dimension_name: Optional[str] = None,
    description_keyword: Optional[str] = None,
    task_id: Optional[UUID] = None,
    task_id_null_only: bool = False,
    include_notes: bool = True,
    max_results: Optional[int] = None,
    max_range_days: Optional[int] = None,
    allow_result_truncation: bool = False,
    result_metadata: Optional[Dict[str, Any]] = None,
) -> List[Tuple[ActualEvent, List[Dict[str, Any]], Optional[Dict[str, Any]]]]:
    if start_date is not None and end_date is None:
        end_date = start_date

    if (
        max_range_days is not None
        and start_date is not None
        and end_date is not None
        and (end_date - start_date).total_seconds() > max_range_days * 24 * 3600
    ):
        raise ActualEventResultTooLargeError(
            f"Date range too wide: maximum {max_range_days} days"
        )

    stmt = (
        select(ActualEvent)
        .options(
            selectinload(ActualEvent.dimension),
            selectinload(ActualEvent.task).selectinload(Task.vision),
        )
        .where(
            ActualEvent.user_id == user_id,
            ActualEvent.deleted_at.is_(None),
        )
    )

    if event_id is not None:
        stmt = stmt.where(ActualEvent.id == event_id)

    if start_date is not None and end_date is not None:
        stmt = stmt.where(
            ActualEvent.start_time <= end_date,
            ActualEvent.end_time >= start_date,
            ~and_(
                ActualEvent.start_time < start_date,
                ActualEvent.end_time == start_date,
                ActualEvent.start_time != ActualEvent.end_time,
            ),
            ~and_(
                ActualEvent.start_time == end_date,
                ActualEvent.end_time > end_date,
                ActualEvent.start_time != ActualEvent.end_time,
            ),
        )

    if tracking_method:
        stmt = stmt.where(ActualEvent.tracking_method == tracking_method)

    if dimension_name:
        dimension_id = await _get_dimension_id_by_name(
            db, user_id=user_id, dimension_name=dimension_name
        )
        stmt = stmt.where(ActualEvent.dimension_id == dimension_id)

    if task_id_null_only:
        stmt = stmt.where(ActualEvent.task_id.is_(None))
    elif task_id is not None:
        stmt = stmt.where(ActualEvent.task_id == task_id)

    if description_keyword:
        keywords = [kw.strip() for kw in description_keyword.split() if kw.strip()]
        if keywords:
            keyword_conditions = [
                or_(
                    ActualEvent.title.ilike(f"%{keyword}%"),
                    ActualEvent.notes.ilike(f"%{keyword}%"),
                )
                for keyword in keywords
            ]
            if len(keyword_conditions) == 1:
                stmt = stmt.where(keyword_conditions[0])
            else:
                stmt = stmt.where(or_(*keyword_conditions))

    stmt = stmt.order_by(ActualEvent.start_time.asc())
    events: List[ActualEvent]
    truncated = False
    total_count: Optional[int] = None

    if allow_result_truncation:
        count_stmt = stmt.with_only_columns(func.count(ActualEvent.id)).order_by(None)
        total_count = (await db.execute(count_stmt)).scalar_one()
        if total_count is None:
            total_count = 0
        limit_value = max_results or total_count
        if max_results is not None:
            truncated = total_count > max_results
            stmt = stmt.limit(max(max_results, 0))
        events = (await db.execute(stmt)).scalars().all()
        if result_metadata is not None:
            result_metadata.update(
                {
                    "total_count": total_count,
                    "limit": limit_value,
                    "returned_count": len(events),
                    "truncated": truncated,
                }
            )
    else:
        if max_results is not None:
            stmt = stmt.limit(max_results + 1)
        events = (await db.execute(stmt)).scalars().all()

    if include_notes:
        await _attach_notes_to_events(db, user_id=user_id, events=events)
    else:
        await _attach_note_counts_to_events(db, user_id=user_id, events=events)

    event_ids = [event.id for event in events if isinstance(event.id, UUID)]
    persons_map = await load_persons_for_sources(
        db,
        source_model=ModelName.ActualEvent,
        source_ids=event_ids,
        link_type=LinkType.ATTENDED_BY,
        user_id=user_id,
    )

    results: List[
        Tuple[ActualEvent, List[Dict[str, Any]], Optional[Dict[str, Any]]]
    ] = []
    for event in events:
        person_summaries = _serialize_person_summaries(
            convert_persons_to_summary(persons_map.get(event.id, []))
        )
        raw_summary = build_task_summary(
            getattr(event, "task", None), include_parent_summary=False
        )
        task_summary = normalize_task_summary(raw_summary, event, as_json=False)
        results.append((event, person_summaries, task_summary))

    if event_id is not None and not results:
        raise ActualEventNotFoundError("Actual event not found")

    if (
        not allow_result_truncation
        and max_results is not None
        and len(events) > max_results
    ):
        raise ActualEventResultTooLargeError(
            f"Result set exceeds limit of {max_results} records; narrow your filters"
        )
    if (
        allow_result_truncation
        and max_results is not None
        and len(results) > max_results
    ):
        del results[max_results:]

    return results


async def list_actual_events_paginated(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    skip: int = 0,
    limit: int = 100,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    tracking_method: Optional[str] = None,
) -> Tuple[
    List[Tuple[ActualEvent, List[Dict[str, Any]], Optional[Dict[str, Any]]]], int
]:
    filters = [
        ActualEvent.user_id == user_id,
        ActualEvent.deleted_at.is_(None),
    ]
    if start_date:
        filters.append(ActualEvent.start_time >= start_date)
    if end_date:
        filters.append(ActualEvent.start_time <= end_date)
    if tracking_method:
        filters.append(ActualEvent.tracking_method == tracking_method)

    total_stmt = select(func.count()).select_from(ActualEvent).where(*filters)
    total = int((await db.execute(total_stmt)).scalar_one())

    stmt = (
        select(ActualEvent)
        .options(
            selectinload(ActualEvent.dimension),
            selectinload(ActualEvent.task).selectinload(Task.vision),
        )
        .where(*filters)
        .order_by(ActualEvent.start_time.asc())
        .offset(skip)
        .limit(limit)
    )
    events = (await db.execute(stmt)).scalars().all()

    await _attach_notes_to_events(db, user_id=user_id, events=events)

    event_ids = [event.id for event in events if isinstance(event.id, UUID)]
    persons_map = await load_persons_for_sources(
        db,
        source_model=ModelName.ActualEvent,
        source_ids=event_ids,
        link_type=LinkType.ATTENDED_BY,
        user_id=user_id,
    )

    result: List[
        Tuple[ActualEvent, List[Dict[str, Any]], Optional[Dict[str, Any]]]
    ] = []
    for event in events:
        person_summaries = _serialize_person_summaries(
            convert_persons_to_summary(persons_map.get(event.id, []))
        )
        raw_summary = build_task_summary(
            getattr(event, "task", None), include_parent_summary=False
        )
        task_summary = normalize_task_summary(raw_summary, event, as_json=False)
        result.append((event, person_summaries, task_summary))
    return result, total


async def create_actual_event(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    event_in: ActualEventCreate,
    run_async: bool = False,
) -> Tuple[ActualEvent, List[EnergyInjectionResult]]:
    completed_task_ids = event_in.completed_task_ids or []
    single_task_id = event_in.task_id
    person_ids = event_in.person_ids or []
    event_data = event_in.model_dump(exclude={"completed_task_ids", "person_ids"})

    db_event = ActualEvent(**event_data, user_id=user_id)
    db.add(db_event)
    await db.flush()

    if single_task_id is not None:
        if not await _task_exists(db, user_id=user_id, task_id=single_task_id):
            raise AssociatedTaskNotFoundError("Associated task not found")
        db_event.task_id = single_task_id
    elif completed_task_ids:
        raise DeprecatedFieldError(
            "completed_task_ids is deprecated. Use task_id to associate a single task."
        )

    if person_ids:
        await set_links(
            db,
            source_model=ModelName.ActualEvent,
            source_id=db_event.id,
            target_model=ModelName.Person,
            target_ids=person_ids,
            link_type=LinkType.ATTENDED_BY,
            replace=True,
            user_id=user_id,
        )

    await commit_safely(db)
    await db.refresh(db_event)

    affected_task_ids: List[UUID] = []
    affected_vision_ids: List[UUID] = []
    if db_event.task_id:
        affected_task_ids.append(db_event.task_id)
        vision_id = await _get_task_vision_id(
            db, user_id=user_id, task_id=db_event.task_id
        )
        if vision_id:
            affected_vision_ids.append(vision_id)

    try:
        await _recompute_daily_stats(db, db_event, user_id=user_id)
        logger.info("Successfully recomputed daily stats for event %s", db_event.id)
    except Exception as exc:  # pragma: no cover - defensive logging
        log_exception(
            logger,
            f"Failed to recompute daily stats for event {db_event.id}: {exc}",
            sys.exc_info(),
        )

    event_with_relations = await _reload_event_with_relations(
        db, user_id=user_id, event_id=db_event.id
    )

    if affected_task_ids or affected_vision_ids:
        await _schedule_recalc_jobs(
            db,
            user_id=user_id,
            task_ids=affected_task_ids,
            vision_ids=affected_vision_ids,
            reason="actual_event:create",
            run_async=run_async,
        )

    return event_with_relations or db_event, []


async def update_actual_event(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    event_id: UUID,
    update_in: ActualEventUpdate,
    run_async: bool = False,
) -> Tuple[ActualEvent, List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    stmt = (
        select(ActualEvent)
        .options(
            selectinload(ActualEvent.dimension),
            selectinload(ActualEvent.task).selectinload(Task.vision),
        )
        .where(
            ActualEvent.id == event_id,
            ActualEvent.user_id == user_id,
            ActualEvent.deleted_at.is_(None),
        )
        .limit(1)
    )
    db_event = (await db.execute(stmt)).scalar_one_or_none()
    if not db_event:
        raise ActualEventNotFoundError("Actual event not found")

    update_data = update_in.model_dump(exclude_unset=True)
    person_field_present = "person_ids" in update_data
    person_ids = update_data.pop("person_ids", None)
    completed_task_ids = update_data.pop("completed_task_ids", None)
    task_field_present = "task_id" in update_data
    new_task_id = update_data.pop("task_id", None)

    for field, value in update_data.items():
        setattr(db_event, field, value)

    if person_field_present:
        requested_ids = list(person_ids or [])
        valid_ids: List[UUID] = []
        if requested_ids:
            stmt = select(Person.id).where(
                Person.id.in_(requested_ids),
                Person.user_id == user_id,
                Person.deleted_at.is_(None),
            )
            valid_ids = (await db.execute(stmt)).scalars().all()
        await set_links(
            db,
            source_model=ModelName.ActualEvent,
            source_id=db_event.id,
            target_model=ModelName.Person,
            target_ids=valid_ids,
            link_type=LinkType.ATTENDED_BY,
            replace=True,
            user_id=user_id,
        )

    old_task_id = db_event.task_id
    old_task_vision_id = await _get_task_vision_id(
        db, user_id=user_id, task_id=old_task_id
    )

    if task_field_present:
        if new_task_id is not None:
            if not await _task_exists(db, user_id=user_id, task_id=new_task_id):
                raise AssociatedTaskNotFoundError("Associated task not found")
            db_event.task_id = new_task_id
        else:
            db_event.task_id = None

    if completed_task_ids:
        raise DeprecatedFieldError(
            "completed_task_ids is deprecated. Use task_id to associate a single task."
        )

    await commit_safely(db)
    await db.refresh(db_event)

    try:
        await _recompute_daily_stats(db, db_event, user_id=user_id)
        logger.info("Successfully recomputed daily stats for event %s", db_event.id)
    except Exception as exc:  # pragma: no cover - defensive logging
        log_exception(
            logger,
            f"Failed to recompute daily stats for updated event {db_event.id}: {exc}",
            sys.exc_info(),
        )

    target_event = await _reload_event_with_relations(
        db, user_id=user_id, event_id=db_event.id
    )
    target_event = target_event or db_event
    await _attach_notes_to_events(db, user_id=user_id, events=[target_event])

    persons_map = await load_persons_for_sources(
        db,
        source_model=ModelName.ActualEvent,
        source_ids=[target_event.id],
        link_type=LinkType.ATTENDED_BY,
        user_id=user_id,
    )
    person_summaries = _serialize_person_summaries(
        convert_persons_to_summary(persons_map.get(target_event.id, []))
    )

    raw_summary = build_task_summary(
        getattr(target_event, "task", None), include_parent_summary=False
    )
    task_summary = normalize_task_summary(raw_summary, target_event, as_json=False)

    affected_task_ids = [
        tid for tid in {old_task_id, target_event.task_id} if tid is not None
    ]
    affected_vision_ids = [
        vid
        for vid in {
            old_task_vision_id,
            task_summary.get("vision_id") if task_summary else None,
        }
        if vid is not None
    ]

    if affected_task_ids or affected_vision_ids:
        await _schedule_recalc_jobs(
            db,
            user_id=user_id,
            task_ids=affected_task_ids,
            vision_ids=affected_vision_ids,
            reason="actual_event:update",
            run_async=run_async,
        )

    return target_event, person_summaries, task_summary


async def delete_actual_event(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    event_id: UUID,
    hard_delete: bool = False,
    run_async: bool = False,
) -> None:
    stmt = (
        select(ActualEvent)
        .options(
            selectinload(ActualEvent.dimension),
            selectinload(ActualEvent.task).selectinload(Task.vision),
        )
        .where(
            ActualEvent.id == event_id,
            ActualEvent.user_id == user_id,
            ActualEvent.deleted_at.is_(None),
        )
        .limit(1)
    )
    db_event = (await db.execute(stmt)).scalar_one_or_none()
    if not db_event:
        raise ActualEventNotFoundError("Actual event not found")

    old_task_id = db_event.task_id
    old_task_vision_id = await _get_task_vision_id(
        db, user_id=user_id, task_id=old_task_id
    )

    if hard_delete:
        await db.delete(db_event)
    else:
        db_event.soft_delete()

    await commit_safely(db)

    try:
        await _recompute_daily_stats(db, db_event, user_id=user_id)
        logger.info("Successfully recomputed stats for deleted event %s", db_event.id)
    except Exception as exc:  # pragma: no cover - defensive logging
        log_exception(
            logger,
            f"Failed to recompute stats for deleted event {db_event.id}: {exc}",
            sys.exc_info(),
        )

    task_ids = [old_task_id] if old_task_id else []
    vision_ids = [old_task_vision_id] if old_task_vision_id else []
    if task_ids or vision_ids:
        await _schedule_recalc_jobs(
            db,
            user_id=user_id,
            task_ids=task_ids,
            vision_ids=vision_ids,
            reason="actual_event:delete",
            run_async=run_async,
        )


async def quick_end_actual_event(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    event_id: UUID,
    run_async: bool = False,
) -> Tuple[ActualEvent, List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    stmt = (
        select(ActualEvent)
        .where(
            ActualEvent.user_id == user_id,
            ActualEvent.id == event_id,
            ActualEvent.deleted_at.is_(None),
        )
        .limit(1)
    )
    db_event = (await db.execute(stmt)).scalar_one_or_none()
    if db_event is None:
        raise ActualEventNotFoundError("Actual event not found")

    db_event.end_time = utc_now()
    await commit_safely(db)
    await db.refresh(db_event)

    persons_map = await load_persons_for_sources(
        db,
        source_model=ModelName.ActualEvent,
        source_ids=[db_event.id],
        link_type=LinkType.ATTENDED_BY,
        user_id=user_id,
    )
    person_summaries = _serialize_person_summaries(
        convert_persons_to_summary(persons_map.get(db_event.id, []))
    )

    target_event = await _reload_event_with_relations(
        db, user_id=user_id, event_id=db_event.id
    )
    target_event = target_event or db_event
    await _attach_notes_to_events(db, user_id=user_id, events=[target_event])

    raw_summary = build_task_summary(
        getattr(target_event, "task", None), include_parent_summary=False
    )
    task_summary = normalize_task_summary(raw_summary, target_event, as_json=False)
    affected_task_ids = [target_event.task_id] if target_event.task_id else []
    affected_vision_ids: List[UUID] = []
    if task_summary and task_summary.get("vision_id"):
        affected_vision_ids.append(task_summary["vision_id"])

    if affected_task_ids or affected_vision_ids:
        await _schedule_recalc_jobs(
            db,
            user_id=user_id,
            task_ids=affected_task_ids,
            vision_ids=affected_vision_ids,
            reason="actual_event:quick_end",
            run_async=run_async,
        )

    return target_event, person_summaries, task_summary


async def restore_actual_event(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    event_id: UUID,
    run_async: bool = False,
) -> Tuple[ActualEvent, List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    stmt = (
        select(ActualEvent)
        .options(
            selectinload(ActualEvent.dimension),
            selectinload(ActualEvent.task).selectinload(Task.vision),
        )
        .where(
            ActualEvent.user_id == user_id,
            ActualEvent.id == event_id,
        )
        .limit(1)
    )
    db_event = (await db.execute(stmt)).scalar_one_or_none()
    if db_event is None:
        raise ActualEventNotFoundError("Actual event not found")
    if db_event.deleted_at is None:
        raise ActualEventNotDeletedError("Event is not deleted")

    db_event.restore()
    await commit_safely(db)
    await db.refresh(db_event)

    persons_map = await load_persons_for_sources(
        db,
        source_model=ModelName.ActualEvent,
        source_ids=[db_event.id],
        link_type=LinkType.ATTENDED_BY,
        user_id=user_id,
    )
    person_summaries = _serialize_person_summaries(
        convert_persons_to_summary(persons_map.get(db_event.id, []))
    )

    reloaded_event = await _reload_event_with_relations(
        db, user_id=user_id, event_id=db_event.id
    )
    target_event = reloaded_event or db_event
    await _attach_notes_to_events(db, user_id=user_id, events=[target_event])

    raw_summary = build_task_summary(
        getattr(target_event, "task", None), include_parent_summary=False
    )
    task_summary = normalize_task_summary(raw_summary, target_event, as_json=False)
    affected_task_ids = [target_event.task_id] if target_event.task_id else []
    affected_vision_ids: List[UUID] = []
    if task_summary and task_summary.get("vision_id"):
        affected_vision_ids.append(task_summary["vision_id"])

    if affected_task_ids or affected_vision_ids:
        await _schedule_recalc_jobs(
            db,
            user_id=user_id,
            task_ids=affected_task_ids,
            vision_ids=affected_vision_ids,
            reason="actual_event:restore",
            run_async=run_async,
        )

    return target_event, person_summaries, task_summary


async def batch_create_actual_events(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    events_data: List[ActualEventCreate],
    run_async: bool = False,
) -> Tuple[
    int,
    int,
    List[Tuple[ActualEvent, List[Dict[str, Any]], Optional[Dict[str, Any]]]],
    List[str],
]:
    created_count = 0
    failed_count = 0
    created_events: List[
        Tuple[ActualEvent, List[Dict[str, Any]], Optional[Dict[str, Any]]]
    ] = []
    errors: List[str] = []

    for index, event_data in enumerate(events_data, 1):
        try:
            db_event, _ = await create_actual_event(
                db,
                user_id=user_id,
                event_in=event_data,
                run_async=run_async,
            )

            persons_map = await load_persons_for_sources(
                db,
                source_model=ModelName.ActualEvent,
                source_ids=[db_event.id],
                link_type=LinkType.ATTENDED_BY,
                user_id=user_id,
            )
            person_summaries = _serialize_person_summaries(
                convert_persons_to_summary(persons_map.get(db_event.id, []))
            )
            raw_summary = build_task_summary(
                getattr(db_event, "task", None), include_parent_summary=False
            )
            task_summary = normalize_task_summary(raw_summary, db_event, as_json=False)
            created_events.append((db_event, person_summaries, task_summary))
            created_count += 1
        except Exception as exc:  # noqa: BLE001
            log_exception(
                logger, f"Failed to create event {index}: {exc}", sys.exc_info()
            )
            errors.append(f"Event {index}: {exc}")
            failed_count += 1
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass

    return created_count, failed_count, created_events, errors


async def batch_delete_actual_events(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    event_ids: List[str],
    hard_delete: bool = False,
    run_async: bool = False,
) -> Tuple[int, List[str], List[str]]:
    deleted_count = 0
    failed_ids: List[str] = []
    errors: List[str] = []

    for raw_id in event_ids:
        event_id_str = str(raw_id)
        try:
            normalized = validate_uuid_field(raw_id, "event_id")
        except ValueError:
            normalized = None
        if normalized is None:
            failed_ids.append(event_id_str)
            errors.append(f"Event with ID {event_id_str} not found")
            continue

        try:
            await delete_actual_event(
                db,
                user_id=user_id,
                event_id=normalized,
                hard_delete=hard_delete,
                run_async=run_async,
            )
            deleted_count += 1
        except ActualEventNotFoundError:
            failed_ids.append(event_id_str)
            errors.append(f"Event with ID {event_id_str} not found")
        except Exception as exc:  # noqa: BLE001
            failed_ids.append(event_id_str)
            errors.append(f"Failed to delete event {event_id_str}: {exc}")
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass

    return deleted_count, failed_ids, errors


async def batch_restore_actual_events(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    event_ids: List[str],
    run_async: bool = False,
) -> Tuple[int, List[str], List[str]]:
    restored_count = 0
    failed_ids: List[str] = []
    errors: List[str] = []

    for raw_id in event_ids:
        event_id_str = str(raw_id)
        try:
            normalized = validate_uuid_field(raw_id, "event_id")
        except ValueError:
            normalized = None
        if normalized is None:
            failed_ids.append(event_id_str)
            errors.append(f"Event with ID {event_id_str} not found")
            continue

        try:
            await restore_actual_event(
                db,
                user_id=user_id,
                event_id=normalized,
                run_async=run_async,
            )
            restored_count += 1
        except ActualEventNotFoundError:
            failed_ids.append(event_id_str)
            errors.append(f"Event with ID {event_id_str} not found")
        except ActualEventNotDeletedError:
            failed_ids.append(event_id_str)
            errors.append(f"Event with ID {event_id_str} is not deleted")
        except Exception as exc:  # noqa: BLE001
            failed_ids.append(event_id_str)
            errors.append(f"Failed to restore event {event_id_str}: {exc}")
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass

    return restored_count, failed_ids, errors


async def batch_update_actual_events(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    event_ids: List[str],
    update_type: str,
    persons: Optional[Dict[str, Any]] = None,
    title: Optional[Dict[str, str]] = None,
    task: Optional[Dict[str, Any]] = None,
    dimension: Optional[Dict[str, int]] = None,
    run_async: bool = False,
) -> Tuple[int, List[str], List[str]]:
    updated_count = 0
    failed_ids: List[str] = []
    errors: List[str] = []

    processed_ids: List[Tuple[str, UUID]] = []
    for raw_id in event_ids:
        event_id_str = str(raw_id)
        try:
            normalized = validate_uuid_field(raw_id, "event_id")
        except ValueError:
            failed_ids.append(event_id_str)
            errors.append(f"Event with ID {event_id_str} not found")
            continue
        if normalized is None:
            failed_ids.append(event_id_str)
            errors.append(f"Event with ID {event_id_str} not found")
            continue
        processed_ids.append((event_id_str, normalized))

    if not processed_ids:
        return updated_count, failed_ids, errors

    normalized_ids = [event_uuid for _, event_uuid in processed_ids]
    stmt = select(ActualEvent).where(
        ActualEvent.user_id == user_id,
        ActualEvent.deleted_at.is_(None),
        ActualEvent.id.in_(normalized_ids),
    )
    events = (await db.execute(stmt)).scalars().all()
    event_dict = {str(event.id): event for event in events}

    affected_task_ids: set[UUID] = set()

    for event_id_str, event_uuid in processed_ids:
        try:
            db_event = event_dict.get(str(event_uuid))
            if db_event is None:
                failed_ids.append(event_id_str)
                errors.append(f"Event with ID {event_id_str} not found")
                continue

            if update_type == "persons" and persons:
                mode = persons.get("mode", "replace")
                person_ids = persons.get("person_ids", [])
                if mode == "replace":
                    await set_links(
                        db,
                        source_model=ModelName.ActualEvent,
                        source_id=db_event.id,
                        target_model=ModelName.Person,
                        target_ids=person_ids,
                        link_type=LinkType.ATTENDED_BY,
                        replace=True,
                        user_id=user_id,
                    )
                elif mode == "add":
                    existing = await load_persons_for_sources(
                        db,
                        source_model=ModelName.ActualEvent,
                        source_ids=[db_event.id],
                        link_type=LinkType.ATTENDED_BY,
                        user_id=user_id,
                    )
                    existing_ids = [
                        getattr(person, "id", None)
                        for person in existing.get(db_event.id, [])
                        if getattr(person, "id", None)
                    ]
                    combined_ids = list({*existing_ids, *person_ids})
                    await set_links(
                        db,
                        source_model=ModelName.ActualEvent,
                        source_id=db_event.id,
                        target_model=ModelName.Person,
                        target_ids=combined_ids,
                        link_type=LinkType.ATTENDED_BY,
                        replace=True,
                        user_id=user_id,
                    )
                elif mode == "clear":
                    await set_links(
                        db,
                        source_model=ModelName.ActualEvent,
                        source_id=db_event.id,
                        target_model=ModelName.Person,
                        target_ids=[],
                        link_type=LinkType.ATTENDED_BY,
                        replace=True,
                        user_id=user_id,
                    )

            elif update_type == "title" and title:
                mode = title.get("mode", "replace")
                value = title.get("value", "")
                find_text = title.get("find", "")
                if mode == "replace":
                    db_event.title = value
                elif mode == "find_replace" and find_text:
                    db_event.title = db_event.title.replace(find_text, value)

            elif update_type == "task" and task:
                mode = task.get("mode", "replace")
                task_id = task.get("task_id")
                previous_task_id = db_event.task_id
                if mode == "replace":
                    db_event.task_id = task_id
                elif mode == "clear":
                    db_event.task_id = None

                for tid in {previous_task_id, db_event.task_id}:
                    if tid is not None:
                        affected_task_ids.add(tid)

            elif update_type == "dimension" and dimension:
                if "dimension_id" in dimension:
                    db_event.dimension_id = dimension.get("dimension_id")

            updated_count += 1
        except Exception as exc:  # noqa: BLE001
            failed_ids.append(event_id_str)
            errors.append(f"Failed to update event {event_id_str}: {exc}")

    if updated_count > 0:
        await commit_safely(db)
        affected_vision_ids: set[UUID] = set()
        if affected_task_ids:
            task_stmt = select(Task.id, Task.vision_id).where(
                Task.user_id == user_id,
                Task.deleted_at.is_(None),
                Task.id.in_(affected_task_ids),
            )
            rows = await db.execute(task_stmt)
            for task_id, vision_id in rows.all():
                affected_task_ids.add(task_id)
                if vision_id:
                    affected_vision_ids.add(vision_id)

        if affected_task_ids or affected_vision_ids:
            await _schedule_recalc_jobs(
                db,
                user_id=user_id,
                task_ids=list(affected_task_ids),
                vision_ids=list(affected_vision_ids),
                reason=f"actual_event:batch_update:{update_type}",
                run_async=run_async,
            )

    return updated_count, failed_ids, errors


__all__ = [
    "ActualEventNotDeletedError",
    "ActualEventNotFoundError",
    "ActualEventResultTooLargeError",
    "AssociatedTaskNotFoundError",
    "DEFAULT_MAX_SEARCH_DAYS",
    "DEFAULT_MAX_SEARCH_RESULTS",
    "DeprecatedFieldError",
    "batch_create_actual_events",
    "batch_delete_actual_events",
    "batch_restore_actual_events",
    "batch_update_actual_events",
    "create_actual_event",
    "delete_actual_event",
    "list_actual_events_paginated",
    "quick_end_actual_event",
    "restore_actual_event",
    "search_actual_events",
    "update_actual_event",
]
