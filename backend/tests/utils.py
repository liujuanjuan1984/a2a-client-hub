from __future__ import annotations

from typing import Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.db.models.user import User
from app.db.models.user_preference import UserPreference

DEFAULT_TEST_PASSWORD = "Password123!"


async def create_user(
    session: AsyncSession,
    email: Optional[str] = None,
    name: str = "Test User",
    *,
    is_superuser: bool = False,
    password: Optional[str] = None,
    timezone: str = "UTC",
    skip_onboarding_defaults: bool = False,
) -> User:
    # `skip_onboarding_defaults` is kept for backward compatibility with the
    # upstream test suite. The A2A client backend cut does not run onboarding.
    _ = skip_onboarding_defaults

    user = User(
        email=email or f"user_{uuid4().hex[:8]}@example.com",
        name=name,
        password_hash=get_password_hash(password or DEFAULT_TEST_PASSWORD),
        is_superuser=is_superuser,
    )
    session.add(user)
    await session.flush()

    session.add(
        UserPreference(
            user_id=user.id,
            key="system.timezone",
            value=timezone,
            module="system",
        )
    )
    await session.commit()
    await session.refresh(user)
    return user
