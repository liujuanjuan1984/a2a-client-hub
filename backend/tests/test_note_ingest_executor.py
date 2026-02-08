from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from app.db.models.association import Association
from app.db.models.habit import Habit
from app.db.models.note import Note
from app.db.models.person import Person
from app.db.models.task import Task
from app.schemas.entity_ingest import (
    EntityExtraction,
    HabitDraft,
    NoteDraft,
    PersonDraft,
    TaskDraft,
)
from app.workflows.note_ingest_executor import note_ingest_executor
from backend.tests.utils import create_person, create_task, create_user, create_vision

pytestmark = pytest.mark.usefixtures("engine")


@pytest.fixture(autouse=True)
def _disable_work_recalc(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.handlers.tasks.schedule_recalc_jobs", _noop)


async def _create_note(async_db_session, user, *, content: str) -> Note:
    note = Note(user_id=user.id, content=content)
    async_db_session.add(note)
    await async_db_session.flush()
    return note


async def _get_association(async_db_session, *filters):
    stmt = select(Association).where(*filters)
    result = await async_db_session.execute(stmt)
    return result.scalar_one_or_none()


@pytest.mark.asyncio
async def test_note_ingest_uses_existing_person_refs(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    person = await create_person(async_db_session, user=user, name="唐沂刚")
    note = await _create_note(async_db_session, user, content="initial raw note")

    extraction = EntityExtraction(
        note=NoteDraft(
            content="今天唐沂刚找我聊需求",
            person_refs=[str(person.id)],
            tags=[],
        ),
    )

    summary = await note_ingest_executor.execute(
        async_db_session,
        user_id=user.id,
        note_id=note.id,
        extraction=extraction,
    )

    assert summary["note_updated"] is True

    link = await _get_association(
        async_db_session,
        Association.user_id == user.id,
        Association.source_model == "Note",
        Association.source_id == note.id,
        Association.target_model == "Person",
        Association.target_id == person.id,
        Association.link_type == "is_about",
        Association.deleted_at.is_(None),
    )
    assert link is not None


@pytest.mark.asyncio
async def test_note_ingest_links_existing_task(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    vision = await create_vision(async_db_session, user=user, name="Todos Inbox")
    task = await create_task(async_db_session, user, vision, content="跟进需求")
    note = await _create_note(async_db_session, user, content="和唐沂刚确认需求")

    extraction = EntityExtraction(
        note=NoteDraft(
            content="和唐沂刚确认需求",
            task_ref=str(task.id),
            tags=[],
        ),
    )

    await note_ingest_executor.execute(
        async_db_session,
        user_id=user.id,
        note_id=note.id,
        extraction=extraction,
    )

    link = await _get_association(
        async_db_session,
        Association.user_id == user.id,
        Association.source_model == "Note",
        Association.source_id == note.id,
        Association.target_model == "Task",
        Association.target_id == task.id,
        Association.link_type == "relates_to",
        Association.deleted_at.is_(None),
    )
    assert link is not None


@pytest.mark.asyncio
async def test_note_ingest_links_new_task_via_local_ref(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    note = await _create_note(async_db_session, user, content="记录 agent 需求")

    extraction = EntityExtraction(
        note=NoteDraft(content="记录 agent 需求", task_ref="task-1", tags=[]),
        tasks=[TaskDraft(ref="task-1", content="准备 agent 演示")],
    )

    summary = await note_ingest_executor.execute(
        async_db_session,
        user_id=user.id,
        note_id=note.id,
        extraction=extraction,
    )

    assert summary["tasks"]["created"] == 1

    link = await _get_association(
        async_db_session,
        Association.user_id == user.id,
        Association.source_model == "Note",
        Association.source_id == note.id,
        Association.target_model == "Task",
        Association.link_type == "relates_to",
        Association.deleted_at.is_(None),
    )
    assert link is not None

    stmt = select(Task).where(Task.id == link.target_id)
    task = (await async_db_session.execute(stmt)).scalar_one()
    assert task.content == "准备 agent 演示"


@pytest.mark.asyncio
async def test_note_ingest_links_task_when_note_has_no_task_ref(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    note = await _create_note(async_db_session, user, content="整理会议材料")

    extraction = EntityExtraction(
        note=NoteDraft(content="整理会议材料", tags=[], person_refs=[]),
        tasks=[TaskDraft(ref="auto-task", content="准备会议材料清单")],
    )

    summary = await note_ingest_executor.execute(
        async_db_session,
        user_id=user.id,
        note_id=note.id,
        extraction=extraction,
    )

    assert summary["tasks"]["created"] == 1

    link = await _get_association(
        async_db_session,
        Association.user_id == user.id,
        Association.source_model == "Note",
        Association.source_id == note.id,
        Association.target_model == "Task",
        Association.link_type == "relates_to",
        Association.deleted_at.is_(None),
    )
    assert link is not None


@pytest.mark.asyncio
async def test_note_ingest_links_person_when_note_has_no_person_ref(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    note = await _create_note(async_db_session, user, content="和 dango 微信开会")

    extraction = EntityExtraction(
        note=NoteDraft(content="和 dango 微信开会", tags=[], person_refs=[]),
        persons=[PersonDraft(ref="p1", name="dango")],
    )

    summary = await note_ingest_executor.execute(
        async_db_session,
        user_id=user.id,
        note_id=note.id,
        extraction=extraction,
    )

    assert summary["persons"]["created"] == 1

    link = await _get_association(
        async_db_session,
        Association.user_id == user.id,
        Association.source_model == "Note",
        Association.source_id == note.id,
        Association.target_model == "Person",
        Association.link_type == "is_about",
        Association.deleted_at.is_(None),
    )
    assert link is not None


@pytest.mark.asyncio
async def test_note_ingest_reuses_person_by_nickname(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    person = await create_person(async_db_session, user=user, name="王小明")

    entity = await async_db_session.get(Person, person.id)
    entity.nicknames = ["女儿"]
    await async_db_session.flush()

    note = await _create_note(async_db_session, user, content="和女儿通话")

    extraction = EntityExtraction(
        note=NoteDraft(content="和女儿通话", tags=[], person_refs=[]),
        persons=[PersonDraft(ref="p1", name=None, nicknames=["女儿"])],
    )

    summary = await note_ingest_executor.execute(
        async_db_session,
        user_id=user.id,
        note_id=note.id,
        extraction=extraction,
    )

    assert summary["persons"]["reused"] == 1
    count_stmt = (
        select(func.count()).select_from(Person).where(Person.user_id == user.id)
    )
    count = (await async_db_session.execute(count_stmt)).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_note_ingest_creates_habit_without_start_date(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    note = await _create_note(async_db_session, user, content="启动21天财富计划")

    extraction = EntityExtraction(
        note=NoteDraft(content="启动21天财富计划", tags=[], person_refs=[]),
        habits=[
            HabitDraft(
                ref="habit-1",
                title="21天财富自由计划",
                description="每天练习财富方案",
                duration_days=None,
            )
        ],
    )

    summary = await note_ingest_executor.execute(
        async_db_session,
        user_id=user.id,
        note_id=note.id,
        extraction=extraction,
    )

    assert summary["habits"]["created"] == 1
    habit_stmt = select(Habit).where(
        Habit.user_id == user.id, Habit.deleted_at.is_(None)
    )
    habit = (await async_db_session.execute(habit_stmt)).scalar_one()
    assert habit.title == "21天财富自由计划"
    assert habit.start_date == date.today()
