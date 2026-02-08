from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import pytest

from app.db.models.actual_event import ActualEvent
from app.handlers import actual_events as actual_events_service
from app.handlers import associations_async
from app.handlers.actual_events import ActualEventNotFoundError
from app.handlers.associations_async import LinkType, ModelName
from app.schemas.actual_event import ActualEventCreate
from backend.tests.utils import (
    create_dimension,
    create_person,
    create_task,
    create_user,
    create_vision,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_create_actual_event_persists_and_links_persons(
    async_db_session, monkeypatch
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await create_dimension(async_db_session, user)
    vision = await create_vision(async_db_session, user, dimension=dimension)
    task = await create_task(async_db_session, user, vision)
    person = await create_person(async_db_session, user)

    # Silence expensive downstream integrations
    async def fake_schedule_recalc_jobs(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.handlers.actual_events.schedule_recalc_jobs",
        fake_schedule_recalc_jobs,
    )

    stats_calls = {}

    def fake_recompute_daily_stats(db, event, user_id):
        stats_calls["recompute_daily_stats"] = (event.id, user_id)

    monkeypatch.setattr(
        "app.handlers.actual_events.recompute_daily_stats_for_event",
        fake_recompute_daily_stats,
    )

    payload = ActualEventCreate(
        title="Deep Work",
        start_time=datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc),
        end_time=datetime(2025, 1, 1, 10, 30, tzinfo=timezone.utc),
        dimension_id=dimension.id,
        task_id=task.id,
        person_ids=[str(person.id)],
    )

    event, energy = await actual_events_service.create_actual_event(
        async_db_session,
        user_id=user.id,
        event_in=payload,
    )

    assert event.task_id == task.id
    assert event.dimension_id == dimension.id
    assert len(energy) == 0
    assert stats_calls["recompute_daily_stats"][1] == user.id

    persons_map = await associations_async.load_persons_for_sources(
        async_db_session,
        source_model=ModelName.ActualEvent,
        source_ids=[event.id],
        link_type=LinkType.ATTENDED_BY,
        user_id=user.id,
    )
    assert event.id in persons_map
    assert persons_map[event.id][0].id == person.id

    results = await actual_events_service.search_actual_events(
        async_db_session, user_id=user.id
    )
    assert len(results) == 1
    fetched_event, person_summaries, task_summary = results[0]
    assert fetched_event.id == event.id
    assert (
        person_summaries and person_summaries[0]["display_name"] == person.display_name
    )
    assert task_summary and task_summary["id"] == task.id

    paginated, total = await actual_events_service.list_actual_events_paginated(
        async_db_session, user_id=user.id, start_date=None, end_date=None
    )
    assert paginated and paginated[0][0].id == event.id
    assert total == 1


async def test_search_actual_events_dimension_not_found(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    with pytest.raises(ActualEventNotFoundError):
        await actual_events_service.search_actual_events(
            async_db_session,
            user_id=user.id,
            dimension_name="Nonexistent Dimension",
        )


async def test_batch_update_accepts_string_event_ids(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    person = await create_person(async_db_session, user)

    event = ActualEvent(
        user_id=user.id,
        title="Focus Session",
        start_time=datetime(2025, 3, 1, 9, 0, tzinfo=timezone.utc),
        end_time=datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc),
    )
    async_db_session.add(event)
    await async_db_session.flush()

    (
        updated_count,
        failed_ids,
        errors,
    ) = await actual_events_service.batch_update_actual_events(
        async_db_session,
        user_id=user.id,
        event_ids=[str(event.id)],
        update_type="persons",
        persons={"mode": "add", "person_ids": [str(person.id)]},
    )

    assert updated_count == 1
    assert failed_ids == []
    assert errors == []


async def test_search_actual_events_truncates_and_sets_metadata(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    for day in range(3):
        event = ActualEvent(
            user_id=user.id,
            title=f"Session {day}",
            start_time=datetime(2025, 3, 1 + day, 9, 0, tzinfo=timezone.utc),
            end_time=datetime(2025, 3, 1 + day, 10, 0, tzinfo=timezone.utc),
        )
        async_db_session.add(event)
    await async_db_session.flush()

    metadata: Dict[str, Any] = {}
    results = await actual_events_service.search_actual_events(
        async_db_session,
        user_id=user.id,
        start_date=datetime(2025, 3, 1, tzinfo=timezone.utc),
        end_date=datetime(2025, 3, 5, tzinfo=timezone.utc),
        max_results=2,
        allow_result_truncation=True,
        result_metadata=metadata,
    )

    assert len(results) == 2
    assert metadata["truncated"] is True
    assert metadata["limit"] == 2
    assert metadata["total_count"] == 3
    assert metadata["returned_count"] == 2


async def test_batch_update_accepts_uuid_instances(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    person = await create_person(async_db_session, user)

    event = ActualEvent(
        user_id=user.id,
        title="Focus Session",
        start_time=datetime(2025, 3, 1, 9, 0, tzinfo=timezone.utc),
        end_time=datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc),
    )
    async_db_session.add(event)
    await async_db_session.flush()

    (
        updated_count,
        failed_ids,
        errors,
    ) = await actual_events_service.batch_update_actual_events(
        async_db_session,
        user_id=user.id,
        event_ids=[event.id],
        update_type="persons",
        persons={"mode": "add", "person_ids": [str(person.id)]},
    )

    assert updated_count == 1
    assert failed_ids == []
    assert errors == []
