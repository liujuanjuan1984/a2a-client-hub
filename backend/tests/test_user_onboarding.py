from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models.dimension import Dimension
from app.db.models.user import User
from app.db.models.user_preference import UserPreference
from app.db.models.vision import Vision
from app.handlers.user_onboarding import UserOnboardingService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


async def _create_user(async_db_session, email: str) -> User:
    user = User(email=email, name="Onboarding User", password_hash="test-hash")
    async_db_session.add(user)
    await async_db_session.commit()
    await async_db_session.refresh(user)
    return user


async def _list_dimensions(async_db_session, user_id):
    stmt = (
        select(Dimension)
        .where(Dimension.user_id == user_id)
        .order_by(Dimension.display_order.asc(), Dimension.created_at.asc())
    )
    result = await async_db_session.execute(stmt)
    return result.scalars().all()


async def test_onboarding_creates_default_dimensions_and_order(async_db_session):
    user = await _create_user(async_db_session, "onboarding-default@example.com")

    await UserOnboardingService.create_default_data_for_user(async_db_session, user)

    dimensions = await _list_dimensions(async_db_session, user.id)
    assert len(dimensions) == 9

    expected_names = [
        "Health",
        "Growth",
        "Family",
        "Work",
        "Wealth",
        "Relationships",
        "Leisure",
        "Contribution",
        "Other",
    ]
    assert [dimension.name for dimension in dimensions] == expected_names

    pref_stmt = select(UserPreference).where(
        UserPreference.user_id == user.id,
        UserPreference.key == "dashboard.dimension_order",
        UserPreference.deleted_at.is_(None),
    )
    order_preference = (await async_db_session.execute(pref_stmt)).scalars().first()
    assert order_preference is not None
    assert order_preference.value == [str(dimension.id) for dimension in dimensions]

    # Idempotent when called repeatedly
    await UserOnboardingService.create_default_data_for_user(async_db_session, user)
    dimensions_again = await _list_dimensions(async_db_session, user.id)
    assert len(dimensions_again) == 9
    assert [dimension.id for dimension in dimensions_again] == [
        dimension.id for dimension in dimensions
    ]


async def test_onboarding_respects_language_preference(async_db_session):
    user = await _create_user(async_db_session, "onboarding-locale@example.com")
    async_db_session.add(
        UserPreference(
            user_id=user.id,
            key="system.language",
            value="zh",
            module="system",
        )
    )
    await async_db_session.commit()

    await UserOnboardingService.create_default_data_for_user(async_db_session, user)
    dimensions = await _list_dimensions(async_db_session, user.id)
    names = {dimension.name for dimension in dimensions}

    assert "健康" in names
    assert "Health" not in names


async def test_onboarding_sets_default_inbox_vision_preference(async_db_session):
    user = await _create_user(async_db_session, "onboarding-default-vision@example.com")

    await UserOnboardingService.create_default_data_for_user(async_db_session, user)

    vision_stmt = select(Vision).where(
        Vision.user_id == user.id,
        Vision.name == "Todos Inbox",
        Vision.deleted_at.is_(None),
    )
    inbox_vision = (await async_db_session.execute(vision_stmt)).scalars().first()

    assert inbox_vision is not None

    pref_stmt = select(UserPreference).where(
        UserPreference.user_id == user.id,
        UserPreference.key == "todos.default_inbox_vision",
        UserPreference.deleted_at.is_(None),
    )
    preference = (await async_db_session.execute(pref_stmt)).scalars().first()

    assert preference is not None
    assert preference.value == str(inbox_vision.id)
