from __future__ import annotations

import pytest
from fastapi import HTTPException, status

from app.api import deps
from app.api.routers import invitations as invitations_router
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _override_admin(user):
    async def _current_admin():
        return user

    return _current_admin


def _enforcing_admin_override(user):
    async def _current_admin():
        if not user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admins only",
            )
        return user

    return _current_admin


async def test_admin_can_create_and_list_invitations(
    async_db_session, async_session_maker
):
    admin_user = await create_user(
        async_db_session, is_superuser=True, skip_onboarding_defaults=True
    )

    overrides = {deps.get_current_admin_user: _override_admin(admin_user)}

    async with create_test_client(
        invitations_router.router,
        async_session_maker=async_session_maker,
        current_user=admin_user,
        overrides=overrides,
    ) as client:
        routes = {
            (route.path, tuple(sorted(route.methods or [])))
            for route in invitations_router.router.routes
        }
        assert ("/invitations/", ("POST",)) in routes

        create_response = await client.post(
            "/invitations/",
            json={"email": "invitee@example.com"},
        )
        assert create_response.status_code == 201, create_response.text
        created = create_response.json()
        assert created["target_email"] == "invitee@example.com"
        assert created["status"] == "pending"

        mine_response = await client.get("/invitations/mine")
        assert mine_response.status_code == 200
        mine_items = mine_response.json()["items"]
        assert any(item["code"] == created["code"] for item in mine_items)

        invited_me_response = await client.get("/invitations/invited-me")
        assert invited_me_response.status_code == 200
        assert invited_me_response.json()["items"] == []


async def test_non_admin_cannot_create_invitation(
    async_db_session, async_session_maker
):
    member_user = await create_user(
        async_db_session, is_superuser=False, skip_onboarding_defaults=True
    )

    overrides = {deps.get_current_admin_user: _enforcing_admin_override(member_user)}

    async with create_test_client(
        invitations_router.router,
        async_session_maker=async_session_maker,
        current_user=member_user,
        overrides=overrides,
    ) as client:
        response = await client.post(
            "/invitations/",
            json={"email": "member@example.com"},
        )

    assert response.status_code == 403, response.text


async def test_lookup_and_revoke_invitation(async_db_session, async_session_maker):
    admin_user = await create_user(
        async_db_session, is_superuser=True, skip_onboarding_defaults=True
    )
    overrides = {deps.get_current_admin_user: _override_admin(admin_user)}

    async with create_test_client(
        invitations_router.router,
        async_session_maker=async_session_maker,
        current_user=admin_user,
        overrides=overrides,
    ) as client:
        create_response = await client.post(
            "/invitations/",
            json={"email": "target@example.com"},
        )
        assert create_response.status_code == 201, create_response.text
        invitation = create_response.json()

        lookup_response = await client.get(f"/invitations/lookup/{invitation['code']}")
        assert lookup_response.status_code == 200
        assert lookup_response.json()["target_email"] == "target@example.com"

        delete_response = await client.delete(f"/invitations/{invitation['id']}")
        assert delete_response.status_code == 204

        lookup_after_delete = await client.get(
            f"/invitations/lookup/{invitation['code']}"
        )
        assert lookup_after_delete.status_code == 404
