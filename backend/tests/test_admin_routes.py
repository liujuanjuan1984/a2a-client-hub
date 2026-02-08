from __future__ import annotations

from uuid import uuid4

import pytest

from app.api import deps
from app.api.routers import admin as admin_router
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_task, create_user, create_vision

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_recompute_vision_efforts_requires_superuser(
    async_db_session, async_session_maker
):
    regular_user = await create_user(
        async_db_session, is_superuser=False, skip_onboarding_defaults=True
    )

    async with create_test_client(
        admin_router.router,
        async_session_maker=async_session_maker,
        current_user=regular_user,
        db_session=async_db_session,
    ) as client:
        response = await client.post(f"/admin/maintenance/recompute/vision/{uuid4()}")
        assert response.status_code == 403


async def test_recompute_vision_efforts_success(
    async_db_session, async_session_maker, monkeypatch
):
    admin_user = await create_user(
        async_db_session, is_superuser=True, skip_onboarding_defaults=True
    )
    vision = await create_vision(async_db_session, admin_user)
    task_one = await create_task(async_db_session, admin_user, vision)
    task_two = await create_task(async_db_session, admin_user, vision)

    calls: list = []

    async def fake_recompute_subtree_totals(db, task_id):
        calls.append(task_id)

    monkeypatch.setattr(
        "app.handlers.admin.recompute_subtree_totals",
        fake_recompute_subtree_totals,
    )

    async def override_current_admin():
        return admin_user

    overrides = {deps.get_current_admin_user: override_current_admin}

    async with create_test_client(
        admin_router.router,
        async_session_maker=async_session_maker,
        current_user=admin_user,
        db_session=async_db_session,
        overrides=overrides,
    ) as client:
        response = await client.post(f"/admin/maintenance/recompute/vision/{vision.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["vision_id"] == str(vision.id)
    assert set(data["recomputed_roots"]) == {str(task_one.id), str(task_two.id)}
    assert set(calls) == {task_one.id, task_two.id}


async def test_recompute_task_efforts_not_found(
    async_db_session, async_session_maker, monkeypatch
):
    admin_user = await create_user(
        async_db_session, is_superuser=True, skip_onboarding_defaults=True
    )

    async def override_current_admin():
        return admin_user

    overrides = {deps.get_current_admin_user: override_current_admin}

    async with create_test_client(
        admin_router.router,
        async_session_maker=async_session_maker,
        current_user=admin_user,
        db_session=async_db_session,
        overrides=overrides,
    ) as client:
        response = await client.post(f"/admin/maintenance/recompute/task/{uuid4()}")

    assert response.status_code == 404
