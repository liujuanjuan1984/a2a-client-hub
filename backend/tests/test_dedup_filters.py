"""Integration tests for newly added exact-match filters used in dedup logic."""

from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.db.models.user import User
from app.handlers import habits as habit_handler
from app.handlers import notes as note_handler
from app.handlers import persons as person_handler
from app.handlers import tags as tag_handler
from app.handlers import tasks as task_handler
from app.handlers import visions as vision_handler
from app.schemas.habit import HabitCreate
from app.schemas.note import NoteCreate
from app.schemas.person import PersonCreate
from app.schemas.tag import TagCreate
from app.schemas.task import TaskCreate
from app.schemas.vision import VisionCreate

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


@pytest.fixture(autouse=True)
def _disable_work_recalc(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.handlers.tasks._schedule_recalc_jobs", _noop)


async def _create_vision(async_db_session, **kwargs):
    return await vision_handler.create_vision(async_db_session, **kwargs)


async def _list_visions(async_db_session, **kwargs):
    return await vision_handler.list_visions(async_db_session, **kwargs)


async def _make_user(async_db_session):
    user = User(
        id=uuid4(),
        email="dedup@example.com",
        name="Dedup User",
        password_hash="hashed",
    )
    async_db_session.add(user)
    await async_db_session.flush()
    await async_db_session.commit()
    return user


async def test_tag_list_name_and_entity_type_filter(async_db_session):
    user = await _make_user(async_db_session)
    await tag_handler.create_tag(
        async_db_session,
        user_id=user.id,
        tag_in=TagCreate(name="前同事", entity_type="person"),
    )
    await tag_handler.create_tag(
        async_db_session,
        user_id=user.id,
        tag_in=TagCreate(name="前同事", entity_type="task"),
    )

    tags = await tag_handler.list_tags(
        async_db_session, user_id=user.id, name="前同事", entity_type="person"
    )

    assert len(tags) == 1
    assert tags[0].entity_type == "person"


async def test_person_list_nickname_exact(async_db_session):
    user = await _make_user(async_db_session)
    await person_handler.create_person(
        async_db_session,
        user_id=user.id,
        person_in=PersonCreate(name="黄其棋", nicknames=["女儿"]),
    )

    persons, _ = await person_handler.list_persons(
        async_db_session, user_id=user.id, nickname_exact="女儿"
    )

    assert len(persons) == 1
    assert persons[0].name == "黄其棋"


async def test_vision_list_name_filter(async_db_session):
    user = await _make_user(async_db_session)
    await _create_vision(
        async_db_session,
        user_id=user.id,
        vision_in=VisionCreate(name="减脂", description=None),
    )
    await _create_vision(
        async_db_session,
        user_id=user.id,
        vision_in=VisionCreate(name="增肌", description=None),
    )

    visions = await _list_visions(
        async_db_session, user_id=user.id, name="减脂", skip=0, limit=10
    )

    assert len(visions) == 1
    assert visions[0].name == "减脂"


async def test_task_list_content_filter(async_db_session):
    user = await _make_user(async_db_session)
    vision = await _create_vision(
        async_db_session,
        user_id=user.id,
        vision_in=VisionCreate(name="事业", description=None),
    )
    await task_handler.create_task(
        async_db_session,
        user_id=user.id,
        task_data=TaskCreate(content="写周报", vision_id=vision.id, display_order=0),
    )
    await task_handler.create_task(
        async_db_session,
        user_id=user.id,
        task_data=TaskCreate(content="备稿", vision_id=vision.id, display_order=1),
    )

    tasks = await task_handler.list_tasks(
        async_db_session,
        user_id=user.id,
        vision_id=vision.id,
        content="写周报",
        skip=0,
        limit=10,
    )

    assert len(tasks) == 1
    assert tasks[0].content == "写周报"


async def test_habit_title_and_active_window_filter(async_db_session):
    user = await _make_user(async_db_session)
    today = date.today()

    active_habit = await habit_handler.create_habit(
        async_db_session,
        user_id=user.id,
        habit_in=HabitCreate(
            title="每天练习",
            description=None,
            start_date=today - timedelta(days=1),
            duration_days=7,
        ),
    )
    await habit_handler.create_habit(
        async_db_session,
        user_id=user.id,
        habit_in=HabitCreate(
            title="每天练习",
            description=None,
            start_date=today - timedelta(days=10),
            duration_days=7,
        ),
    )

    habits, _ = await habit_handler.list_habits(
        async_db_session,
        user_id=user.id,
        title="每天练习",
        active_window_only=True,
    )

    assert len(habits) == 1
    assert habits[0].id == active_habit.id


async def test_note_list_content_exact(async_db_session):
    user = await _make_user(async_db_session)
    await note_handler.create_note(
        async_db_session,
        user_id=user.id,
        note_in=NoteCreate(
            content="同样的内容", person_ids=None, tag_ids=None, task_id=None
        ),
    )
    await note_handler.create_note(
        async_db_session,
        user_id=user.id,
        note_in=NoteCreate(content="不同内容", person_ids=None, tag_ids=None, task_id=None),
    )

    notes = await note_handler.list_notes(
        async_db_session,
        user_id=user.id,
        content_exact="同样的内容",
        limit=10,
    )

    assert len(notes) == 1
    assert notes[0].content == "同样的内容"
