from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.routers import actual_events as actual_events_router
from app.db.models.actual_event import ActualEvent
from app.handlers import notes as note_service
from app.schemas.note import NoteCreate
from backend.tests.api_utils import create_test_client
from backend.tests.utils import (
    create_dimension,
    create_person,
    create_task,
    create_user,
    create_vision,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_create_actual_event_route(async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await create_dimension(async_db_session, user)
    vision = await create_vision(async_db_session, user, dimension=dimension)
    task = await create_task(async_db_session, user, vision)
    person = await create_person(async_db_session, user)

    payload = {
        "title": "Deep Work",
        "start_time": "2025-01-01T09:00:00Z",
        "end_time": "2025-01-01T10:30:00Z",
        "dimension_id": str(dimension.id),
        "task_id": str(task.id),
        "person_ids": [str(person.id)],
    }

    async with create_test_client(
        actual_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        db_session=async_db_session,
    ) as client:
        response = await client.post("/actual-events/", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Deep Work"
    assert data["task"]["id"] == str(task.id)
    assert data["persons"][0]["display_name"] == person.display_name
    assert data["energy_injections"] is None or isinstance(
        data["energy_injections"], list
    )
    assert data["linked_notes"] == []


async def test_update_actual_event_route(
    async_db_session, async_session_maker, monkeypatch
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await create_dimension(async_db_session, user)
    new_dimension = await create_dimension(async_db_session, user, name="Deep Focus")
    vision = await create_vision(async_db_session, user, dimension=dimension)
    task = await create_task(async_db_session, user, vision)

    create_payload = {
        "title": "Morning Focus",
        "start_time": "2025-04-01T08:00:00Z",
        "end_time": "2025-04-01T09:30:00Z",
        "dimension_id": str(dimension.id),
        "task_id": str(task.id),
    }

    async def fake_schedule_recalc_jobs(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.handlers.actual_events.schedule_recalc_jobs",
        fake_schedule_recalc_jobs,
    )

    async with create_test_client(
        actual_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        db_session=async_db_session,
    ) as client:
        create_resp = await client.post("/actual-events/", json=create_payload)
        assert create_resp.status_code == 201
        event_id = create_resp.json()["id"]

        update_payload = {
            "title": "Afternoon Focus",
            "dimension_id": str(new_dimension.id),
        }
        update_resp = await client.put(
            f"/actual-events/{event_id}",
            json=update_payload,
        )

    assert update_resp.status_code == 200
    data = update_resp.json()
    assert data["id"] == event_id
    assert data["title"] == "Afternoon Focus"
    assert data["dimension_summary"]["id"] == str(new_dimension.id)
    assert data["dimension_summary"]["name"] == "Deep Focus"


async def test_create_actual_event_rejects_deprecated_fields(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await create_dimension(async_db_session, user)

    payload = {
        "title": "Legacy",
        "start_time": "2025-01-02T09:00:00Z",
        "end_time": "2025-01-02T10:00:00Z",
        "dimension_id": str(dimension.id),
        "completed_task_ids": [str(uuid4())],
    }

    async with create_test_client(
        actual_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        db_session=async_db_session,
    ) as client:
        response = await client.post("/actual-events/", json=payload)

    assert response.status_code == 400


async def test_read_actual_events_range(async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await create_dimension(async_db_session, user)
    vision = await create_vision(async_db_session, user, dimension=dimension)
    task = await create_task(async_db_session, user, vision)

    create_payload = {
        "title": "Planning",
        "start_time": "2025-03-01T09:00:00Z",
        "end_time": "2025-03-01T10:00:00Z",
        "dimension_id": str(dimension.id),
        "task_id": str(task.id),
    }

    async with create_test_client(
        actual_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        db_session=async_db_session,
    ) as client:
        await client.post("/actual-events/", json=create_payload)
        response = await client.get(
            "/actual-events/",
            params={
                "start": "2025-03-01T00:00:00Z",
                "end": "2025-03-02T00:00:00Z",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    events = payload["items"]
    assert len(events) == 1
    assert events[0]["title"] == "Planning"
    assert events[0]["linked_notes"] == []
    assert events[0]["linked_notes_count"] == 0


async def test_read_actual_events_range_includes_linked_notes(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await create_dimension(async_db_session, user)

    create_payload = {
        "title": "Deep focus",
        "start_time": "2025-03-05T09:00:00Z",
        "end_time": "2025-03-05T10:00:00Z",
        "dimension_id": str(dimension.id),
    }

    async with create_test_client(
        actual_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        db_session=async_db_session,
    ) as client:
        await client.post("/actual-events/", json=create_payload)

    result = await async_db_session.execute(
        select(ActualEvent).where(ActualEvent.user_id == user.id)
    )
    event = result.scalars().one()
    await note_service.create_note(
        async_db_session,
        user_id=user.id,
        note_in=NoteCreate(content="Reflection", actual_event_ids=[event.id]),
    )

    async with create_test_client(
        actual_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        db_session=async_db_session,
    ) as client:
        response = await client.get(
            "/actual-events/",
            params={
                "start": "2025-03-05T00:00:00Z",
                "end": "2025-03-06T00:00:00Z",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    events = payload["items"]
    assert len(events) == 1
    assert events[0]["linked_notes"] == []
    assert events[0]["linked_notes_count"] == 1
