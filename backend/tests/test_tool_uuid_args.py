from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.agents.tools.arg_utils import normalize_uuid_list
from app.agents.tools.person_tools import CreatePersonArgs, UpdatePersonArgs
from app.agents.tools.task_tools import CreateTaskArgs, UpdateTaskArgs
from app.agents.tools.timelog_tools import CreateTimeLogArgs, UpdateTimeLogArgs
from app.agents.tools.vision_tools import CreateVisionArgs, UpdateVisionArgs


def test_create_task_args_coerces_person_ids_from_json():
    person_id = str(uuid4())
    args = CreateTaskArgs(
        content="test",
        vision_id=uuid4(),
        person_ids=f'["{person_id}"]',
    )
    assert [str(value) for value in args.person_ids] == [person_id]


def test_update_task_args_coerces_person_ids_from_csv():
    first = str(uuid4())
    second = str(uuid4())
    args = UpdateTaskArgs(task_id=uuid4(), person_ids=f"{first},{second}")
    assert [str(value) for value in args.person_ids] == [first, second]


def test_create_task_args_invalid_person_ids_raises():
    with pytest.raises(ValueError):
        CreateTaskArgs(content="x", vision_id=uuid4(), person_ids=123)


def test_create_person_args_coerces_tag_ids():
    tag = str(uuid4())
    args = CreatePersonArgs(tag_ids=f'["{tag}"]')
    assert [str(value) for value in args.tag_ids] == [tag]


def test_update_person_args_coerces_tag_ids():
    first = str(uuid4())
    args = UpdatePersonArgs(person_id=uuid4(), tag_ids=first)
    assert [str(value) for value in args.tag_ids] == [first]


def test_create_vision_args_coerces_person_ids():
    pid = str(uuid4())
    args = CreateVisionArgs(name="Vision", person_ids=f'["{pid}"]')
    assert [str(value) for value in args.person_ids] == [pid]


def test_update_vision_args_coerces_person_ids():
    pid = str(uuid4())
    args = UpdateVisionArgs(vision_id=uuid4(), person_ids=pid)
    assert [str(value) for value in args.person_ids] == [pid]


def test_create_timelog_args_coerces_person_ids():
    pid = str(uuid4())
    args = CreateTimeLogArgs(
        title="log",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        person_ids=pid,
    )
    assert [str(value) for value in args.person_ids] == [pid]


def test_update_timelog_args_coerces_person_ids():
    pid = str(uuid4())
    args = UpdateTimeLogArgs(event_id=uuid4(), person_ids=pid)
    assert [str(value) for value in args.person_ids] == [pid]


def test_normalize_uuid_list_handles_uuid_objects():
    pid = uuid4()
    assert normalize_uuid_list([pid]) == [str(pid)]


def test_normalize_uuid_list_returns_none_for_empty():
    assert normalize_uuid_list([]) is None
    assert normalize_uuid_list(None) is None
