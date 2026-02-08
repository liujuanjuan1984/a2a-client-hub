"""Async service layer for planned events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Union
from uuid import UUID

from sqlalchemy import Column, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    PLANNED_EVENT_ALLOWED_STATUSES,
    PLANNED_EVENT_EXCEPTION_ACTION_OVERRIDE,
    PLANNED_EVENT_EXCEPTION_ACTION_SKIP,
    PLANNED_EVENT_EXCEPTION_ACTION_TRUNCATE,
)
from app.db.models.planned_event import PlannedEvent
from app.db.models.planned_event_occurrence_exception import (
    PlannedEventOccurrenceException,
)
from app.db.transaction import commit_safely
from app.handlers.associations import LinkType, ModelName
from app.handlers.associations_async import (
    attach_persons_for_sources,
    load_persons_for_sources,
    set_links,
)
from app.schemas.planned_event import (
    PlannedEventCreate,
    PlannedEventResponse,
    PlannedEventUpdate,
)
from app.utils.person_utils import convert_persons_to_summary
from app.utils.recurring_events import (
    RecurringEventExceptionBundle,
    compute_instance_id,
    expand_planned_events_with_recurrence,
    infer_rrule_series_end,
)


class PlannedEventNotFoundError(Exception):
    """Raised when a planned event is not found."""


class InvalidPlannedEventStatusError(Exception):
    """Raised when an invalid status filter is provided."""


class InvalidDeleteTypeError(Exception):
    """Raised when a delete_type argument is invalid."""


class InvalidUpdateScopeError(Exception):
    """Raised when an update scope argument is invalid."""


INSTANCE_OVERRIDE_ALLOWED_FIELDS = {
    "title",
    "start_time",
    "end_time",
    "priority",
    "dimension_id",
    "task_id",
    "is_all_day",
    "status",
    "tags",
    "extra_data",
}
VALID_UPDATE_SCOPES = {"single", "all_future", "all"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _active_clause(user_id: Union[UUID, Column]):
    return and_(PlannedEvent.user_id == user_id, PlannedEvent.deleted_at.is_(None))


def _build_planned_events_query(
    *,
    user_id: Union[UUID, Column],
    status: Optional[str],
    task_id: Optional[UUID],
) -> Any:
    stmt = select(PlannedEvent).where(_active_clause(user_id))
    if status is not None:
        if status not in PLANNED_EVENT_ALLOWED_STATUSES:
            raise InvalidPlannedEventStatusError(
                "Invalid status filter. Must be one of: "
                + ", ".join(sorted(PLANNED_EVENT_ALLOWED_STATUSES))
            )
        stmt = stmt.where(PlannedEvent.status == status)
    if task_id is not None:
        stmt = stmt.where(PlannedEvent.task_id == task_id)
    return stmt


async def _fetch_event(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    event_id: UUID,
) -> PlannedEvent:
    stmt = select(PlannedEvent).where(
        _active_clause(user_id),
        PlannedEvent.id == event_id,
    )
    result = await db.execute(stmt.limit(1))
    event = result.scalars().first()
    if event is None:
        raise PlannedEventNotFoundError("Planned event not found")
    return event


async def _load_occurrence_exceptions(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    master_event_ids: Sequence[UUID],
) -> Dict[UUID, RecurringEventExceptionBundle]:
    if not master_event_ids:
        return {}

    stmt = (
        select(PlannedEventOccurrenceException)
        .where(
            PlannedEventOccurrenceException.user_id == user_id,
            PlannedEventOccurrenceException.master_event_id.in_(master_event_ids),
            PlannedEventOccurrenceException.deleted_at.is_(None),
        )
        .order_by(PlannedEventOccurrenceException.updated_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()

    bundles: Dict[UUID, RecurringEventExceptionBundle] = {}
    for row in rows:
        bundle = bundles.setdefault(
            row.master_event_id, RecurringEventExceptionBundle()
        )
        if row.action == PLANNED_EVENT_EXCEPTION_ACTION_SKIP:
            if row.instance_id is not None:
                bundle.skip_instance_ids.add(row.instance_id)
            bundle.skip_instance_starts.add(row.instance_start)
        elif row.action == PLANNED_EVENT_EXCEPTION_ACTION_TRUNCATE:
            bundle.truncate_after = row.instance_start
        elif row.action == PLANNED_EVENT_EXCEPTION_ACTION_OVERRIDE:
            payload = row.payload or {}
            if row.instance_id is not None:
                bundle.override_payloads_by_instance_id[row.instance_id] = payload
            bundle.override_payloads_by_instance_start[row.instance_start] = payload
    return bundles


def _series_cutoff(
    event: PlannedEvent,
    bundle: Optional[RecurringEventExceptionBundle],
) -> Optional[datetime]:
    candidates: List[datetime] = []
    if bundle and bundle.truncate_after is not None:
        candidates.append(bundle.truncate_after)
    inferred = infer_rrule_series_end(event.start_time, event.rrule_string)
    if inferred is not None:
        candidates.append(inferred)
    if not candidates:
        return None
    return min(candidates)


def _series_has_future_instances(
    event: PlannedEvent,
    bundle: Optional[RecurringEventExceptionBundle],
    window_start: datetime,
) -> bool:
    cutoff = _series_cutoff(event, bundle)
    if cutoff is None:
        return True
    return cutoff >= window_start


def _normalize_instance_start(instance_start: Optional[datetime]) -> Optional[datetime]:
    if instance_start is None:
        return None
    if instance_start.tzinfo is None:
        return instance_start.replace(tzinfo=timezone.utc)
    return instance_start


async def _record_skip_exception(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    master_event_id: UUID,
    instance_start: datetime,
    instance_id: UUID,
) -> PlannedEventOccurrenceException:
    stmt = (
        select(PlannedEventOccurrenceException)
        .where(
            PlannedEventOccurrenceException.user_id == user_id,
            PlannedEventOccurrenceException.master_event_id == master_event_id,
            PlannedEventOccurrenceException.action
            == PLANNED_EVENT_EXCEPTION_ACTION_SKIP,
            PlannedEventOccurrenceException.instance_start == instance_start,
        )
        .limit(1)
    )
    existing = (await db.execute(stmt)).scalars().first()
    if existing:
        existing.instance_id = instance_id
        existing.deleted_at = None
        return existing

    exception = PlannedEventOccurrenceException(
        user_id=user_id,
        master_event_id=master_event_id,
        action=PLANNED_EVENT_EXCEPTION_ACTION_SKIP,
        instance_id=instance_id,
        instance_start=instance_start,
    )
    db.add(exception)
    return exception


async def _record_truncate_exception(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    master_event_id: UUID,
    instance_start: datetime,
    instance_id: Optional[UUID],
) -> PlannedEventOccurrenceException:
    stmt = (
        select(PlannedEventOccurrenceException)
        .where(
            PlannedEventOccurrenceException.user_id == user_id,
            PlannedEventOccurrenceException.master_event_id == master_event_id,
            PlannedEventOccurrenceException.action
            == PLANNED_EVENT_EXCEPTION_ACTION_TRUNCATE,
        )
        .limit(1)
    )
    existing = (await db.execute(stmt)).scalars().first()
    if existing:
        existing.instance_start = instance_start
        existing.instance_id = instance_id
        existing.deleted_at = None
        return existing

    exception = PlannedEventOccurrenceException(
        user_id=user_id,
        master_event_id=master_event_id,
        action=PLANNED_EVENT_EXCEPTION_ACTION_TRUNCATE,
        instance_id=instance_id,
        instance_start=instance_start,
    )
    db.add(exception)
    return exception


def _serialize_override_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    serialized: Dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, datetime):
            serialized[key] = value.isoformat()
        else:
            serialized[key] = value
    return serialized


async def _record_override_exception(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    master_event_id: UUID,
    instance_start: datetime,
    instance_id: UUID,
    payload: Dict[str, Any],
) -> PlannedEventOccurrenceException:
    serialized_payload = _serialize_override_payload(payload)
    conditions = [
        PlannedEventOccurrenceException.user_id == user_id,
        PlannedEventOccurrenceException.master_event_id == master_event_id,
        PlannedEventOccurrenceException.action
        == PLANNED_EVENT_EXCEPTION_ACTION_OVERRIDE,
    ]
    if instance_id is not None:
        conditions.append(
            or_(
                PlannedEventOccurrenceException.instance_id == instance_id,
                PlannedEventOccurrenceException.instance_start == instance_start,
            )
        )
    else:
        conditions.append(
            PlannedEventOccurrenceException.instance_start == instance_start
        )

    stmt = (
        select(PlannedEventOccurrenceException)
        .where(*conditions)
        .order_by(PlannedEventOccurrenceException.updated_at.desc())
    )
    matches = (await db.execute(stmt)).scalars().all()
    if matches:
        primary = matches[0]
        primary.instance_id = instance_id
        primary.instance_start = instance_start
        existing_payload = primary.payload or {}
        primary.payload = {**existing_payload, **serialized_payload}
        primary.deleted_at = None
        for duplicate in matches[1:]:
            if duplicate.deleted_at is None:
                duplicate.soft_delete()
        return primary

    exception = PlannedEventOccurrenceException(
        user_id=user_id,
        master_event_id=master_event_id,
        action=PLANNED_EVENT_EXCEPTION_ACTION_OVERRIDE,
        instance_id=instance_id,
        instance_start=instance_start,
        payload=serialized_payload,
    )
    db.add(exception)
    return exception


async def _fetch_person_ids_for_event(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    event_id: UUID,
) -> List[str]:
    persons_map = await load_persons_for_sources(
        db,
        source_model=ModelName.PlannedEvent,
        source_ids=[event_id],
        link_type=LinkType.INVITED,
        user_id=user_id,
    )
    return [str(person.id) for person in persons_map.get(event_id, [])]


async def _create_future_master_event(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    source_event: PlannedEvent,
    update_data: Dict[str, Any],
    person_ids: Optional[List[str]],
    instance_start: datetime,
) -> PlannedEvent:
    new_start_time = update_data.get("start_time") or instance_start
    if new_start_time is None:
        raise InvalidUpdateScopeError(
            "start_time or instance_start is required for update_type='all_future'"
        )

    if isinstance(new_start_time, str):
        new_start_time = datetime.fromisoformat(new_start_time.replace("Z", "+00:00"))

    if "end_time" in update_data:
        new_end_time = update_data["end_time"]
        if isinstance(new_end_time, str):
            new_end_time = datetime.fromisoformat(new_end_time.replace("Z", "+00:00"))
    elif source_event.end_time is not None:
        duration = source_event.end_time - source_event.start_time
        new_end_time = new_start_time + duration
    else:
        new_end_time = None

    rrule_value = update_data.get("rrule_string", source_event.rrule_string)
    if "is_recurring" in update_data:
        is_recurring_value = bool(update_data["is_recurring"])
    else:
        is_recurring_value = bool(rrule_value)

    new_event = PlannedEvent(
        user_id=user_id,
        title=update_data.get("title", source_event.title),
        start_time=new_start_time,
        end_time=new_end_time,
        priority=update_data.get("priority", source_event.priority),
        dimension_id=update_data.get("dimension_id", source_event.dimension_id),
        task_id=update_data.get("task_id", source_event.task_id),
        is_all_day=update_data.get("is_all_day", source_event.is_all_day),
        is_recurring=is_recurring_value,
        recurrence_pattern=update_data.get(
            "recurrence_pattern", source_event.recurrence_pattern
        ),
        rrule_string=rrule_value,
        status=update_data.get("status", source_event.status),
        tags=update_data.get("tags", source_event.tags),
        extra_data=update_data.get("extra_data", source_event.extra_data),
    )
    db.add(new_event)
    await db.flush()

    resolved_person_ids: Optional[List[str]]
    if person_ids is not None:
        resolved_person_ids = person_ids
    else:
        resolved_person_ids = await _fetch_person_ids_for_event(
            db, user_id=user_id, event_id=source_event.id
        )

    if resolved_person_ids:
        await set_links(
            db,
            source_model=ModelName.PlannedEvent,
            source_id=new_event.id,
            target_model=ModelName.Person,
            target_ids=resolved_person_ids,
            link_type=LinkType.INVITED,
            replace=True,
            user_id=user_id,
        )

    return new_event


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def create_planned_event(
    db: AsyncSession, *, user_id: Union[UUID, Column], event_in: PlannedEventCreate
) -> PlannedEvent:
    data = event_in.model_dump()
    person_ids = data.pop("person_ids", None)

    planned_event = PlannedEvent(**data, user_id=user_id)
    db.add(planned_event)
    await db.flush()

    if person_ids:
        await set_links(
            db,
            source_model=ModelName.PlannedEvent,
            source_id=planned_event.id,
            target_model=ModelName.Person,
            target_ids=person_ids,
            link_type=LinkType.INVITED,
            replace=True,
            user_id=user_id,
        )

    await commit_safely(db)
    await db.refresh(planned_event)

    await attach_persons_for_sources(
        db,
        source_model=ModelName.PlannedEvent,
        items=[planned_event],
        link_type=LinkType.INVITED,
        user_id=user_id,
    )
    planned_event.persons = convert_persons_to_summary(  # type: ignore[attr-defined]
        getattr(planned_event, "persons", [])
    )
    return planned_event


async def get_planned_event(
    db: AsyncSession, *, user_id: Union[UUID, Column], event_id: UUID
) -> PlannedEvent:
    event = await _fetch_event(db, user_id=user_id, event_id=event_id)
    await attach_persons_for_sources(
        db,
        source_model=ModelName.PlannedEvent,
        items=[event],
        link_type=LinkType.INVITED,
        user_id=user_id,
    )
    event.persons = convert_persons_to_summary(  # type: ignore[attr-defined]
        getattr(event, "persons", [])
    )
    return event


async def list_planned_events(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    status: Optional[str] = None,
    task_id: Optional[UUID] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[PlannedEvent]:
    stmt = _build_planned_events_query(
        user_id=user_id,
        status=status,
        task_id=task_id,
    )
    stmt = stmt.order_by(PlannedEvent.start_time.asc()).offset(skip).limit(limit)
    events = (await db.execute(stmt)).scalars().all()
    if not events:
        return []
    await attach_persons_for_sources(
        db,
        source_model=ModelName.PlannedEvent,
        items=events,
        link_type=LinkType.INVITED,
        user_id=user_id,
    )
    for event in events:
        event.persons = convert_persons_to_summary(  # type: ignore[attr-defined]
            getattr(event, "persons", [])
        )
    return events


async def list_planned_events_with_total(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    status: Optional[str] = None,
    task_id: Optional[UUID] = None,
    skip: int = 0,
    limit: int = 100,
) -> tuple[List[PlannedEvent], int]:
    stmt = _build_planned_events_query(
        user_id=user_id,
        status=status,
        task_id=task_id,
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    stmt = stmt.order_by(PlannedEvent.start_time.asc()).offset(skip).limit(limit)
    events = (await db.execute(stmt)).scalars().all()
    total = await db.scalar(count_stmt)
    if not events:
        return [], int(total or 0)

    await attach_persons_for_sources(
        db,
        source_model=ModelName.PlannedEvent,
        items=events,
        link_type=LinkType.INVITED,
        user_id=user_id,
    )
    for event in events:
        event.persons = convert_persons_to_summary(  # type: ignore[attr-defined]
            getattr(event, "persons", [])
        )
    return events, int(total or 0)


async def list_planned_events_in_range(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    start: datetime,
    end: datetime,
    status: Optional[str] = None,
) -> List[Dict]:
    if status is not None and status not in PLANNED_EVENT_ALLOWED_STATUSES:
        raise InvalidPlannedEventStatusError(
            "Invalid status filter. Must be one of: "
            + ", ".join(sorted(PLANNED_EVENT_ALLOWED_STATUSES))
        )

    non_recurring_filters = [
        _active_clause(user_id),
        PlannedEvent.rrule_string.is_(None),
        PlannedEvent.start_time <= end,
        or_(
            PlannedEvent.end_time >= start,
            and_(PlannedEvent.end_time.is_(None), PlannedEvent.start_time >= start),
        ),
    ]
    recurring_filters = [
        _active_clause(user_id),
        PlannedEvent.rrule_string.is_not(None),
    ]
    if status is not None:
        non_recurring_filters.append(PlannedEvent.status == status)
        recurring_filters.append(PlannedEvent.status == status)

    non_recurring_stmt = (
        select(PlannedEvent)
        .where(*non_recurring_filters)
        .order_by(PlannedEvent.start_time.asc())
    )
    recurring_stmt = select(PlannedEvent).where(*recurring_filters)

    non_recurring_events = (await db.execute(non_recurring_stmt)).scalars().all()
    recurring_events = (await db.execute(recurring_stmt)).scalars().all()
    recurrence_exceptions = await _load_occurrence_exceptions(
        db,
        user_id=user_id,
        master_event_ids=[event.id for event in recurring_events],
    )
    recurring_events = [
        event
        for event in recurring_events
        if _series_has_future_instances(
            event, recurrence_exceptions.get(event.id), start
        )
    ]
    attach_targets: Sequence[PlannedEvent] = (
        non_recurring_events + recurring_events  # type: ignore[operator]
    )
    if attach_targets:
        await attach_persons_for_sources(
            db,
            source_model=ModelName.PlannedEvent,
            items=attach_targets,
            link_type=LinkType.INVITED,
            user_id=user_id,
        )
        for event in attach_targets:
            event.persons = convert_persons_to_summary(  # type: ignore[attr-defined]
                getattr(event, "persons", [])
            )

    base_responses = [
        PlannedEventResponse.model_validate(event)
        for event in (non_recurring_events + recurring_events)
    ]
    expanded = expand_planned_events_with_recurrence(
        base_responses, start, end, exceptions=recurrence_exceptions
    )
    expanded.sort(key=lambda row: row["start_time"])
    return expanded


async def update_planned_event(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    event_id: UUID,
    update_in: PlannedEventUpdate,
    update_scope: str = "all",
    instance_id: Optional[UUID] = None,
    instance_start: Optional[datetime] = None,
) -> PlannedEvent:
    event = await _fetch_event(db, user_id=user_id, event_id=event_id)
    update_data = update_in.model_dump(exclude_unset=True)
    person_ids = update_data.pop("person_ids", None)
    normalized_scope = (update_scope or "all").lower()
    if normalized_scope not in VALID_UPDATE_SCOPES:
        raise InvalidUpdateScopeError(
            "Invalid update_type. Must be 'single', 'all_future', or 'all'"
        )

    normalized_instance_start = _normalize_instance_start(instance_start)
    if normalized_scope != "all":
        if not event.is_recurring:
            raise InvalidUpdateScopeError(
                "Scoped updates are only available for recurring events"
            )
        if normalized_instance_start is None:
            raise InvalidUpdateScopeError(
                "instance_start is required when update_type is not 'all'"
            )

    target_event: PlannedEvent = event

    if normalized_scope == "all":
        for field, value in update_data.items():
            setattr(event, field, value)
        if person_ids is not None:
            await set_links(
                db,
                source_model=ModelName.PlannedEvent,
                source_id=event.id,
                target_model=ModelName.Person,
                target_ids=person_ids or [],
                link_type=LinkType.INVITED,
                replace=True,
                user_id=user_id,
            )
    elif normalized_scope == "single":
        effective_instance_id = instance_id or compute_instance_id(
            event.id, normalized_instance_start  # type: ignore[arg-type]
        )
        allowed_payload = {
            field: value
            for field, value in update_data.items()
            if field in INSTANCE_OVERRIDE_ALLOWED_FIELDS
        }
        disallowed_fields = set(update_data) - INSTANCE_OVERRIDE_ALLOWED_FIELDS
        if disallowed_fields:
            raise InvalidUpdateScopeError(
                "The following fields cannot be overridden for a single occurrence: "
                + ", ".join(sorted(disallowed_fields))
            )
        if not allowed_payload:
            raise InvalidUpdateScopeError(
                "No override fields provided for the selected occurrence"
            )
        await _record_override_exception(
            db,
            user_id=user_id,
            master_event_id=event.id,
            instance_start=normalized_instance_start,  # type: ignore[arg-type]
            instance_id=effective_instance_id,
            payload=allowed_payload,
        )
    else:  # normalized_scope == "all_future"
        effective_instance_id = instance_id or compute_instance_id(
            event.id, normalized_instance_start  # type: ignore[arg-type]
        )
        await _record_truncate_exception(
            db,
            user_id=user_id,
            master_event_id=event.id,
            instance_start=normalized_instance_start,  # type: ignore[arg-type]
            instance_id=effective_instance_id,
        )
        target_event = await _create_future_master_event(
            db,
            user_id=user_id,
            source_event=event,
            update_data=update_data,
            person_ids=person_ids,
            instance_start=normalized_instance_start,  # type: ignore[arg-type]
        )

    await commit_safely(db)
    await db.refresh(target_event)
    persons_map = await load_persons_for_sources(
        db,
        source_model=ModelName.PlannedEvent,
        source_ids=[target_event.id],
        link_type=LinkType.INVITED,
        user_id=user_id,
    )
    target_event.persons = convert_persons_to_summary(  # type: ignore[attr-defined]
        persons_map.get(target_event.id, [])
    )
    return target_event


async def delete_planned_event(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    event_id: UUID,
    delete_type: str = "single",
    instance_id: Optional[UUID] = None,
    instance_start: Optional[datetime] = None,
) -> bool:
    event = await _fetch_event(db, user_id=user_id, event_id=event_id)
    if delete_type not in {"single", "all_future", "all"}:
        raise InvalidDeleteTypeError(
            "Invalid delete_type. Must be 'single', 'all_future', or 'all'"
        )

    normalized_instance_start = _normalize_instance_start(instance_start)

    if event.is_recurring:
        if delete_type == "single":
            if normalized_instance_start is None:
                raise InvalidDeleteTypeError(
                    "instance_start is required when deleting a single occurrence"
                )
            effective_instance_id = instance_id or compute_instance_id(
                event.id, normalized_instance_start
            )
            await _record_skip_exception(
                db,
                user_id=user_id,
                master_event_id=event.id,
                instance_start=normalized_instance_start,
                instance_id=effective_instance_id,
            )
        elif delete_type == "all_future":
            if normalized_instance_start is None:
                raise InvalidDeleteTypeError(
                    "instance_start is required when deleting future occurrences"
                )
            effective_instance_id = instance_id or compute_instance_id(
                event.id, normalized_instance_start
            )
            await _record_truncate_exception(
                db,
                user_id=user_id,
                master_event_id=event.id,
                instance_start=normalized_instance_start,
                instance_id=effective_instance_id,
            )
        else:  # delete entire series
            event.soft_delete()
    else:
        event.soft_delete()

    await commit_safely(db)
    return True


async def get_events_by_task(
    db: AsyncSession, *, user_id: Union[UUID, Column], task_id: UUID
) -> List[PlannedEvent]:
    stmt = (
        select(PlannedEvent)
        .where(_active_clause(user_id), PlannedEvent.task_id == task_id)
        .order_by(PlannedEvent.start_time.asc())
    )
    events = (await db.execute(stmt)).scalars().all()
    return events


__all__ = [
    "InvalidDeleteTypeError",
    "InvalidPlannedEventStatusError",
    "InvalidUpdateScopeError",
    "PlannedEventNotFoundError",
    "create_planned_event",
    "get_planned_event",
    "list_planned_events",
    "list_planned_events_with_total",
    "list_planned_events_in_range",
    "update_planned_event",
    "delete_planned_event",
    "get_events_by_task",
]
