"""
Unit tests for task-related Pydantic schemas.

These tests ensure serialization/deserialization flows used by the task routes
remain stable and regressions (like missing forward-reference rebuilds) are
caught early.
"""

from datetime import datetime
from uuid import uuid4

import pytest

from app.schemas.task import TaskMoveResponse

pytestmark = pytest.mark.unit


def test_task_move_response_validates_nested_descendants_with_person_summaries():
    """TaskMoveResponse should accept dict payloads mirroring router usage."""
    now = datetime(2025, 10, 25, 20, 0, 0)
    parent_task_id = uuid4()
    child_task_id = uuid4()
    vision_id = uuid4()

    person_payload = {
        "id": uuid4(),
        "name": "Alice",
        "display_name": "Alice Example",
        "primary_nickname": "Ali",
        "birth_date": None,
        "location": "NYC",
        "tags": [
            {
                "id": uuid4(),
                "name": "friend",
                "entity_type": "person",
                "category": "general",
                "description": None,
                "color": "#123ABC",
                "created_at": now,
                "updated_at": now,
            }
        ],
    }

    parent_task_payload = {
        "id": parent_task_id,
        "vision_id": vision_id,
        "parent_task_id": None,
        "status": "todo",
        "display_order": 0,
        "actual_effort": None,
        "actual_effort_self": 0,
        "actual_effort_total": 0,
        "notes_count": 0,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
        "content": "Parent task",
        "priority": 1,
        "estimated_effort": 60,
        "planning_cycle_type": None,
        "planning_cycle_days": None,
        "planning_cycle_start_date": None,
        "vision_summary": None,
        "parent_summary": None,
        "persons": [person_payload],
    }

    child_task_payload = {
        "id": child_task_id,
        "vision_id": vision_id,
        "parent_task_id": parent_task_id,
        "status": "todo",
        "display_order": 1,
        "actual_effort": None,
        "actual_effort_self": 0,
        "actual_effort_total": 0,
        "notes_count": 0,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
        "content": "Child task",
        "priority": 1,
        "estimated_effort": 30,
        "planning_cycle_type": None,
        "planning_cycle_days": None,
        "planning_cycle_start_date": None,
        "vision_summary": None,
        "parent_summary": None,
        "persons": [],
    }

    payload = {
        **parent_task_payload,
        "updated_descendants": [child_task_payload],
    }

    result = TaskMoveResponse.model_validate(payload)

    assert result.id == parent_task_id
    assert result.updated_descendants[0].id == child_task_id
    assert result.persons[0].display_name == "Alice Example"
