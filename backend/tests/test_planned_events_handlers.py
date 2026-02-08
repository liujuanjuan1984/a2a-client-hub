from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.handlers import planned_events as planned_events_service
from app.handlers.planned_events import InvalidPlannedEventStatusError
from app.schemas.planned_event import PlannedEventCreate
from backend.tests.utils import create_dimension, create_person, create_user

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


async def test_create_planned_event_attaches_persons(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await create_dimension(async_db_session, user)
    person = await create_person(async_db_session, user)

    event = await planned_events_service.create_planned_event(
        async_db_session,
        user_id=user.id,
        event_in=PlannedEventCreate(
            title="Strategy Session",
            start_time=datetime(2025, 4, 5, 9, 0, tzinfo=timezone.utc),
            end_time=datetime(2025, 4, 5, 10, 0, tzinfo=timezone.utc),
            dimension_id=dimension.id,
            person_ids=[str(person.id)],
        ),
    )

    assert hasattr(event, "persons")
    assert event.persons and event.persons[0].id == person.id


async def test_list_planned_events_invalid_status_raises(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    with pytest.raises(InvalidPlannedEventStatusError):
        await planned_events_service.list_planned_events(
            async_db_session, user_id=user.id, status="unknown"
        )
