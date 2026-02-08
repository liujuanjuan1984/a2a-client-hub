"""Shared entity serialization helpers for agents, handlers and CardBox."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional, Sequence
from uuid import UUID

from pydantic import BaseModel

from app.core.constants import USER_PREFERENCE_DEFAULTS
from app.schemas.habit import HabitResponse
from app.schemas.note import (
    NoteResponse,
    NoteTimelogDimensionSummary,
    NoteTimelogSummary,
    NoteTimelogTaskSummary,
)
from app.schemas.person import PersonActivityItem, PersonSummaryResponse
from app.schemas.tag import TagResponse
from app.schemas.task import TaskParentSummary, TaskSummaryResponse
from app.schemas.vision import VisionResponse, VisionSummaryResponse
from app.utils.timezone_util import utc_now


def _to_iso(value: Any) -> Optional[str]:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _to_serializable_uuid(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def serialize_tag(tag: Any) -> Dict[str, Any]:
    if tag is None:
        return {}

    if isinstance(tag, dict):
        raw = dict(tag)
    elif hasattr(tag, "model_dump"):
        raw = tag.model_dump(mode="json")
    else:
        raw = {
            "id": getattr(tag, "id", None),
            "name": getattr(tag, "name", None),
            "entity_type": getattr(tag, "entity_type", None),
            "category": getattr(tag, "category", "general"),
            "description": getattr(tag, "description", None),
            "color": getattr(tag, "color", None),
            "created_at": getattr(tag, "created_at", None),
            "updated_at": getattr(tag, "updated_at", None),
        }

    raw["id"] = _to_serializable_uuid(raw.get("id"))
    if raw.get("category") is None:
        raw["category"] = "general"
    raw["created_at"] = _to_iso(raw.get("created_at"))
    raw["updated_at"] = _to_iso(raw.get("updated_at"))
    return raw


def serialize_person(person: Any, *, include_tags: bool = True) -> Dict[str, Any]:
    if person is None:
        return {}

    if isinstance(person, dict):
        raw = dict(person)
    elif isinstance(person, BaseModel):
        raw = person.model_dump(mode="json")
    else:
        raw = {
            "id": getattr(person, "id", None),
            "name": getattr(person, "name", None),
            "display_name": getattr(person, "display_name", None),
            "primary_nickname": getattr(person, "primary_nickname", None),
            "role": getattr(person, "role", None),
            "location": getattr(person, "location", None),
            "birth_date": getattr(person, "birth_date", None),
            "tags": getattr(person, "tags", []),
        }

    raw["id"] = _to_serializable_uuid(raw.get("id"))
    raw["birth_date"] = _to_iso(raw.get("birth_date"))

    tags = raw.get("tags") or []
    raw["tags"] = [serialize_tag(tag) for tag in tags] if include_tags else []
    return raw


def serialize_person_summary(
    summary: Any, *, include_tags: bool = True
) -> Dict[str, Any]:
    if summary is None:
        return {}

    if isinstance(summary, PersonSummaryResponse):
        data = summary.model_dump(mode="json")
    elif isinstance(summary, dict):
        data = dict(summary)
    else:
        summary_id = getattr(summary, "id", None)
        data = {
            "id": summary_id,
            "name": getattr(summary, "name", None),
            "display_name": getattr(summary, "display_name", None),
            "primary_nickname": getattr(summary, "primary_nickname", None),
            "birth_date": getattr(summary, "birth_date", None),
            "location": getattr(summary, "location", None),
            "tags": getattr(summary, "tags", []),
        }

    data["id"] = _to_serializable_uuid(data.get("id"))
    data["birth_date"] = _to_iso(data.get("birth_date"))
    if include_tags:
        data["tags"] = [serialize_tag(tag) for tag in data.get("tags", [])]
    else:
        data["tags"] = []
    return data


def _build_person_summary(person: Any) -> Optional[PersonSummaryResponse]:
    if person is None:
        return None

    if isinstance(person, PersonSummaryResponse):
        return person

    if getattr(person, "deleted_at", None) is not None:
        return None

    raw_tags = getattr(person, "tags", []) or []
    tags: list[TagResponse] = []
    for tag in raw_tags:
        if isinstance(tag, TagResponse):
            tags.append(tag)
            continue

        if getattr(tag, "deleted_at", None) is not None:
            continue

        tags.append(
            TagResponse(
                id=getattr(tag, "id", None),
                name=getattr(tag, "name", None),
                entity_type=getattr(tag, "entity_type", None),
                category=getattr(tag, "category", "general"),
                description=getattr(tag, "description", None),
                color=getattr(tag, "color", None),
                created_at=getattr(tag, "created_at", None),
                updated_at=getattr(tag, "updated_at", None),
            )
        )

    primary_nickname: Optional[str]
    if hasattr(person, "get_primary_nickname"):
        primary_nickname = person.get_primary_nickname()
    else:
        primary_nickname = getattr(person, "primary_nickname", None)

    display_name = (
        getattr(person, "display_name", None)
        or getattr(person, "name", None)
        or f"Person #{getattr(person, 'id', 'unknown')}"
    )

    return PersonSummaryResponse(
        id=getattr(person, "id", None),
        name=getattr(person, "name", None),
        display_name=display_name,
        primary_nickname=primary_nickname or display_name,
        birth_date=getattr(person, "birth_date", None),
        location=getattr(person, "location", None),
        tags=tags,
    )


def serialize_person_activity(activity: Any) -> Dict[str, Any]:
    if activity is None:
        return {}

    if isinstance(activity, PersonActivityItem):
        data = activity.model_dump(mode="json")
    elif isinstance(activity, dict):
        data = dict(activity)
    else:
        data = {
            "id": getattr(activity, "id", None),
            "type": getattr(activity, "type", None),
            "title": getattr(activity, "title", None),
            "description": getattr(activity, "description", None),
            "date": getattr(activity, "date", None),
            "status": getattr(activity, "status", None),
        }

    data["id"] = _to_serializable_uuid(data.get("id"))
    data["date"] = _to_iso(data.get("date"))
    return data


def serialize_task(
    task: Any,
    *,
    include_persons: bool = True,
    include_subtasks: bool = True,
) -> Optional[Dict[str, Any]]:
    if task is None:
        return None

    if isinstance(task, dict):
        raw = dict(task)
    elif hasattr(task, "model_dump"):
        raw = task.model_dump(mode="json")
    else:
        raw = {
            "id": getattr(task, "id", None),
            "vision_id": getattr(task, "vision_id", None),
            "parent_task_id": getattr(task, "parent_task_id", None),
            "title": getattr(task, "title", None) or getattr(task, "content", None),
            "content": getattr(task, "content", None),
            "notes_count": getattr(task, "notes_count", None),
            "status": getattr(task, "status", None),
            "priority": getattr(task, "priority", None),
            "display_order": getattr(task, "display_order", None),
            "estimated_effort": getattr(task, "estimated_effort", None),
            "actual_effort": getattr(task, "actual_effort", None),
            "actual_effort_self": getattr(task, "actual_effort_self", None),
            "actual_effort_total": getattr(task, "actual_effort_total", None),
            "planning_cycle_type": getattr(task, "planning_cycle_type", None),
            "planning_cycle_days": getattr(task, "planning_cycle_days", None),
            "planning_cycle_start_date": getattr(
                task, "planning_cycle_start_date", None
            ),
            "completion_percentage": getattr(task, "completion_percentage", None),
            "depth": getattr(task, "depth", None),
            "created_at": getattr(task, "created_at", None),
            "updated_at": getattr(task, "updated_at", None),
            "deleted_at": getattr(task, "deleted_at", None),
            # Only touch relationship collections when explicitly requested to
            "persons": getattr(task, "persons", None) if include_persons else None,
            "subtasks": getattr(task, "subtasks", None) if include_subtasks else None,
        }

    raw["id"] = _to_serializable_uuid(raw.get("id"))
    raw["vision_id"] = _to_serializable_uuid(raw.get("vision_id"))
    raw["parent_task_id"] = _to_serializable_uuid(raw.get("parent_task_id"))
    raw["planning_cycle_start_date"] = _to_iso(raw.get("planning_cycle_start_date"))
    raw["created_at"] = _to_iso(raw.get("created_at"))
    raw["updated_at"] = _to_iso(raw.get("updated_at"))
    raw["deleted_at"] = _to_iso(raw.get("deleted_at"))
    raw["notes_count"] = raw.get("notes_count") or 0

    # Backward compatibility: drop legacy notes field if present
    if "notes" in raw:
        raw.pop("notes", None)

    if include_persons:
        persons = raw.get("persons") or []
        raw["persons"] = [serialize_person_summary(p) for p in persons]
    else:
        raw["persons"] = []

    if include_subtasks:
        subtasks = raw.get("subtasks") or []
        raw["subtasks"] = [
            subtask
            for subtask in (
                serialize_task(
                    item, include_persons=include_persons, include_subtasks=True
                )
                for item in subtasks
            )
            if subtask is not None
        ]
    else:
        raw["subtasks"] = []

    raw["is_leaf"] = not bool(raw["subtasks"])
    return raw


def build_task_summary(
    task: Any,
    *,
    include_vision_summary: bool = True,
    include_parent_summary: bool = True,
) -> Optional[TaskSummaryResponse]:
    """Assemble a TaskSummaryResponse with consistent vision/parent metadata."""

    if task is None:
        return None

    if isinstance(task, TaskSummaryResponse):
        return task

    if isinstance(task, dict):
        try:
            return TaskSummaryResponse.model_validate(task)
        except Exception:
            return None

    if getattr(task, "deleted_at", None) is not None or getattr(
        task, "is_deleted", False
    ):
        return None

    vision_summary: Optional[VisionSummaryResponse] = None
    if include_vision_summary:
        vision = getattr(task, "vision", None)
        if vision is not None and not getattr(vision, "is_deleted", False):
            vision_summary = VisionSummaryResponse(
                id=getattr(vision, "id", None),
                name=getattr(vision, "name", None),
                status=getattr(vision, "status", None),
                dimension_id=getattr(vision, "dimension_id", None),
            )

    parent_summary: Optional[TaskParentSummary] = None
    if include_parent_summary:
        parent_task = getattr(task, "parent_task", None)
        if parent_task is not None and not getattr(parent_task, "is_deleted", False):
            parent_summary = TaskParentSummary(
                id=getattr(parent_task, "id", None),
                content=getattr(parent_task, "content", None),
                status=getattr(parent_task, "status", None),
            )

    payload = {
        "id": getattr(task, "id", None),
        "content": getattr(task, "content", None),
        "status": getattr(task, "status", None),
        "vision_id": getattr(task, "vision_id", None),
        "parent_task_id": getattr(task, "parent_task_id", None),
        "priority": getattr(task, "priority", 0) or 0,
        "estimated_effort": getattr(task, "estimated_effort", None),
        "notes_count": getattr(task, "notes_count", 0) or 0,
        "actual_effort_total": getattr(task, "actual_effort_total", 0) or 0,
        "created_at": getattr(task, "created_at", None),
        "updated_at": getattr(task, "updated_at", None),
        "vision_summary": vision_summary,
        "parent_summary": parent_summary,
    }

    try:
        return TaskSummaryResponse.model_validate(payload)
    except Exception:
        # Fallback for lightweight stubs used in exports/tests without full timestamps
        fallback_payload = dict(payload)
        if fallback_payload.get("content") is None:
            fallback_payload["content"] = ""
        if fallback_payload.get("status") is None:
            fallback_payload["status"] = "todo"
        if fallback_payload.get("created_at") is None:
            fallback_payload["created_at"] = utc_now()
        if fallback_payload.get("updated_at") is None:
            fallback_payload["updated_at"] = fallback_payload["created_at"]
        return TaskSummaryResponse.model_construct(**fallback_payload)


def build_note_response(
    note: Any,
    *,
    persons: Optional[Sequence[Any]] = None,
    task: Optional[Any] = None,
    timelogs: Optional[Sequence[Any]] = None,
    include_timelogs: bool = True,
) -> NoteResponse:
    """Assemble a NoteResponse with consistent filtering and nested summaries."""

    resolved_persons = (
        list(persons) if persons is not None else list(getattr(note, "persons", []))
    )
    person_summaries: list[PersonSummaryResponse] = []
    for person in resolved_persons:
        if getattr(person, "deleted_at", None) is not None:
            continue

        person_tags = [
            TagResponse(
                id=tag.id,
                name=tag.name,
                entity_type=tag.entity_type,
                category=getattr(tag, "category", "general"),
                description=tag.description,
                color=tag.color,
                created_at=tag.created_at,
                updated_at=tag.updated_at,
            )
            for tag in getattr(person, "tags", [])
            if getattr(tag, "deleted_at", None) is None
        ]

        primary_nickname = (
            person.get_primary_nickname()
            if hasattr(person, "get_primary_nickname")
            else getattr(person, "primary_nickname", None)
        )

        person_summaries.append(
            PersonSummaryResponse(
                id=person.id,
                name=getattr(person, "name", None),
                display_name=getattr(person, "display_name", None)
                or getattr(person, "name", None)
                or f"Person #{getattr(person, 'id', 'unknown')}",
                primary_nickname=primary_nickname
                or getattr(person, "display_name", None)
                or getattr(person, "name", None)
                or f"Person #{getattr(person, 'id', 'unknown')}",
                birth_date=getattr(person, "birth_date", None),
                location=getattr(person, "location", None),
                tags=person_tags,
            )
        )

    note_tags = [
        TagResponse(
            id=tag.id,
            name=tag.name,
            entity_type=tag.entity_type,
            category=getattr(tag, "category", "general"),
            description=tag.description,
            color=tag.color,
            created_at=tag.created_at,
            updated_at=tag.updated_at,
        )
        for tag in getattr(note, "tags", []) or []
        if getattr(tag, "deleted_at", None) is None
    ]

    resolved_task = task if task is not None else getattr(note, "task", None)
    task_summary = build_task_summary(resolved_task)

    resolved_timelogs = (
        list(timelogs) if timelogs is not None else list(getattr(note, "timelogs", []))
    )
    timelog_summaries: list[NoteTimelogSummary] = []
    if include_timelogs and resolved_timelogs:
        for timelog in resolved_timelogs:
            dimension_summary: Optional[NoteTimelogDimensionSummary] = None
            dimension = getattr(timelog, "dimension", None)
            if dimension is not None:
                dimension_summary = NoteTimelogDimensionSummary(
                    id=dimension.id,
                    name=getattr(dimension, "name", None),
                    color=getattr(dimension, "color", None),
                )

            timelog_task_summary: Optional[NoteTimelogTaskSummary] = None
            tl_task = getattr(timelog, "task", None)
            tl_summary = build_task_summary(tl_task, include_parent_summary=False)
            if tl_summary is not None:
                timelog_task_summary = NoteTimelogTaskSummary(
                    id=tl_summary.id,
                    content=tl_summary.content,
                    status=tl_summary.status,
                    vision_id=tl_summary.vision_id,
                    vision_summary=tl_summary.vision_summary,
                )

            timelog_summaries.append(
                NoteTimelogSummary(
                    id=timelog.id,
                    title=getattr(timelog, "title", None),
                    start_time=getattr(timelog, "start_time", None),
                    end_time=getattr(timelog, "end_time", None),
                    dimension_id=getattr(timelog, "dimension_id", None),
                    dimension_summary=dimension_summary,
                    task_summary=timelog_task_summary,
                    created_at=getattr(timelog, "created_at", None),
                    updated_at=getattr(timelog, "updated_at", None),
                )
            )

    return NoteResponse(
        id=note.id,
        content=note.content,
        created_at=note.created_at,
        updated_at=note.updated_at,
        persons=person_summaries,
        tags=note_tags,
        task=task_summary,
        timelogs=timelog_summaries if include_timelogs else [],
    )


def serialize_note(
    note: Any,
    *,
    persons: Optional[Sequence[Any]] = None,
    task: Optional[Any] = None,
    timelogs: Optional[Sequence[Any]] = None,
    include_timelogs: bool = False,
) -> Dict[str, Any]:
    if note is None:
        return {}

    response = build_note_response(
        note,
        persons=persons,
        task=task,
        timelogs=timelogs,
        include_timelogs=include_timelogs,
    )
    payload = response.model_dump(mode="json")
    if not include_timelogs:
        payload.pop("timelogs", None)
    return payload


def build_vision_response(
    vision: Any,
    *,
    persons: Optional[Sequence[Any]] = None,
    include_persons: bool = True,
) -> VisionResponse:
    """Assemble a VisionResponse with consistent person summaries."""

    resolved_persons = (
        list(persons) if persons is not None else list(getattr(vision, "persons", []))
    )

    person_summaries: list[PersonSummaryResponse] = []
    if include_persons and resolved_persons:
        for person in resolved_persons:
            summary = _build_person_summary(person)
            if summary is not None:
                person_summaries.append(summary)

    return VisionResponse(
        id=getattr(vision, "id", None),
        name=getattr(vision, "name", None),
        description=getattr(vision, "description", None),
        dimension_id=getattr(vision, "dimension_id", None),
        status=getattr(vision, "status", None),
        stage=getattr(vision, "stage", None) or 0,
        experience_points=getattr(vision, "experience_points", None) or 0,
        experience_rate_per_hour=getattr(vision, "experience_rate_per_hour", None),
        total_actual_effort=getattr(vision, "total_actual_effort", None),
        created_at=getattr(vision, "created_at", None),
        updated_at=getattr(vision, "updated_at", None),
        deleted_at=getattr(vision, "deleted_at", None),
        persons=person_summaries,
    )


def serialize_vision(vision: Any) -> Dict[str, Any]:
    if vision is None:
        return {}

    response = build_vision_response(vision)
    payload = response.model_dump(mode="json")
    payload["dimension"] = serialize_dimension(getattr(vision, "dimension", None))
    if "experience_rate_per_hour" not in payload:
        payload["experience_rate_per_hour"] = None
    return payload


def serialize_vision_summary(vision: Any) -> Optional[Dict[str, Any]]:
    if vision is None:
        return None

    payload = build_vision_response(vision, include_persons=False).model_dump(
        mode="json"
    )
    return {
        "id": payload.get("id"),
        "name": payload.get("name"),
        "status": payload.get("status"),
        "dimension_id": payload.get("dimension_id"),
    }


def serialize_actual_event(
    event: Any,
    *,
    persons: Sequence[Any],
    task_summary: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    start_time = getattr(event, "start_time", None)
    end_time = getattr(event, "end_time", None)
    duration_minutes: Optional[float] = None
    if start_time and end_time:
        delta = end_time - start_time
        duration_minutes = round(delta.total_seconds() / 60, 2)

    event_id = getattr(event, "id", None)
    dimension_summary = serialize_dimension_summary(getattr(event, "dimension", None))
    normalized_task = (
        normalize_task_summary(task_summary, event, as_json=True)
        if task_summary
        else None
    )

    payload = {
        "id": _to_serializable_uuid(event_id),
        "title": getattr(event, "title", None),
        "start_time": _to_iso(start_time),
        "end_time": _to_iso(end_time),
        "duration_minutes": duration_minutes,
        "dimension_id": _to_serializable_uuid(getattr(event, "dimension_id", None)),
        "tracking_method": getattr(event, "tracking_method", None),
        "location": getattr(event, "location", None),
        "energy_level": getattr(event, "energy_level", None),
        "notes": getattr(event, "notes", None),
        "tags": getattr(event, "tags", None) or [],
        "task": normalized_task,
        "persons": [serialize_person_summary(p) for p in persons],
        "created_at": _to_iso(getattr(event, "created_at", None)),
        "updated_at": _to_iso(getattr(event, "updated_at", None)),
        "dimension_summary": dimension_summary,
    }
    return payload


def normalize_task_summary(
    task_summary: Any, event: Optional[Any] = None, *, as_json: bool = True
) -> Optional[Dict[str, Any]]:
    summary = build_task_summary(task_summary, include_parent_summary=False)
    if summary is None and event is not None:
        summary = build_task_summary(
            getattr(event, "task", None), include_parent_summary=False
        )

    if summary is None:
        return None

    payload_python = summary.model_dump(mode="python")
    if as_json:
        payload_json = summary.model_dump(mode="json")
        return {
            "id": payload_json.get("id"),
            "content": payload_json.get("content"),
            "vision_id": payload_json.get("vision_id"),
            "status": payload_json.get("status"),
            "vision_summary": payload_json.get("vision_summary"),
        }

    return {
        "id": payload_python.get("id"),
        "content": payload_python.get("content"),
        "vision_id": payload_python.get("vision_id"),
        "status": payload_python.get("status"),
        "vision_summary": payload_python.get("vision_summary"),
    }


def serialize_dimension(dimension: Any) -> Optional[Dict[str, Any]]:
    if not dimension:
        return None

    if isinstance(dimension, dict):
        data = dict(dimension)
    else:
        dim_id = getattr(dimension, "id", None)
        data = {
            "id": _to_serializable_uuid(dim_id),
            "name": getattr(dimension, "name", None),
            "color": getattr(dimension, "color", None),
            "icon": getattr(dimension, "icon", None),
            "description": getattr(dimension, "description", None),
            "created_at": getattr(dimension, "created_at", None),
            "updated_at": getattr(dimension, "updated_at", None),
        }

    data["created_at"] = _to_iso(data.get("created_at"))
    data["updated_at"] = _to_iso(data.get("updated_at"))
    return data


def serialize_dimension_summary(
    dimension: Any,
) -> Optional[Dict[str, Any]]:
    serialized = serialize_dimension(dimension)
    if not serialized:
        return None

    return {
        "id": serialized.get("id"),
        "name": serialized.get("name"),
        "color": serialized.get("color"),
    }


def serialize_food(food: Any) -> Dict[str, Any]:
    if food is None:
        return {}

    if hasattr(food, "model_dump"):
        data = food.model_dump(mode="json")
    elif isinstance(food, dict):
        data = dict(food)
    else:
        food_id = getattr(food, "id", None)
        data = {
            "id": _to_serializable_uuid(food_id),
            "name": getattr(food, "name", None),
            "description": getattr(food, "description", None),
            "is_common": getattr(food, "is_common", False),
            "user_id": _to_serializable_uuid(getattr(food, "user_id", None)),
            "calories_per_100g": getattr(food, "calories_per_100g", None),
            "protein_per_100g": getattr(food, "protein_per_100g", None),
            "carbs_per_100g": getattr(food, "carbs_per_100g", None),
            "fat_per_100g": getattr(food, "fat_per_100g", None),
            "fiber_per_100g": getattr(food, "fiber_per_100g", None),
            "sugar_per_100g": getattr(food, "sugar_per_100g", None),
            "sodium_per_100g": getattr(food, "sodium_per_100g", None),
            "created_at": getattr(food, "created_at", None),
            "updated_at": getattr(food, "updated_at", None),
        }

    data["created_at"] = _to_iso(data.get("created_at"))
    data["updated_at"] = _to_iso(data.get("updated_at"))
    return data


def serialize_food_entry(entry: Any) -> Dict[str, Any]:
    if entry is None:
        return {}

    if isinstance(entry, dict):
        raw = dict(entry)
    else:
        meal = getattr(entry, "meal_type", None)
        meal_value = meal.value if hasattr(meal, "value") else meal
        entry_id = getattr(entry, "id", None)
        food_id = getattr(entry, "food_id", None)
        raw = {
            "id": _to_serializable_uuid(entry_id),
            "date": getattr(entry, "date", None),
            "consumed_at": getattr(entry, "consumed_at", None),
            "meal_type": meal_value,
            "food_id": _to_serializable_uuid(food_id),
            "portion_size_g": getattr(entry, "portion_size_g", None),
            "notes": getattr(entry, "notes", None),
            "calories": getattr(entry, "calories", None),
            "protein": getattr(entry, "protein", None),
            "carbs": getattr(entry, "carbs", None),
            "fat": getattr(entry, "fat", None),
            "fiber": getattr(entry, "fiber", None),
            "sugar": getattr(entry, "sugar", None),
            "sodium": getattr(entry, "sodium", None),
            "created_at": getattr(entry, "created_at", None),
            "updated_at": getattr(entry, "updated_at", None),
            "food": getattr(entry, "food", None),
        }

    raw["consumed_at"] = _to_iso(raw.get("consumed_at"))
    raw["created_at"] = _to_iso(raw.get("created_at"))
    raw["updated_at"] = _to_iso(raw.get("updated_at"))
    raw["food"] = serialize_food(raw.get("food"))
    return raw


def serialize_preference(pref: Any, *, include_meta: bool = False) -> Dict[str, Any]:
    if pref is None:
        return {}

    if isinstance(pref, dict):
        data = dict(pref)
    else:
        data = {
            "key": getattr(pref, "key", None),
            "value": getattr(pref, "value", None),
            "module": getattr(pref, "module", None),
            "created_at": getattr(pref, "created_at", None),
            "updated_at": getattr(pref, "updated_at", None),
            "meta": getattr(pref, "meta", None),
        }

    data["created_at"] = _to_iso(data.get("created_at"))
    data["updated_at"] = _to_iso(data.get("updated_at"))

    if include_meta or "meta" in data:
        meta: Dict[str, Any] = data.get("meta") or {}
        cfg: Dict[str, Any] = USER_PREFERENCE_DEFAULTS.get(data.get("key"), {})
        merged_meta = {
            "allowed_values": list(
                cfg.get("allowed_values") or meta.get("allowed_values", [])
            ),
            "default_value": cfg.get("value", meta.get("default_value")),
            "description": cfg.get("description", meta.get("description")),
            "module": cfg.get("module", meta.get("module")),
        }
        data["meta"] = merged_meta

    return data


def serialize_daily_nutrition(summary: Any) -> Dict[str, Any]:
    if summary is None:
        return {}
    if hasattr(summary, "model_dump"):
        data = summary.model_dump(mode="json")
    elif isinstance(summary, dict):
        data = dict(summary)
    else:
        data = {
            "date": getattr(summary, "date", None),
            "total_calories": getattr(summary, "total_calories", None),
            "total_protein": getattr(summary, "total_protein", None),
            "total_carbs": getattr(summary, "total_carbs", None),
            "total_fat": getattr(summary, "total_fat", None),
            "total_fiber": getattr(summary, "total_fiber", None),
            "total_sugar": getattr(summary, "total_sugar", None),
            "total_sodium": getattr(summary, "total_sodium", None),
            "entry_count": getattr(summary, "entry_count", None),
        }
    return data


def serialize_habit(habit: Any) -> Dict[str, Any]:
    if habit is None:
        return {}

    if isinstance(habit, HabitResponse):
        data = habit.model_dump(mode="json")
    elif isinstance(habit, dict):
        data = dict(habit)
    else:
        data = {
            "id": _to_serializable_uuid(getattr(habit, "id", None)),
            "title": getattr(habit, "title", None),
            "description": getattr(habit, "description", None),
            "status": getattr(habit, "status", None),
            "start_date": getattr(habit, "start_date", None),
            "end_date": getattr(habit, "end_date", None),
            "duration_days": getattr(habit, "duration_days", None),
            "task": getattr(habit, "task", None),
            "progress_percentage": getattr(habit, "progress_percentage", None),
            "is_completed": getattr(habit, "is_completed", None),
            "created_at": getattr(habit, "created_at", None),
            "updated_at": getattr(habit, "updated_at", None),
        }

    data["start_date"] = _to_iso(data.get("start_date"))
    data["end_date"] = _to_iso(data.get("end_date"))
    data["created_at"] = _to_iso(data.get("created_at"))
    data["updated_at"] = _to_iso(data.get("updated_at"))
    data["task"] = (
        serialize_task(data.get("task"), include_persons=False)
        if data.get("task")
        else None
    )
    return data


def serialize_habit_action(action: Any) -> Dict[str, Any]:
    if action is None:
        return {}

    if isinstance(action, dict):
        data = dict(action)
    else:
        action_id = getattr(action, "id", None)
        habit_id = getattr(action, "habit_id", None)
        data = {
            "id": _to_serializable_uuid(action_id),
            "habit_id": _to_serializable_uuid(habit_id),
            "action_date": getattr(action, "action_date", None),
            "status": getattr(action, "status", None),
            "status_display": getattr(action, "status_display", None),
            "notes": getattr(action, "notes", None),
            "can_modify": getattr(action, "can_modify", None),
            "is_today": getattr(action, "is_today", None),
            "is_past": getattr(action, "is_past", None),
            "is_future": getattr(action, "is_future", None),
            "created_at": getattr(action, "created_at", None),
            "updated_at": getattr(action, "updated_at", None),
        }

    data["action_date"] = _to_iso(data.get("action_date"))
    data["created_at"] = _to_iso(data.get("created_at"))
    data["updated_at"] = _to_iso(data.get("updated_at"))
    return data


__all__ = [
    "build_task_summary",
    "build_note_response",
    "build_vision_response",
    "serialize_actual_event",
    "serialize_daily_nutrition",
    "serialize_dimension",
    "serialize_dimension_summary",
    "serialize_food",
    "serialize_food_entry",
    "serialize_habit",
    "serialize_habit_action",
    "serialize_note",
    "serialize_person",
    "serialize_person_activity",
    "serialize_person_summary",
    "serialize_preference",
    "serialize_tag",
    "serialize_task",
    "serialize_vision",
    "serialize_vision_summary",
    "normalize_task_summary",
]
