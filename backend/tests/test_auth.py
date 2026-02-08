from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.api.routers import auth as auth_router
from app.core.config import settings
from app.core.security import create_user_token, get_password_hash
from app.db.models.user import User
from app.db.models.user_activity import UserActivity
from app.utils.timezone_util import utc_now
from backend.tests.api_utils import create_test_client
from backend.tests.utils import DEFAULT_TEST_PASSWORD, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def run_in_session(async_session_maker, coro_fn):
    async with async_session_maker() as session:
        return await coro_fn(session)


@pytest_asyncio.fixture()
async def client(async_session_maker, async_db_session) -> AsyncClient:
    async with create_test_client(
        auth_router.router,
        async_session_maker=async_session_maker,
        base_prefix=settings.api_v1_prefix,
    ) as test_client:
        yield test_client


async def _seed_user(async_session_maker, *, email: str, password: str) -> User:
    async def inserter(session):
        return await create_user(
            session, email=email, password=password, timezone="UTC"
        )

    return await run_in_session(async_session_maker, inserter)


async def test_login_returns_access_token_and_user_profile(
    client: AsyncClient, async_session_maker
) -> None:
    email = "test@example.com"
    password = "Str0ngPass!1"
    await _seed_user(async_session_maker, email=email, password=password)

    response = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": email, "password": password},
    )

    assert response.status_code == 200
    payload = response.json()
    assert UUID(payload["user"]["id"])
    assert payload["user"]["email"] == email
    assert payload["access_token"]
    assert payload["token_type"] == "bearer"
    assert payload["expires_in"] == settings.jwt_access_token_ttl_seconds


async def test_login_sets_refresh_cookie(
    client: AsyncClient, async_session_maker
) -> None:
    email = "cookie@example.com"
    await _seed_user(async_session_maker, email=email, password=DEFAULT_TEST_PASSWORD)

    response = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": email, "password": DEFAULT_TEST_PASSWORD},
    )
    assert response.status_code == 200

    set_cookie_headers = response.headers.get_list("set-cookie")
    assert any(
        header.startswith(f"{settings.auth_refresh_cookie_name}=")
        for header in set_cookie_headers
    )
    assert any("HttpOnly" in header for header in set_cookie_headers)
    assert client.cookies.get(settings.auth_refresh_cookie_name)


async def test_refresh_rotates_cookie_and_returns_new_access_token(
    client: AsyncClient, async_session_maker
) -> None:
    email = "refresh@example.com"
    await _seed_user(async_session_maker, email=email, password=DEFAULT_TEST_PASSWORD)

    login_response = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": email, "password": DEFAULT_TEST_PASSWORD},
    )
    assert login_response.status_code == 200

    before = client.cookies.get(settings.auth_refresh_cookie_name)
    assert before

    refresh_response = await client.post(f"{settings.api_v1_prefix}/auth/refresh")
    assert refresh_response.status_code == 200, refresh_response.text
    payload = refresh_response.json()
    assert payload["access_token"]
    assert payload["token_type"] == "bearer"
    assert payload["expires_in"] == settings.jwt_access_token_ttl_seconds

    after = client.cookies.get(settings.auth_refresh_cookie_name)
    assert after
    assert after != before


async def test_logout_clears_refresh_cookie(
    client: AsyncClient, async_session_maker
) -> None:
    email = "logout@example.com"
    await _seed_user(async_session_maker, email=email, password=DEFAULT_TEST_PASSWORD)

    login = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": email, "password": DEFAULT_TEST_PASSWORD},
    )
    assert login.status_code == 200
    assert client.cookies.get(settings.auth_refresh_cookie_name)

    logout = await client.post(f"{settings.api_v1_prefix}/auth/logout")
    assert logout.status_code == 204
    assert client.cookies.get(settings.auth_refresh_cookie_name) in {None, ""}


async def test_login_with_wrong_password_returns_unauthorized(
    client: AsyncClient, async_session_maker
) -> None:
    email = "login-wrong@example.com"
    await _seed_user(async_session_maker, email=email, password=DEFAULT_TEST_PASSWORD)

    response = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": email, "password": "incorrect"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


async def test_login_disabled_user_returns_unauthorized(
    client: AsyncClient, async_session_maker
) -> None:
    email = "disabled@example.com"
    user = await _seed_user(
        async_session_maker, email=email, password=DEFAULT_TEST_PASSWORD
    )

    async def disable_user(session):
        user_in_db = await session.get(User, user.id)
        assert user_in_db is not None
        user_in_db.disabled_at = utc_now()
        await session.commit()

    await run_in_session(async_session_maker, disable_user)

    response = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": email, "password": DEFAULT_TEST_PASSWORD},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


async def test_me_endpoint_returns_current_user(
    client: AsyncClient, async_session_maker
) -> None:
    email = "me@example.com"
    user = await _seed_user(
        async_session_maker, email=email, password=DEFAULT_TEST_PASSWORD
    )
    token = create_user_token(user.id)

    response = await client.get(
        f"{settings.api_v1_prefix}/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == email
    assert body["timezone"] == "UTC"


async def test_me_endpoint_rejects_missing_token(client: AsyncClient) -> None:
    response = await client.get(f"{settings.api_v1_prefix}/auth/me")
    assert response.status_code in {401, 403}


async def test_me_endpoint_rejects_disabled_user(
    client: AsyncClient, async_session_maker
) -> None:
    email = "me-disabled@example.com"
    user = await _seed_user(
        async_session_maker, email=email, password=DEFAULT_TEST_PASSWORD
    )

    async def disable(session):
        user_in_db = await session.get(User, user.id)
        assert user_in_db is not None
        user_in_db.disabled_at = utc_now()
        user_in_db.password_hash = get_password_hash(DEFAULT_TEST_PASSWORD)
        await session.commit()
        return user_in_db.id

    user_id = await run_in_session(async_session_maker, disable)

    token = create_user_token(user_id)
    response = await client.get(
        f"{settings.api_v1_prefix}/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "User not found or disabled"


async def test_login_records_activity_and_last_login(
    client: AsyncClient, async_session_maker
) -> None:
    email = "activity@example.com"
    await _seed_user(async_session_maker, email=email, password=DEFAULT_TEST_PASSWORD)

    login_response = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": email, "password": DEFAULT_TEST_PASSWORD},
    )
    assert login_response.status_code == 200

    async def fetch_activity(session):
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        assert user.last_login_at is not None
        assert user.failed_login_attempts == 0
        assert user.locked_until is None
        activity_result = await session.execute(
            select(UserActivity).where(
                UserActivity.user_id == user.id,
                UserActivity.event_type == "auth.login",
            )
        )
        return activity_result.scalars().all()

    activities = await run_in_session(async_session_maker, fetch_activity)
    assert any(activity.status == "success" for activity in activities)


async def test_login_lockout_after_repeated_failures(
    client: AsyncClient, async_session_maker
) -> None:
    email = "lock@example.com"
    await _seed_user(async_session_maker, email=email, password=DEFAULT_TEST_PASSWORD)

    for _ in range(settings.auth_max_failed_login_attempts):
        bad = await client.post(
            f"{settings.api_v1_prefix}/auth/login",
            json={"email": email, "password": "WrongPass!2"},
        )
        assert bad.status_code == 401

    locked = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": email, "password": DEFAULT_TEST_PASSWORD},
    )
    assert locked.status_code == 429

    async def inspect_lock(session):
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        assert user.locked_until is not None
        events_result = await session.execute(
            select(UserActivity)
            .where(
                UserActivity.user_id == user.id,
                UserActivity.event_type == "auth.login",
            )
            .order_by(UserActivity.created_at.asc())
        )
        return events_result.scalars().all()

    events = await run_in_session(async_session_maker, inspect_lock)
    assert any(event.status == "blocked" for event in events)
