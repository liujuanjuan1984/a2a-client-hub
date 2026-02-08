from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.agents.tools import responses  # noqa: F401 - ensure registry seeded
from app.serialization import SerializeParams, fallback_serialize, serialize
from app.serialization.entities import (
    build_task_summary,
    normalize_task_summary,
    serialize_note,
    serialize_person_summary,
    serialize_tag,
    serialize_task,
)


def _uuid(value: str) -> UUID:
    return UUID(value)


def test_serialize_person_summary_handles_tags_and_dates():
    tag = SimpleNamespace(
        id=_uuid("00000000-0000-0000-0000-000000000001"),
        name="friend",
        entity_type="person",
        description="",
        color="#ffffff",
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 30, 0),
    )
    summary = SimpleNamespace(
        id=_uuid("00000000-0000-0000-0000-000000000002"),
        name="Alice",
        display_name="Alice",
        primary_nickname="Al",
        birth_date=datetime(1990, 5, 20),
        location="NYC",
        tags=[tag],
    )

    result = serialize_person_summary(summary)

    assert result["id"] == "00000000-0000-0000-0000-000000000002"
    assert result["birth_date"] == "1990-05-20T00:00:00"
    assert result["tags"][0]["id"] == "00000000-0000-0000-0000-000000000001"
    assert result["tags"][0]["created_at"].startswith("2024-01-01")


def test_serialize_task_includes_persons_and_is_leaf():
    person = SimpleNamespace(
        id=_uuid("00000000-0000-0000-0000-000000000003"),
        name="Bob",
        display_name="Bob",
        primary_nickname="B",
        birth_date=datetime(1995, 7, 1),
        location="SF",
        tags=[],
    )
    task = SimpleNamespace(
        id=_uuid("00000000-0000-0000-0000-000000000004"),
        vision_id=_uuid("00000000-0000-0000-0000-000000000005"),
        parent_task_id=None,
        title="Task",
        content="Do something",
        notes="",
        status="open",
        priority=1,
        display_order=0,
        estimated_effort=30,
        actual_effort=None,
        actual_effort_self=None,
        actual_effort_total=None,
        planning_cycle_type=None,
        planning_cycle_days=None,
        planning_cycle_start_date=None,
        completion_percentage=None,
        depth=0,
        created_at=datetime(2025, 1, 1, 9, 0, 0),
        updated_at=datetime(2025, 1, 1, 9, 30, 0),
        deleted_at=None,
        persons=[person],
        subtasks=[],
    )

    result = serialize_task(task)

    assert result["id"] == "00000000-0000-0000-0000-000000000004"
    assert result["vision_id"] == "00000000-0000-0000-0000-000000000005"
    assert result["persons"][0]["id"] == "00000000-0000-0000-0000-000000000003"
    assert result["is_leaf"] is True
    assert result["subtasks"] == []


def test_build_task_summary_provides_vision_and_parent():
    vision = SimpleNamespace(
        id=_uuid("00000000-0000-0000-0000-000000000101"),
        name="Health Vision",
        status="active",
        dimension_id=_uuid("00000000-0000-0000-0000-000000000201"),
        is_deleted=False,
    )
    parent = SimpleNamespace(
        id=_uuid("00000000-0000-0000-0000-000000000102"),
        content="Weekly planning",
        status="in_progress",
        is_deleted=False,
    )
    task = SimpleNamespace(
        id=_uuid("00000000-0000-0000-0000-000000000103"),
        content="Morning workout",
        status="done",
        vision_id=vision.id,
        parent_task_id=parent.id,
        priority=2,
        estimated_effort=90,
        notes_count=3,
        actual_effort_total=45,
        created_at=datetime(2025, 1, 1, 7, 0, 0),
        updated_at=datetime(2025, 1, 1, 8, 0, 0),
        vision=vision,
        parent_task=parent,
        deleted_at=None,
        is_deleted=False,
    )

    summary = build_task_summary(task)

    assert summary is not None
    assert summary.id == task.id
    assert summary.vision_summary is not None
    assert summary.vision_summary.id == vision.id
    assert summary.parent_summary is not None
    assert summary.parent_summary.id == parent.id
    assert summary.priority == 2
    assert summary.actual_effort_total == 45


def test_build_task_summary_skips_deleted_task():
    task = SimpleNamespace(
        id=_uuid("00000000-0000-0000-0000-000000000104"),
        content="Archived task",
        status="cancelled",
        vision_id=_uuid("00000000-0000-0000-0000-000000000202"),
        parent_task_id=None,
        priority=1,
        estimated_effort=None,
        notes_count=0,
        actual_effort_total=0,
        created_at=datetime(2025, 1, 2, 9, 0, 0),
        updated_at=datetime(2025, 1, 2, 10, 0, 0),
        vision=None,
        parent_task=None,
        deleted_at=datetime(2025, 1, 3, 0, 0, 0),
        is_deleted=True,
    )

    summary = build_task_summary(task)

    assert summary is None


def test_normalize_task_summary_fallback_to_event_task():
    vision = SimpleNamespace(
        id=_uuid("00000000-0000-0000-0000-000000000301"),
        name="Skill Vision",
        status="active",
        dimension_id=_uuid("00000000-0000-0000-0000-000000000401"),
        is_deleted=False,
    )
    task = SimpleNamespace(
        id=_uuid("00000000-0000-0000-0000-000000000302"),
        content="Read technical book",
        status="in_progress",
        vision_id=vision.id,
        parent_task_id=None,
        priority=1,
        estimated_effort=None,
        notes_count=0,
        actual_effort_total=0,
        created_at=datetime(2025, 1, 5, 12, 0, 0),
        updated_at=datetime(2025, 1, 5, 13, 0, 0),
        vision=vision,
        parent_task=None,
        deleted_at=None,
        is_deleted=False,
    )
    event = SimpleNamespace(task=task)

    normalized = normalize_task_summary(None, event)

    assert normalized is not None
    assert normalized["id"] == "00000000-0000-0000-0000-000000000302"
    assert normalized["content"] == "Read technical book"
    assert normalized["vision_summary"] is not None
    assert normalized["vision_summary"]["id"] == "00000000-0000-0000-0000-000000000301"


def test_serialization_registry_uses_registered_schema():
    tag = SimpleNamespace(
        id=_uuid("00000000-0000-0000-0000-000000000006"),
        name="work",
        entity_type="person",
        description=None,
        color="#000000",
        created_at=datetime(2024, 6, 1, 8, 0, 0),
        updated_at=datetime(2024, 6, 1, 9, 0, 0),
    )

    result = serialize(tag, "tag")

    assert result["id"] == "00000000-0000-0000-0000-000000000006"
    assert result["name"] == "work"
    assert result["created_at"].startswith("2024-06-01")


def test_fallback_serialize_handles_unknown_object():
    class Custom:
        def __init__(self) -> None:
            self.id = _uuid("00000000-0000-0000-0000-000000000007")
            self.created_at = datetime(2024, 8, 1, 10, 0, 0)

    obj = Custom()
    result = fallback_serialize(obj, SerializeParams())

    assert result["id"] == "00000000-0000-0000-0000-000000000007"
    assert result["created_at"].startswith("2024-08-01")


def test_serialize_note_limits_fields():
    note = SimpleNamespace(
        id=_uuid("00000000-0000-0000-0000-000000000008"),
        content="hello",
        created_at=datetime(2024, 9, 1, 11, 0, 0),
        updated_at=datetime(2024, 9, 1, 12, 0, 0),
        deleted_at=None,
        tags=[],
        persons=[],
        task=None,
    )

    result = serialize_note(note)

    assert result["id"] == "00000000-0000-0000-0000-000000000008"
    assert result["created_at"].startswith("2024-09-01")
    assert result["persons"] == []
    assert result["task"] is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"name": "focus"}, "focus"),
        (SimpleNamespace(name="focus"), "focus"),
    ],
)
def test_serialize_tag_accepts_dict_or_object(raw, expected):
    result = serialize_tag(raw)
    assert result["name"] == expected
