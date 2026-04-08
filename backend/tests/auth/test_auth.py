from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlalchemy import select
from starlette.requests import Request

from app.core.config import settings
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    build_jwks_document,
    create_user_refresh_token,
    create_user_token,
    get_password_hash,
    verify_refresh_token_claims,
)
from app.db.models.auth_audit_event import AuthAuditEvent
from app.db.models.auth_refresh_session import AuthRefreshSession
from app.db.models.invitation import Invitation, InvitationStatus
from app.db.models.user import User
from app.features.auth import router as auth_router
from app.features.auth import service as auth_handler
from app.features.auth.rate_limit import SlidingWindowRateLimiter
from app.features.auth.request_context import get_client_ip
from app.utils.timezone_util import utc_now
from tests.support.api_utils import create_test_client

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TRUSTED_ORIGIN = "http://localhost:3000"


async def run_in_session(async_session_maker, coro_fn):
    async with async_session_maker() as session:
        return await coro_fn(session)


def _build_request(
    *, client_host: str, headers: dict[str, str] | None = None
) -> Request:
    encoded_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": encoded_headers,
            "client": (client_host, 12345),
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )


async def _create_invitation(
    async_session_maker, *, creator_user_id: UUID, target_email: str
) -> Invitation:
    async def inserter(session):
        invitation = Invitation(
            code=uuid4().hex,
            creator_user_id=creator_user_id,
            target_email=target_email.lower(),
            status=InvitationStatus.PENDING,
        )
        session.add(invitation)
        await session.commit()
        await session.refresh(invitation)
        return invitation

    return await run_in_session(async_session_maker, inserter)


@pytest_asyncio.fixture()
async def client(async_session_maker, async_db_session) -> AsyncClient:
    async with create_test_client(
        auth_router.router,
        async_session_maker=async_session_maker,
        base_prefix=settings.api_v1_prefix,
    ) as test_client:
        yield test_client


async def test_register_user_creates_account_and_timezone(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "alice@example.com",
        "name": "Alice",
        "password": "Str0ngPass!1",
        "timezone": "Asia/Shanghai",
    }

    response = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == payload["email"]
    assert data["is_superuser"] is True  # first registered user gains superuser rights

    async def fetch_user(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        return result.scalar_one()

    created = await run_in_session(async_session_maker, fetch_user)
    assert created.timezone == payload["timezone"]


async def test_login_multi_user_mode_returns_token(client: AsyncClient) -> None:
    register_payload = {
        "email": "test@example.com",
        "name": "Test User",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }

    register_response = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=register_payload
    )
    assert register_response.status_code == 201

    # Now test login
    login_payload = {
        "email": "test@example.com",
        "password": "Str0ngPass!1",
    }

    response = await client.post(
        f"{settings.api_v1_prefix}/auth/login", json=login_payload
    )
    assert response.status_code == 200

    payload = response.json()
    assert UUID(payload["user"]["id"])
    assert payload["user"]["email"] == "test@example.com"
    assert payload["access_token"]
    assert payload["token_type"] == "bearer"
    assert payload["expires_in"] == settings.jwt_access_token_ttl_seconds


async def test_login_sets_refresh_cookie(client: AsyncClient) -> None:
    register_payload = {
        "email": "cookie@example.com",
        "name": "Cookie User",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }

    register_response = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=register_payload
    )
    assert register_response.status_code == 201

    login_payload = {"email": "cookie@example.com", "password": "Str0ngPass!1"}
    response = await client.post(
        f"{settings.api_v1_prefix}/auth/login", json=login_payload
    )
    assert response.status_code == 200

    set_cookie_headers = response.headers.get_list("set-cookie")
    assert any(
        header.startswith(f"{settings.auth_refresh_cookie_name}=")
        for header in set_cookie_headers
    )
    assert any("HttpOnly" in header for header in set_cookie_headers)


async def test_refresh_rotates_cookie_and_returns_new_access_token(
    client: AsyncClient,
    async_session_maker,
) -> None:
    register_payload = {
        "email": "refresh@example.com",
        "name": "Refresh User",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }

    register_response = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=register_payload
    )
    assert register_response.status_code == 201

    login_payload = {"email": "refresh@example.com", "password": "Str0ngPass!1"}
    login_response = await client.post(
        f"{settings.api_v1_prefix}/auth/login", json=login_payload
    )
    assert login_response.status_code == 200
    before = client.cookies.get(settings.auth_refresh_cookie_name)
    assert before

    refresh_response = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert refresh_response.status_code == 200, refresh_response.text
    payload = refresh_response.json()
    assert payload["access_token"]
    assert payload["token_type"] == "bearer"
    assert payload["expires_in"] == settings.jwt_access_token_ttl_seconds

    after = client.cookies.get(settings.auth_refresh_cookie_name)
    assert after
    assert after != before

    claims = verify_refresh_token_claims(after)
    assert claims is not None
    assert claims.session_id is not None

    async def inspect_sessions(session):
        result = await session.execute(select(AuthRefreshSession))
        return list(result.scalars())

    sessions = await run_in_session(async_session_maker, inspect_sessions)
    assert len(sessions) == 1
    assert sessions[0].current_jti == claims.jwt_id


async def test_refresh_rejects_missing_origin_header_without_native_marker(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "refresh-no-origin@example.com",
        "name": "Refresh User",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }
    register_response = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=payload
    )
    assert register_response.status_code == 201

    login_response = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login_response.status_code == 200

    refresh_response = await client.post(f"{settings.api_v1_prefix}/auth/refresh")
    assert refresh_response.status_code == 403

    async def inspect_events(session):
        result = await session.execute(
            select(AuthAuditEvent).where(AuthAuditEvent.event_type == "refresh_blocked")
        )
        return list(result.scalars())

    events = await run_in_session(async_session_maker, inspect_events)
    assert len(events) == 1
    assert events[0].event_metadata["reason"] == "untrusted_cookie_origin"


async def test_refresh_accepts_native_client_without_origin_header(
    client: AsyncClient,
) -> None:
    payload = {
        "email": "refresh-native@example.com",
        "name": "Refresh Native User",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }
    register_response = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=payload
    )
    assert register_response.status_code == 201

    login_response = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login_response.status_code == 200

    refresh_response = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"X-A2A-Client-Platform": "native"},
    )
    assert refresh_response.status_code == 200


async def test_refresh_invalid_token_is_rate_limited_before_jwt_validation(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "auth_refresh_rate_limit_max_attempts", 2)
    monkeypatch.setattr(settings, "auth_refresh_rate_limit_window_seconds", 60)
    monkeypatch.setattr(auth_router, "auth_rate_limiter", SlidingWindowRateLimiter())

    client.cookies.set(settings.auth_refresh_cookie_name, "invalid-refresh-token")

    first = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert first.status_code == 401

    second = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert second.status_code == 401

    third = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert third.status_code == 429


async def test_logout_revokes_current_refresh_session(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "logout@example.com",
        "name": "Logout User",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }
    await client.post(f"{settings.api_v1_prefix}/auth/register", json=payload)

    login_response = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login_response.status_code == 200
    refresh_cookie = client.cookies.get(settings.auth_refresh_cookie_name)
    assert refresh_cookie

    logout_response = await client.post(
        f"{settings.api_v1_prefix}/auth/logout",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert logout_response.status_code == 204

    client.cookies.set(settings.auth_refresh_cookie_name, refresh_cookie)
    refresh_response = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert refresh_response.status_code == 401

    async def inspect_audit(session):
        result = await session.execute(
            select(AuthAuditEvent).where(AuthAuditEvent.event_type == "logout")
        )
        return list(result.scalars())

    events = await run_in_session(async_session_maker, inspect_audit)
    assert len(events) == 1


async def test_logout_revokes_only_current_legacy_refresh_token(
    client: AsyncClient,
    async_session_maker,
) -> None:
    payload = {
        "email": "legacy-logout@example.com",
        "name": "Legacy Logout User",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }
    await client.post(f"{settings.api_v1_prefix}/auth/register", json=payload)

    async def fetch_user(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        return result.scalar_one()

    user = await run_in_session(async_session_maker, fetch_user)
    fixed_now = datetime(2026, 4, 8, 9, 30, tzinfo=timezone.utc)
    with patch("app.core.security.utc_now", return_value=fixed_now):
        first_cookie = create_user_refresh_token(user.id)
        second_cookie = create_user_refresh_token(user.id)

    assert first_cookie != second_cookie

    client.cookies.set(settings.auth_refresh_cookie_name, first_cookie)
    logout_response = await client.post(
        f"{settings.api_v1_prefix}/auth/logout",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert logout_response.status_code == 204

    client.cookies.set(settings.auth_refresh_cookie_name, first_cookie)
    revoked_refresh = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert revoked_refresh.status_code == 401

    client.cookies.set(settings.auth_refresh_cookie_name, second_cookie)
    surviving_refresh = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert surviving_refresh.status_code == 200


async def test_legacy_refresh_token_can_be_bootstrapped_only_once(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "legacy-bootstrap@example.com",
        "name": "Legacy Bootstrap User",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }
    await client.post(f"{settings.api_v1_prefix}/auth/register", json=payload)

    async def fetch_user(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        return result.scalar_one()

    user = await run_in_session(async_session_maker, fetch_user)
    legacy_refresh = create_user_refresh_token(user.id)

    client.cookies.set(settings.auth_refresh_cookie_name, legacy_refresh)
    first_refresh = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert first_refresh.status_code == 200

    client.cookies.set(settings.auth_refresh_cookie_name, legacy_refresh)
    replay_refresh = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert replay_refresh.status_code == 401

    async def inspect_session_state(session):
        result = await session.execute(select(AuthRefreshSession))
        return list(result.scalars())

    sessions = await run_in_session(async_session_maker, inspect_session_state)
    assert len(sessions) == 1


async def test_logout_all_revokes_all_refresh_sessions(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "logout-all@example.com",
        "name": "Logout All User",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }
    await client.post(f"{settings.api_v1_prefix}/auth/register", json=payload)

    first_login = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert first_login.status_code == 200
    first_cookie = client.cookies.get(settings.auth_refresh_cookie_name)
    assert first_cookie

    second_login = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert second_login.status_code == 200
    second_cookie = client.cookies.get(settings.auth_refresh_cookie_name)
    assert second_cookie and second_cookie != first_cookie

    async def fetch_user(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        return result.scalar_one()

    user = await run_in_session(async_session_maker, fetch_user)
    access_token = create_user_token(user.id)

    logout_all_response = await client.post(
        f"{settings.api_v1_prefix}/auth/logout-all",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_all_response.status_code == 204

    client.cookies.set(settings.auth_refresh_cookie_name, first_cookie)
    first_refresh = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert first_refresh.status_code == 401

    client.cookies.set(settings.auth_refresh_cookie_name, second_cookie)
    second_refresh = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert second_refresh.status_code == 401


async def test_logout_all_blocks_legacy_refresh_tokens(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "logout-all-legacy@example.com",
        "name": "Logout All Legacy User",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }
    await client.post(f"{settings.api_v1_prefix}/auth/register", json=payload)

    async def fetch_user(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        return result.scalar_one()

    user = await run_in_session(async_session_maker, fetch_user)
    legacy_refresh = create_user_refresh_token(user.id)
    access_token = create_user_token(user.id)

    logout_all_response = await client.post(
        f"{settings.api_v1_prefix}/auth/logout-all",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_all_response.status_code == 204

    client.cookies.set(settings.auth_refresh_cookie_name, legacy_refresh)
    refresh_response = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert refresh_response.status_code == 401


async def test_change_password_updates_credentials(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "changepw@example.com",
        "name": "Changer",
        "password": "InitPass!1",
        "timezone": "UTC",
    }
    register_response = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=payload
    )
    assert register_response.status_code == 201

    async def fetch_user(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        return result.scalar_one()

    user = await run_in_session(async_session_maker, fetch_user)
    token = create_user_token(user.id)
    login_response = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login_response.status_code == 200
    refresh_cookie = client.cookies.get(settings.auth_refresh_cookie_name)
    assert refresh_cookie

    change_response = await client.post(
        f"{settings.api_v1_prefix}/auth/password/change",
        json={
            "current_password": payload["password"],
            "new_password": "N3wPass!2",
            "new_password_confirm": "N3wPass!2",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert change_response.status_code == 200
    assert change_response.json()["message"] == "Password updated successfully"

    # Old password should no longer work
    failed_login = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert failed_login.status_code == 401

    client.cookies.set(settings.auth_refresh_cookie_name, refresh_cookie)
    refresh_after_password_change = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert refresh_after_password_change.status_code == 401

    # New password should authenticate
    success_login = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": payload["email"], "password": "N3wPass!2"},
    )
    assert success_login.status_code == 200


async def test_change_password_blocks_legacy_refresh_tokens(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "changepw-legacy@example.com",
        "name": "Legacy Changer",
        "password": "InitPass!1",
        "timezone": "UTC",
    }
    register_response = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=payload
    )
    assert register_response.status_code == 201

    async def fetch_user(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        return result.scalar_one()

    user = await run_in_session(async_session_maker, fetch_user)
    access_token = create_user_token(user.id)
    legacy_refresh = create_user_refresh_token(user.id)

    change_response = await client.post(
        f"{settings.api_v1_prefix}/auth/password/change",
        json={
            "current_password": payload["password"],
            "new_password": "N3wPass!2",
            "new_password_confirm": "N3wPass!2",
        },
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert change_response.status_code == 200

    client.cookies.set(settings.auth_refresh_cookie_name, legacy_refresh)
    refresh_response = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert refresh_response.status_code == 401


async def test_change_password_rejects_wrong_current_password(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "wrongcurrent@example.com",
        "name": "Wrong",
        "password": "InitPass!1",
    }
    await client.post(f"{settings.api_v1_prefix}/auth/register", json=payload)

    async def fetch_user(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        return result.scalar_one()

    user = await run_in_session(async_session_maker, fetch_user)
    token = create_user_token(user.id)

    response = await client.post(
        f"{settings.api_v1_prefix}/auth/password/change",
        json={
            "current_password": "BadPass!1",
            "new_password": "Another1!",
            "new_password_confirm": "Another1!",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert "Current password" in response.json()["detail"]


async def test_change_password_enforces_strength_rules(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "weak@example.com",
        "name": "Weak",
        "password": "InitPass!1",
    }
    await client.post(f"{settings.api_v1_prefix}/auth/register", json=payload)

    async def fetch_user(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        return result.scalar_one()

    user = await run_in_session(async_session_maker, fetch_user)
    token = create_user_token(user.id)

    response = await client.post(
        f"{settings.api_v1_prefix}/auth/password/change",
        json={
            "current_password": payload["password"],
            "new_password": "weakpass",
            "new_password_confirm": "weakpass",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert "Password must" in response.json()["detail"]


async def test_register_second_user_is_not_superuser(
    client: AsyncClient, async_session_maker
) -> None:
    first_payload = {
        "email": "first@example.com",
        "name": "First",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }
    second_payload = {
        "email": "second@example.com",
        "name": "Second",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }

    response_first = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=first_payload
    )
    assert response_first.status_code == 201

    async def seed_invitation(session):
        result = await session.execute(
            select(User).where(User.email == first_payload["email"])
        )
        creator = result.scalar_one()
        invitation = Invitation(
            code=uuid4().hex,
            creator_user_id=creator.id,
            target_email=second_payload["email"],
            status=InvitationStatus.PENDING,
        )
        session.add(invitation)
        await session.commit()
        await session.refresh(invitation)
        return invitation

    invitation = await run_in_session(async_session_maker, seed_invitation)

    second_with_invite = {**second_payload, "invite_code": invitation.code}
    response_second = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=second_with_invite
    )
    assert response_second.status_code == 201
    assert response_second.json()["is_superuser"] is False

    async def verify(session):
        result = await session.execute(
            select(Invitation).where(Invitation.id == invitation.id)
        )
        refreshed = result.scalar_one()
        return refreshed.status

    status = await run_in_session(async_session_maker, verify)
    assert status == InvitationStatus.REGISTERED


async def test_register_without_timezone_defaults_to_utc(  # type: ignore[no-untyped-def]
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "timezone@example.com",
        "name": "TZ",
        "password": "Str0ngPass!1",
    }

    response = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=payload
    )
    assert response.status_code == 201
    data = response.json()
    assert data["timezone"] == "UTC"

    async def fetch_user(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        return result.scalar_one()

    created = await run_in_session(async_session_maker, fetch_user)
    assert created.timezone == "UTC"


async def test_register_rejects_duplicate_email(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "require_invitation_for_registration", False)

    payload = {
        "email": "duplicate@example.com",
        "name": "Dup",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }
    first = await client.post(f"{settings.api_v1_prefix}/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post(f"{settings.api_v1_prefix}/auth/register", json=payload)
    assert second.status_code == 400
    assert second.json()["detail"] == "Email already registered"


async def test_register_requires_invitation_for_non_first_user(
    client: AsyncClient,
) -> None:
    first_payload = {
        "email": "admin@example.com",
        "name": "Admin",
        "password": "Str0ngPass!1",
    }
    response_first = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=first_payload
    )
    assert response_first.status_code == 201

    second_payload = {
        "email": "invitee@example.com",
        "name": "Invitee",
        "password": "Str0ngPass!1",
    }

    response = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=second_payload
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invitation code is required for registration"


async def test_register_with_invitation_revokes_other_codes(
    client: AsyncClient, async_session_maker
) -> None:
    admin_payload = {
        "email": "admin@example.com",
        "name": "Admin",
        "password": "Str0ngPass!1",
    }
    register_admin = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=admin_payload
    )
    assert register_admin.status_code == 201

    async def seed_admins(session):
        result = await session.execute(
            select(User).where(User.email == admin_payload["email"])
        )
        admin_user = result.scalar_one()
        other_admin = User(
            email="other-admin@example.com",
            name="Other Admin",
            password_hash=get_password_hash("AnotherStr0ng!1"),
            is_superuser=True,
        )
        session.add(other_admin)
        await session.commit()
        await session.refresh(other_admin)
        return admin_user, other_admin

    admin_user, other_admin = await run_in_session(async_session_maker, seed_admins)

    target_email = "target@example.com"

    primary_invitation = await _create_invitation(
        async_session_maker,
        creator_user_id=admin_user.id,
        target_email=target_email,
    )

    secondary_invitation = await _create_invitation(
        async_session_maker,
        creator_user_id=other_admin.id,
        target_email=target_email,
    )

    registration_payload = {
        "email": target_email,
        "name": "Target User",
        "password": "Str0ngPass!1",
        "invite_code": primary_invitation.code,
    }

    response = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=registration_payload
    )
    assert response.status_code == 201

    async def verify(session):
        prim_res = await session.execute(
            select(Invitation).where(Invitation.id == primary_invitation.id)
        )
        sec_res = await session.execute(
            select(Invitation).where(Invitation.id == secondary_invitation.id)
        )
        return prim_res.scalar_one(), sec_res.scalar_one()

    refreshed_primary, refreshed_secondary = await run_in_session(
        async_session_maker, verify
    )
    assert refreshed_primary.status == InvitationStatus.REGISTERED
    assert refreshed_primary.target_user_id is not None

    assert refreshed_secondary.status == InvitationStatus.REVOKED
    assert refreshed_secondary.deleted_at is not None


async def test_register_rejects_weak_password(client: AsyncClient) -> None:
    payload = {
        "email": "weak@example.com",
        "name": "Weak",
        "password": "weakpass",
        "timezone": "UTC",
    }

    response = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=payload
    )
    assert response.status_code == 400
    assert "Password" in response.json()["detail"]


async def test_authenticate_user_not_found_runs_dummy_hash_verification(
    async_db_session,
) -> None:
    password = "NotUsed!1"  # pragma: allowlist secret

    with patch(
        "app.features.auth.service.verify_password", return_value=False
    ) as verify_mock:
        with pytest.raises(auth_handler.UserNotFoundError, match="Invalid credentials"):
            await auth_handler.authenticate_user(
                async_db_session,
                email="missing@example.com",
                password=password,
            )

    verify_mock.assert_called_once_with(password, DUMMY_PASSWORD_HASH)


async def test_login_with_wrong_password_returns_unauthorized(
    client: AsyncClient,
) -> None:
    payload = {
        "email": "login-wrong@example.com",
        "name": "Login Wrong",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }
    await client.post(f"{settings.api_v1_prefix}/auth/register", json=payload)

    login_payload = {
        "email": payload["email"],
        "password": "incorrect",
    }

    response = await client.post(
        f"{settings.api_v1_prefix}/auth/login", json=login_payload
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


async def test_login_disabled_user_returns_unauthorized(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "disabled@example.com",
        "name": "Disabled",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }
    await client.post(f"{settings.api_v1_prefix}/auth/register", json=payload)

    async def disable_user(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        user = result.scalar_one()
        user.disabled_at = utc_now()
        await session.commit()

    await run_in_session(async_session_maker, disable_user)

    login_payload = {
        "email": payload["email"],
        "password": payload["password"],
    }
    response = await client.post(
        f"{settings.api_v1_prefix}/auth/login", json=login_payload
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


async def test_login_returns_user_timezone(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "tzuser@example.com",
        "name": "TZ User",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }
    await client.post(f"{settings.api_v1_prefix}/auth/register", json=payload)

    async def set_user_timezone(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        user = result.scalar_one()
        user.timezone = "Asia/Shanghai"
        await session.commit()

    await run_in_session(async_session_maker, set_user_timezone)

    login_payload = {
        "email": payload["email"],
        "password": payload["password"],
    }
    response = await client.post(
        f"{settings.api_v1_prefix}/auth/login", json=login_payload
    )
    assert response.status_code == 200
    assert response.json()["user"]["timezone"] == "Asia/Shanghai"


async def test_me_endpoint_returns_current_user(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "me@example.com",
        "name": "Me",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }
    await client.post(f"{settings.api_v1_prefix}/auth/register", json=payload)

    async def fetch_user(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        return result.scalar_one()

    user = await run_in_session(async_session_maker, fetch_user)
    token = create_user_token(user.id)

    response = await client.get(
        f"{settings.api_v1_prefix}/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == payload["email"]
    assert body["timezone"] == "UTC"


async def test_me_endpoint_rejects_missing_token(client: AsyncClient) -> None:
    response = await client.get(f"{settings.api_v1_prefix}/auth/me")
    assert response.status_code in {401, 403}


async def test_me_endpoint_rejects_disabled_user(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "me-disabled@example.com",
        "name": "Me Disabled",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }
    await client.post(f"{settings.api_v1_prefix}/auth/register", json=payload)

    async def disable(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        user = result.scalar_one()
        user.disabled_at = utc_now()
        user.password_hash = get_password_hash(payload["password"])
        await session.commit()
        return user.id

    user_id = await run_in_session(async_session_maker, disable)

    token = create_user_token(user_id)
    response = await client.get(
        f"{settings.api_v1_prefix}/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "User not found or disabled"


async def test_login_updates_last_login_and_resets_lock_state(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "activity@example.com",
        "name": "Activity",
        "password": "InitPass!1",
        "timezone": "UTC",
    }
    register_response = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=payload
    )
    assert register_response.status_code == 201

    login_response = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login_response.status_code == 200

    async def fetch_user_state(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        user = result.scalar_one()
        assert user.last_login_at is not None
        assert user.failed_login_attempts == 0
        assert user.locked_until is None
        return user

    await run_in_session(async_session_maker, fetch_user_state)


async def test_login_lockout_after_repeated_failures(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "lock@example.com",
        "name": "Lock",
        "password": "InitPass!1",
        "timezone": "UTC",
    }
    await client.post(f"{settings.api_v1_prefix}/auth/register", json=payload)

    for _ in range(settings.auth_max_failed_login_attempts):
        bad = await client.post(
            f"{settings.api_v1_prefix}/auth/login",
            json={"email": payload["email"], "password": "WrongPass!2"},
        )
        assert bad.status_code == 401

    locked = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert locked.status_code == 429

    async def inspect_lock(session):
        result = await session.execute(
            select(User).where(User.email == payload["email"])
        )
        user = result.scalar_one()
        assert user.locked_until is not None
        return user

    await run_in_session(async_session_maker, inspect_lock)


async def test_jwks_endpoint_exposes_active_key(client: AsyncClient) -> None:
    response = await client.get(f"{settings.api_v1_prefix}/auth/.well-known/jwks.json")
    assert response.status_code == 200
    body = response.json()
    assert body == build_jwks_document()
    assert body["keys"][0]["kid"] == settings.jwt_key_id


async def test_verify_refresh_token_claims_accepts_previous_key_without_kid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048
    )
    previous_public_key = (
        previous_private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    monkeypatch.setattr(
        settings,
        "jwt_previous_public_keys",
        [{"kid": "legacy-key", "public_key_pem": previous_public_key}],
    )

    now = utc_now()
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "typ": "refresh",
            "iss": settings.jwt_issuer,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "jti": uuid4().hex,
        },
        previous_private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8"),
        algorithm=settings.jwt_algorithm,
    )

    claims = verify_refresh_token_claims(token)
    assert claims is not None


async def test_get_client_ip_ignores_untrusted_forwarded_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "auth_trust_proxy_headers", False)
    monkeypatch.setattr(settings, "auth_trusted_proxy_ips", ["127.0.0.1"])

    request = _build_request(
        client_host="198.51.100.10",
        headers={"X-Forwarded-For": "203.0.113.9"},
    )

    assert get_client_ip(request) == "198.51.100.10"


async def test_get_client_ip_uses_forwarded_headers_for_trusted_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "auth_trust_proxy_headers", True)
    monkeypatch.setattr(
        settings,
        "auth_trusted_proxy_ips",
        ["198.51.100.0/24"],
    )

    request = _build_request(
        client_host="198.51.100.10",
        headers={"X-Forwarded-For": "203.0.113.9, 198.51.100.10"},
    )

    assert get_client_ip(request) == "203.0.113.9"


async def test_login_and_refresh_write_audit_events(
    client: AsyncClient, async_session_maker
) -> None:
    payload = {
        "email": "audit@example.com",
        "name": "Audit User",
        "password": "Str0ngPass!1",
        "timezone": "UTC",
    }
    register_response = await client.post(
        f"{settings.api_v1_prefix}/auth/register", json=payload
    )
    assert register_response.status_code == 201

    login_response = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login_response.status_code == 200

    refresh_response = await client.post(
        f"{settings.api_v1_prefix}/auth/refresh",
        headers={"Origin": TRUSTED_ORIGIN},
    )
    assert refresh_response.status_code == 200

    async def fetch_events(session):
        result = await session.execute(
            select(AuthAuditEvent).order_by(AuthAuditEvent.created_at.asc())
        )
        return list(result.scalars())

    events = await run_in_session(async_session_maker, fetch_events)
    event_types = [item.event_type for item in events]
    assert "login_success" in event_types
    assert "refresh_success" in event_types
