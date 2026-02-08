"""
Association service utilities

Provides:
- Strongly-typed enums for allowed model names and link types
- Helpers to create/replace links with existence checks
- Helpers to query targets for sources and sources for a target
- Convenience loaders for Person associations
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional, Sequence, Set, Union
from uuid import UUID

from sqlalchemy import Column, func
from sqlalchemy.orm import Session, joinedload

from app.db.models.actual_event import ActualEvent
from app.db.models.actual_event_quick_template import ActualEventQuickTemplate
from app.db.models.association import Association
from app.db.models.note import Note
from app.db.models.person import Person
from app.db.models.planned_event import PlannedEvent
from app.db.models.task import Task
from app.db.models.vision import Vision
from app.utils.data_protocol import validate_uuid_field


class ModelName(str, Enum):
    ActualEventQuickTemplate = "ActualEventQuickTemplate"
    Vision = "Vision"
    Task = "Task"
    PlannedEvent = "PlannedEvent"
    ActualEvent = "ActualEvent"
    Note = "Note"
    Person = "Person"


class LinkType(str, Enum):
    QUICK_TEMPLATE_INVOLVES = "quick_template_involves"  # QuickTemplate -> Person
    INVOLVES = "involves"  # Vision/Task -> Person
    INVITED = "invited"  # PlannedEvent -> Person
    ATTENDED_BY = "attended_by"  # ActualEvent -> Person
    IS_ABOUT = "is_about"  # Note -> Person
    RELATES_TO = "relates_to"  # Note -> Task
    CAPTURED_FROM = "captured_from"  # Note -> ActualEvent (timelog)


MODEL_MAP = {
    ModelName.ActualEventQuickTemplate: ActualEventQuickTemplate,
    ModelName.Vision: Vision,
    ModelName.Task: Task,
    ModelName.PlannedEvent: PlannedEvent,
    ModelName.ActualEvent: ActualEvent,
    ModelName.Note: Note,
    ModelName.Person: Person,
}


def recompute_task_notes_count(
    db: Session, task_ids: Set[UUID], user_id: Optional[UUID] = None
) -> None:
    """Recalculate notes_count for the specified tasks."""
    if not task_ids:
        return

    query = (
        Association.active(db)
        .with_entities(Association.target_id, func.count(Association.id))
        .filter(
            Association.target_model == ModelName.Task.value,
            Association.source_model == ModelName.Note.value,
            Association.link_type == LinkType.RELATES_TO.value,
            Association.target_id.in_(task_ids),
        )
    )

    if user_id is not None:
        query = query.filter(Association.user_id == user_id)

    rows = query.group_by(Association.target_id).all()
    counts = {task_id: count for task_id, count in rows}

    for task_id in task_ids:
        db.query(Task).filter(Task.id == task_id).update(
            {Task.notes_count: counts.get(task_id, 0)},
            synchronize_session=False,
        )


def _assert_allowed_models(source_model: ModelName, target_model: ModelName) -> None:
    if source_model not in MODEL_MAP or target_model not in MODEL_MAP:
        raise ValueError("Unsupported model in Association operation")


def _assert_entities_exist(
    db: Session,
    model_name: ModelName,
    ids: Sequence[UUID],
    user_id: Optional[UUID] = None,
) -> Set[UUID]:
    if not ids:
        return set()

    # Use new data protocol to clean and validate IDs
    valid_ids = []
    for id_val in ids:
        try:
            cleaned_id = validate_uuid_field(id_val, "entity_id")
            if cleaned_id is not None:
                valid_ids.append(cleaned_id)
        except ValueError:
            # Skip invalid UUIDs
            continue

    if not valid_ids:
        return set()

    model_cls = MODEL_MAP[model_name]
    if hasattr(model_cls, "active"):
        query = model_cls.active(db)
        if user_id is not None and hasattr(model_cls, "user_id"):
            query = query.filter(model_cls.user_id == user_id)
    else:
        query = db.query(model_cls)

    rows = query.filter(model_cls.id.in_(valid_ids)).all()
    return {getattr(r, "id") for r in rows}  # type: ignore[attr-defined]


def set_links(
    db: Session,
    *,
    source_model: ModelName,
    source_id: Union[UUID, Column],
    target_model: ModelName,
    target_ids: Sequence[UUID],
    link_type: LinkType,
    replace: bool = True,
    user_id: Optional[UUID] = None,
) -> None:
    """Create or replace Association links after validating entities exist.

    - Validates source exists
    - Validates targets exist; ignores invalid IDs
    - If replace=True: removes existing links for the (source, target_model)
    """
    _assert_allowed_models(source_model, target_model)

    # Validate source existence
    existing_source = _assert_entities_exist(
        db, source_model, [source_id], user_id=user_id
    )
    if source_id not in existing_source:
        raise ValueError(f"Source {source_model}#{source_id} not found")

    # Validate target existence
    valid_target_ids = _assert_entities_exist(
        db, target_model, list(target_ids), user_id=user_id
    )

    affected_task_ids: Set[UUID] = set()
    needs_task_note_recompute = (
        source_model == ModelName.Note
        and target_model == ModelName.Task
        and link_type == LinkType.RELATES_TO
    )

    if needs_task_note_recompute:
        existing_targets_query = (
            Association.active(db)
            .with_entities(Association.target_id)
            .filter(
                Association.source_model == source_model.value,
                Association.source_id == source_id,
                Association.target_model == target_model.value,
                Association.link_type == link_type.value,
            )
        )
        if user_id is not None:
            existing_targets_query = existing_targets_query.filter(
                Association.user_id == user_id
            )
        affected_task_ids.update(
            target_id for (target_id,) in existing_targets_query.all()
        )

    if replace:
        query = Association.active(db).filter(
            Association.source_model == source_model.value,
            Association.source_id == source_id,
            Association.target_model == target_model.value,
        )
        if user_id is not None:
            query = query.filter(Association.user_id == user_id)
        query.delete(synchronize_session=False)

    # Insert new links (skip duplicates by checking existing in session query)
    if valid_target_ids:
        existing_query = Association.active(db).filter(
            Association.source_model == source_model.value,
            Association.source_id == source_id,
            Association.target_model == target_model.value,
            Association.target_id.in_(valid_target_ids),
            Association.link_type == link_type.value,
        )
        if user_id is not None:
            existing_query = existing_query.filter(Association.user_id == user_id)
        existing = existing_query.all()
        existing_pairs = {(a.source_id, a.target_id) for a in existing}
        for tid in valid_target_ids:
            if (source_id, tid) in existing_pairs:
                continue
            association = Association(
                source_model=source_model.value,
                source_id=source_id,
                target_model=target_model.value,
                target_id=tid,
                link_type=link_type.value,
            )
            if user_id is not None:
                association.user_id = user_id
            db.add(association)
            if needs_task_note_recompute:
                affected_task_ids.add(tid)

    if needs_task_note_recompute and affected_task_ids:
        # Ensure association inserts/deletes are flushed before counting so
        # recompute_task_notes_count sees the latest state even when autoflush
        # is disabled (tests configure autoflush=False).
        db.flush()
        recompute_task_notes_count(db, affected_task_ids, user_id=user_id)


def get_target_ids_for_sources(
    db: Session,
    *,
    source_model: ModelName,
    source_ids: Sequence[UUID],
    target_model: ModelName,
    link_type: Optional[LinkType] = None,
    user_id: Optional[UUID] = None,
) -> Dict[UUID, List[UUID]]:
    """Return mapping source_id -> list[target_id] for given sources."""
    if not source_ids:
        return {}
    query = (
        Association.active(db)
        .filter(Association.user_id == user_id)
        .filter(
            Association.source_model == source_model.value,
            Association.source_id.in_(source_ids),
            Association.target_model == target_model.value,
        )
    )
    if link_type is not None:
        query = query.filter(Association.link_type == link_type.value)
    rows = query.all()
    result: Dict[UUID, List[UUID]] = {}
    for a in rows:
        result.setdefault(a.source_id, []).append(a.target_id)
    return result


def get_source_ids_for_target(
    db: Session,
    *,
    source_model: ModelName,
    target_model: ModelName,
    target_id: UUID,
    link_type: Optional[LinkType] = None,
    user_id: Optional[UUID] = None,
) -> List[str]:
    """Return list of source IDs that link to the given target."""
    query = (
        Association.active(db)
        .filter(Association.user_id == user_id)
        .filter(
            Association.source_model == source_model.value,
            Association.target_model == target_model.value,
            Association.target_id == target_id,
        )
    )
    if link_type is not None:
        query = query.filter(Association.link_type == link_type.value)
    return [a.source_id for a in query.all()]


def load_persons_for_sources(
    db: Session,
    *,
    source_model: ModelName,
    source_ids: Sequence[UUID],
    link_type: Optional[LinkType] = None,
    user_id: Optional[UUID] = None,
) -> Dict[UUID, List[Person]]:
    """Convenience: get mapping source_id -> list[Person] with tags preloaded."""
    mapping = get_target_ids_for_sources(
        db,
        source_model=source_model,
        source_ids=source_ids,
        target_model=ModelName.Person,
        link_type=link_type,
        user_id=user_id,
    )
    all_person_ids: Set[UUID] = set(pid for pids in mapping.values() for pid in pids)
    persons = (
        Person.active(db)
        .filter(Person.user_id == user_id)
        .options(joinedload(Person.tags))
        .filter(Person.id.in_(all_person_ids) if all_person_ids else False)
        .all()
    )
    persons_by_id = {p.id: p for p in persons}
    return {
        sid: [persons_by_id[pid] for pid in pids if pid in persons_by_id]
        for sid, pids in mapping.items()
    }


def attach_persons_for_sources(
    db: Session,
    *,
    source_model: ModelName,
    items: Sequence[object],
    link_type: Optional[LinkType] = None,
    attr_name: str = "persons",
    user_id: Optional[UUID] = None,
) -> None:
    """Attach persons to ORM items in-place using weak Association links.

    Args:
        db: SQLAlchemy session
        source_model: ModelName of the items
        items: Sequence of ORM items that contain an integer `id` attribute
        link_type: Optional link type to filter associations
        attr_name: Attribute name on item to assign persons list

    This function mutates `items` by setting `setattr(item, attr_name, persons)`.
    """
    if not items:
        return
    item_ids: List[UUID] = []
    for item in items:
        item_id = getattr(item, "id", None)
        if isinstance(item_id, UUID):
            item_ids.append(item_id)
    if not item_ids:
        return
    persons_map = load_persons_for_sources(
        db,
        source_model=source_model,
        source_ids=item_ids,
        link_type=link_type,
        user_id=user_id,
    )
    for item in items:
        item_id = getattr(item, "id", None)
        if isinstance(item_id, UUID):
            setattr(item, attr_name, persons_map.get(item_id, []))
