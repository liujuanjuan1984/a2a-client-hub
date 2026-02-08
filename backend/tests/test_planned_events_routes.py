from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.api.routers import planned_events as planned_events_router
from app.db.models.planned_event_occurrence_exception import (
    PlannedEventOccurrenceException,
)
from app.handlers import planned_events as planned_events_service
from backend.tests.api_utils import create_test_client
from backend.tests.conftest import _truncate_all_tables
from backend.tests.utils import create_dimension, create_person, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(scope="function")
def planned_events_test_state(async_session_maker, async_engine):
    """Create a fresh user plus related fixtures per test."""

    async def _setup():
        async with async_session_maker() as session:
            user = await create_user(session, skip_onboarding_defaults=True)
            dimension = await create_dimension(session, user)
            person = await create_person(session, user)
            await session.commit()
            await session.refresh(user)
            session.expunge(user)
            session.expunge(dimension)
            session.expunge(person)
            return {
                "user": user,
                "dimension": dimension,
                "person": person,
            }

    state = asyncio.run(_setup())

    try:
        yield state
    finally:
        asyncio.run(_truncate_all_tables(async_engine))


async def test_create_planned_event_route(
    planned_events_test_state, async_session_maker
):
    user = planned_events_test_state["user"]
    dimension = planned_events_test_state["dimension"]
    person = planned_events_test_state["person"]

    payload = {
        "title": "Strategy Session",
        "start_time": "2025-06-01T09:00:00Z",
        "end_time": "2025-06-01T10:00:00Z",
        "dimension_id": str(dimension.id),
        "person_ids": [str(person.id)],
    }

    async with create_test_client(
        planned_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.post("/planned-events/", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Strategy Session"
    assert data["persons"][0]["id"] == str(person.id)


async def test_read_planned_events_raw_invalid_status(
    planned_events_test_state, async_session_maker
):
    user = planned_events_test_state["user"]

    async with create_test_client(
        planned_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.get("/planned-events/raw", params={"status": "unknown"})

    assert response.status_code == 400


async def test_read_planned_event_not_found_returns_404(
    planned_events_test_state, async_session_maker
):
    user = planned_events_test_state["user"]

    async with create_test_client(
        planned_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.get(f"/planned-events/{uuid4()}")

    assert response.status_code == 404


async def test_update_planned_event_not_found_returns_404(
    planned_events_test_state, async_session_maker
):
    user = planned_events_test_state["user"]
    payload = {"title": "Updated"}

    async with create_test_client(
        planned_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.put(f"/planned-events/{uuid4()}", json=payload)

    assert response.status_code == 404


async def test_delete_planned_event_not_found_returns_404(
    planned_events_test_state, async_session_maker
):
    user = planned_events_test_state["user"]

    async with create_test_client(
        planned_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.delete(f"/planned-events/{uuid4()}")

    assert response.status_code == 404


async def test_update_planned_event_accepts_integer_priority(
    planned_events_test_state, async_session_maker
):
    user = planned_events_test_state["user"]
    dimension = planned_events_test_state["dimension"]

    create_payload = {
        "title": "Daily Reflection",
        "start_time": "2025-06-02T09:00:00Z",
        "end_time": "2025-06-02T09:30:00Z",
        "dimension_id": str(dimension.id),
    }

    async with create_test_client(
        planned_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_response = await client.post("/planned-events/", json=create_payload)
        assert create_response.status_code == 201
        event_id = create_response.json()["id"]

        update_response = await client.put(
            f"/planned-events/{event_id}", json={"priority": 4}
        )

    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["priority"] == 4


async def test_delete_single_occurrence_only_removes_selected_instance(
    planned_events_test_state, async_session_maker
):
    user = planned_events_test_state["user"]
    dimension = planned_events_test_state["dimension"]

    create_payload = {
        "title": "Bedtime Routine",
        "start_time": "2025-06-05T12:30:00Z",
        "end_time": "2025-06-05T13:00:00Z",
        "dimension_id": str(dimension.id),
        "is_recurring": True,
        "rrule_string": "FREQ=DAILY",
    }

    async with create_test_client(
        planned_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_response = await client.post("/planned-events/", json=create_payload)
        assert create_response.status_code == 201
        master_id = create_response.json()["id"]
        master_uuid = UUID(master_id)

        list_response = await client.get(
            "/planned-events/",
            params={
                "start": "2025-06-05T00:00:00Z",
                "end": "2025-06-08T00:00:00Z",
            },
        )
        assert list_response.status_code == 200
        data = list_response.json()["items"]
        assert len(data) >= 2
        target = next(item for item in data if item.get("master_event_id") == master_id)
        assert target["is_instance"] is True

        delete_response = await client.delete(
            f"/planned-events/{master_id}",
            params={
                "delete_type": "single",
                "instance_id": target.get("instance_id"),
                "instance_start": target["start_time"],
            },
        )
        assert delete_response.status_code == 204

        async with async_session_maker() as session:
            result = await session.execute(
                select(PlannedEventOccurrenceException).where(
                    PlannedEventOccurrenceException.master_event_id == master_uuid,
                    PlannedEventOccurrenceException.action == "skip",
                )
            )
            rows = result.scalars().all()
            assert len(rows) == 1

        confirm_response = await client.get(
            "/planned-events/",
            params={
                "start": "2025-06-05T00:00:00Z",
                "end": "2025-06-08T00:00:00Z",
            },
        )
        assert confirm_response.status_code == 200
        refreshed = confirm_response.json()["items"]
        assert all(item["start_time"] != target["start_time"] for item in refreshed)
        assert any(item["start_time"] != target["start_time"] for item in refreshed)


async def test_delete_all_future_truncates_recurring_instances(
    planned_events_test_state, async_session_maker
):
    user = planned_events_test_state["user"]
    dimension = planned_events_test_state["dimension"]

    create_payload = {
        "title": "Focus Session",
        "start_time": "2025-06-10T08:00:00Z",
        "end_time": "2025-06-10T09:00:00Z",
        "dimension_id": str(dimension.id),
        "is_recurring": True,
        "rrule_string": "FREQ=DAILY",
    }

    async with create_test_client(
        planned_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_response = await client.post("/planned-events/", json=create_payload)
        assert create_response.status_code == 201
        master_id = create_response.json()["id"]
        master_uuid = UUID(master_id)

        list_response = await client.get(
            "/planned-events/",
            params={
                "start": "2025-06-10T00:00:00Z",
                "end": "2025-06-15T00:00:00Z",
            },
        )
        assert list_response.status_code == 200
        data = list_response.json()["items"]
        assert len(data) >= 3
        target = next(item for item in data if item.get("master_event_id") == master_id)

        delete_response = await client.delete(
            f"/planned-events/{master_id}",
            params={
                "delete_type": "all_future",
                "instance_id": target.get("instance_id"),
                "instance_start": target["start_time"],
            },
        )
        assert delete_response.status_code == 204

        async with async_session_maker() as session:
            result = await session.execute(
                select(PlannedEventOccurrenceException).where(
                    PlannedEventOccurrenceException.master_event_id == master_uuid,
                    PlannedEventOccurrenceException.action == "truncate",
                )
            )
            truncate_rows = result.scalars().all()
            assert len(truncate_rows) == 1
            assert (
                truncate_rows[0].instance_start.isoformat().replace("+00:00", "Z")
                == target["start_time"]
            )
            bundles = await planned_events_service._load_occurrence_exceptions(  # type: ignore[attr-defined]
                session,
                user_id=user.id,
                master_event_ids=[master_uuid],
            )
            assert master_uuid in bundles
            assert (
                bundles[master_uuid].truncate_after == truncate_rows[0].instance_start
            )
            service_payload = await planned_events_service.list_planned_events_in_range(  # type: ignore[attr-defined]
                session,
                user_id=user.id,
                start=datetime.fromisoformat("2025-06-10T00:00:00+00:00"),
                end=datetime.fromisoformat("2025-06-15T00:00:00+00:00"),
            )
            target_boundary = datetime.fromisoformat(
                target["start_time"].replace("Z", "+00:00")
            )
            service_start_times = [
                row["start_time"].isoformat().replace("+00:00", "Z")
                for row in service_payload
                if row.get("master_event_id") == master_uuid
            ]
            assert target["start_time"] not in service_start_times
            assert all(
                datetime.fromisoformat(ts.replace("Z", "+00:00")) < target_boundary
                for ts in service_start_times
            )

        confirm_response = await client.get(
            "/planned-events/",
            params={
                "start": "2025-06-10T00:00:00Z",
                "end": "2025-06-15T00:00:00Z",
            },
        )
        assert confirm_response.status_code == 200
        refreshed = confirm_response.json()["items"]
        remaining_starts = [
            item["start_time"]
            for item in refreshed
            if item.get("master_event_id") == master_id
        ]
        assert target["start_time"] not in remaining_starts
        assert all(
            datetime.fromisoformat(item.replace("Z", "+00:00"))
            < datetime.fromisoformat(target["start_time"].replace("Z", "+00:00"))
            for item in remaining_starts
        )


async def test_update_single_occurrence_overrides_only_target_instance(
    planned_events_test_state, async_session_maker
):
    user = planned_events_test_state["user"]
    dimension = planned_events_test_state["dimension"]

    create_payload = {
        "title": "下午例行检视",
        "start_time": "2025-07-01T08:00:00Z",
        "end_time": "2025-07-01T09:00:00Z",
        "dimension_id": str(dimension.id),
        "is_recurring": True,
        "rrule_string": "FREQ=DAILY",
    }

    async with create_test_client(
        planned_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_response = await client.post("/planned-events/", json=create_payload)
        assert create_response.status_code == 201
        master_id = create_response.json()["id"]

        list_response = await client.get(
            "/planned-events/",
            params={
                "start": "2025-07-01T00:00:00Z",
                "end": "2025-07-05T00:00:00Z",
            },
        )
        assert list_response.status_code == 200
        range_items = [
            row
            for row in list_response.json()["items"]
            if row.get("master_event_id") == master_id
        ]
        target = next(
            row for row in range_items if row["start_time"].startswith("2025-07-02T")
        )

        new_start = "2025-07-02T10:30:00Z"
        new_end = "2025-07-02T11:00:00Z"

        update_response = await client.put(
            f"/planned-events/{master_id}",
            params={
                "update_type": "single",
                "instance_id": target.get("instance_id"),
                "instance_start": target["start_time"],
            },
            json={
                "title": "延后例会",
                "start_time": new_start,
                "end_time": new_end,
            },
        )
        assert update_response.status_code == 200

        confirm_response = await client.get(
            "/planned-events/",
            params={
                "start": "2025-07-01T00:00:00Z",
                "end": "2025-07-05T00:00:00Z",
            },
        )
        assert confirm_response.status_code == 200
        refreshed = [
            row
            for row in confirm_response.json()["items"]
            if row.get("master_event_id") == master_id
        ]
        assert any(row["start_time"] == new_start for row in refreshed)
        assert any(
            row["start_time"].startswith("2025-07-01T08:00:00") for row in refreshed
        )
        assert all(
            (row["start_time"] == new_start) == row["title"].startswith("延后例会")
            for row in refreshed
        )

        async with async_session_maker() as session:
            result = await session.execute(
                select(PlannedEventOccurrenceException).where(
                    PlannedEventOccurrenceException.master_event_id == UUID(master_id),
                    PlannedEventOccurrenceException.action == "override",
                )
            )
            overrides = result.scalars().all()
            assert len(overrides) == 1
            assert overrides[0].payload is not None
            assert overrides[0].payload.get("start_time").startswith(new_start[:19])

        # Perform another single-occurrence edit without changing start_time
        updated_title = "再次延后例会"
        second_update = await client.put(
            f"/planned-events/{master_id}",
            params={
                "update_type": "single",
                "instance_id": target.get("instance_id"),
                "instance_start": new_start,
            },
            json={
                "title": updated_title,
            },
        )
        assert second_update.status_code == 200

        async with async_session_maker() as session:
            result = await session.execute(
                select(PlannedEventOccurrenceException).where(
                    PlannedEventOccurrenceException.master_event_id == UUID(master_id),
                    PlannedEventOccurrenceException.action == "override",
                )
            )
            overrides = result.scalars().all()
            assert len(overrides) == 1
            assert overrides[0].deleted_at is None
            assert overrides[0].payload is not None
            assert overrides[0].payload.get("start_time").startswith(new_start[:19])
            assert overrides[0].payload.get("title") == updated_title


async def test_update_all_future_creates_new_master_event(
    planned_events_test_state, async_session_maker
):
    user = planned_events_test_state["user"]
    dimension = planned_events_test_state["dimension"]

    create_payload = {
        "title": "晨间写作",
        "start_time": "2025-08-01T06:00:00Z",
        "end_time": "2025-08-01T06:30:00Z",
        "dimension_id": str(dimension.id),
        "is_recurring": True,
        "rrule_string": "FREQ=DAILY",
    }

    async with create_test_client(
        planned_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_response = await client.post("/planned-events/", json=create_payload)
        assert create_response.status_code == 201
        master_id = create_response.json()["id"]

        list_response = await client.get(
            "/planned-events/",
            params={
                "start": "2025-08-01T00:00:00Z",
                "end": "2025-08-06T00:00:00Z",
            },
        )
        assert list_response.status_code == 200
        range_items = [
            row
            for row in list_response.json()["items"]
            if row.get("master_event_id") == master_id
        ]
        target = next(
            row for row in range_items if row["start_time"].startswith("2025-08-03T")
        )
        target_start = target["start_time"]

        new_start = "2025-08-03T09:30:00Z"
        new_end = "2025-08-03T10:00:00Z"
        update_response = await client.put(
            f"/planned-events/{master_id}",
            params={
                "update_type": "all_future",
                "instance_id": target.get("instance_id"),
                "instance_start": target["start_time"],
            },
            json={
                "title": "晨间写作（秋季版）",
                "start_time": new_start,
                "end_time": new_end,
            },
        )
        assert update_response.status_code == 200
        split_event = update_response.json()
        assert split_event["id"] != master_id
        new_master_id = split_event["id"]

        async with async_session_maker() as session:
            result = await session.execute(
                select(PlannedEventOccurrenceException).where(
                    PlannedEventOccurrenceException.master_event_id == UUID(master_id),
                    PlannedEventOccurrenceException.action == "truncate",
                )
            )
            truncate_rows = result.scalars().all()
            assert truncate_rows, "truncate exception should be recorded"
            assert (
                truncate_rows[0]
                .instance_start.isoformat()
                .replace("+00:00", "Z")
                .startswith(target_start[:19])
            )

        confirm_response = await client.get(
            "/planned-events/",
            params={
                "start": "2025-08-01T00:00:00Z",
                "end": "2025-08-06T00:00:00Z",
            },
        )
        assert confirm_response.status_code == 200
        refreshed = confirm_response.json()["items"]
        original_instances = [
            row for row in refreshed if row.get("master_event_id") == master_id
        ]
        future_instances = [
            row for row in refreshed if row.get("master_event_id") == new_master_id
        ]
        assert original_instances
        assert future_instances
        assert all(
            datetime.fromisoformat(row["start_time"].replace("Z", "+00:00"))
            < datetime.fromisoformat(target_start.replace("Z", "+00:00"))
            for row in original_instances
        )
        assert all(
            datetime.fromisoformat(row["start_time"].replace("Z", "+00:00"))
            >= datetime.fromisoformat(new_start.replace("Z", "+00:00"))
            for row in future_instances
        )
        assert any(row["title"].startswith("晨间写作（秋季版）") for row in future_instances)


async def test_update_single_non_recurring_returns_400(
    planned_events_test_state, async_session_maker
):
    user = planned_events_test_state["user"]
    dimension = planned_events_test_state["dimension"]

    create_payload = {
        "title": "单次会议",
        "start_time": "2025-09-10T09:00:00Z",
        "end_time": "2025-09-10T10:00:00Z",
        "dimension_id": str(dimension.id),
    }

    async with create_test_client(
        planned_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_response = await client.post("/planned-events/", json=create_payload)
        assert create_response.status_code == 201
        event_id = create_response.json()["id"]

        update_response = await client.put(
            f"/planned-events/{event_id}",
            params={
                "update_type": "single",
                "instance_start": "2025-09-10T09:00:00Z",
            },
            json={"title": "更新后的会议"},
        )
        assert update_response.status_code == 400


async def test_cross_day_instance_included_in_next_day_range(
    planned_events_test_state, async_session_maker
):
    user = planned_events_test_state["user"]
    dimension = planned_events_test_state["dimension"]

    create_payload = {
        "title": "夜间睡眠",
        "start_time": "2025-12-30T22:00:00Z",
        "end_time": "2025-12-31T06:00:00Z",
        "dimension_id": str(dimension.id),
        "is_recurring": True,
        "rrule_string": "FREQ=DAILY",
    }

    async with create_test_client(
        planned_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_response = await client.post("/planned-events/", json=create_payload)
        assert create_response.status_code == 201
        master_id = create_response.json()["id"]

        list_response = await client.get(
            "/planned-events/",
            params={
                "start": "2025-12-31T00:00:00Z",
                "end": "2026-01-01T00:00:00Z",
            },
        )
        assert list_response.status_code == 200
        data = list_response.json()["items"]
        assert any(row["id"] == master_id for row in data)
        assert any(
            (row.get("end_time") or "").startswith("2025-12-31T06:00:00")
            for row in data
        )


async def test_planned_events_query_skips_truncated_recurring_series(
    planned_events_test_state, async_session_maker, monkeypatch
):
    user = planned_events_test_state["user"]
    dimension = planned_events_test_state["dimension"]

    seen_lengths: List[int] = []
    original_expand = planned_events_service.expand_planned_events_with_recurrence

    def _capture(events, start, end, exceptions=None):
        seen_lengths.append(len(events))
        return original_expand(events, start, end, exceptions=exceptions)

    monkeypatch.setattr(
        planned_events_service,
        "expand_planned_events_with_recurrence",
        _capture,
    )

    async with create_test_client(
        planned_events_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        legacy_payload = {
            "title": "历史系列-晨间瑜伽",
            "start_time": "2025-05-01T06:00:00Z",
            "end_time": "2025-05-01T06:30:00Z",
            "dimension_id": str(dimension.id),
            "is_recurring": True,
            "rrule_string": "FREQ=DAILY",
        }
        legacy_response = await client.post("/planned-events/", json=legacy_payload)
        assert legacy_response.status_code == 201
        legacy_master = legacy_response.json()["id"]

        list_response = await client.get(
            "/planned-events/",
            params={
                "start": "2025-05-01T00:00:00Z",
                "end": "2025-05-10T00:00:00Z",
            },
        )
        assert list_response.status_code == 200
        legacy_occurrence = next(
            row
            for row in list_response.json()["items"]
            if row.get("master_event_id") == legacy_master
            and row["start_time"].startswith("2025-05-05T")
        )

        delete_response = await client.delete(
            f"/planned-events/{legacy_master}",
            params={
                "delete_type": "all_future",
                "instance_id": legacy_occurrence.get("instance_id"),
                "instance_start": legacy_occurrence["start_time"],
            },
        )
        assert delete_response.status_code == 204

        active_payload = {
            "title": "现行系列-晨跑",
            "start_time": "2025-07-01T07:00:00Z",
            "end_time": "2025-07-01T07:30:00Z",
            "dimension_id": str(dimension.id),
            "is_recurring": True,
            "rrule_string": "FREQ=DAILY",
        }
        active_response = await client.post("/planned-events/", json=active_payload)
        assert active_response.status_code == 201
        active_master = active_response.json()["id"]

        final_response = await client.get(
            "/planned-events/",
            params={
                "start": "2025-07-01T00:00:00Z",
                "end": "2025-07-05T00:00:00Z",
            },
        )
        assert final_response.status_code == 200
        results = [
            row
            for row in final_response.json()["items"]
            if row.get("master_event_id") == active_master
        ]
        assert results
        assert seen_lengths
        assert seen_lengths[-1] == 1
