from __future__ import annotations

from uuid import UUID

import pytest

from app.api.routers import actual_event_templates as templates_router
from backend.tests.api_utils import create_test_client
from backend.tests.utils import (
    create_actual_event_template,
    create_dimension,
    create_person,
    create_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _post(
    path: str,
    *,
    async_session_maker,
    async_db_session,
    current_user,
    json: dict | None = None,
):
    async with create_test_client(
        templates_router.router,
        async_session_maker=async_session_maker,
        current_user=current_user,
        db_session=async_db_session,
    ) as client:
        return await client.post(path, json=json)


async def test_bump_usage_endpoint_returns_hydrated_template(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await create_dimension(async_db_session, user, name="Focus")
    person_a = await create_person(async_db_session, user, name="Alice")
    person_b = await create_person(async_db_session, user, name="Bob")

    template = await create_actual_event_template(
        async_db_session,
        user,
        title="Deep Work",
        dimension_id=dimension.id,
        person_ids=[person_b.id, person_a.id],
        usage_count=3,
    )
    before_usage = template.usage_count

    response = await _post(
        f"/actual-events/templates/{template.id}/bump-usage",
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        current_user=user,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dimension_id"] == str(dimension.id)
    assert payload["dimension_name"] == dimension.name
    assert payload["dimension_color"] == dimension.color
    assert payload["usage_count"] == before_usage + 1
    assert payload["last_used_at"] is not None
    returned_person_ids = payload["person_ids"]
    assert returned_person_ids == sorted(
        [str(person_a.id), str(person_b.id)], key=lambda value: value
    )
    assert {UUID(item["id"]) for item in payload["persons"]} == {
        person_a.id,
        person_b.id,
    }


async def test_create_template_endpoint_returns_dimension_metadata(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await create_dimension(async_db_session, user, name="Wellness")

    response = await _post(
        "/actual-events/templates/",
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        current_user=user,
        json={
            "title": "Morning Routine",
            "dimension_id": str(dimension.id),
            "position": 1,
            "default_duration_minutes": 30,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["dimension_id"] == str(dimension.id)
    assert payload["dimension_name"] == dimension.name
    assert payload["dimension_color"] == dimension.color
    assert payload["usage_count"] == 0
    assert payload["person_ids"] == []
    assert payload["persons"] == []
