from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models.food import Food
from app.handlers import foods as food_service
from app.handlers.foods import (
    FoodAlreadyExistsError,
    FoodOperationNotAllowedError,
    FoodPermissionDeniedError,
)
from app.schemas.food import FoodCreate, FoodUpdate
from backend.tests.utils import create_food as create_food_helper
from backend.tests.utils import create_user

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


async def test_create_food_duplicate_name_raises(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    payload = FoodCreate(name="Oatmeal")
    await food_service.create_food(async_db_session, user_id=user.id, food_in=payload)

    with pytest.raises(FoodAlreadyExistsError):
        await food_service.create_food(
            async_db_session, user_id=user.id, food_in=payload
        )


async def test_get_food_permission_enforced(async_db_session):
    owner = await create_user(async_db_session, skip_onboarding_defaults=True)
    other_user = await create_user(async_db_session, skip_onboarding_defaults=True)
    food = await create_food_helper(async_db_session, user=owner, name="Private Food")

    with pytest.raises(FoodPermissionDeniedError):
        await food_service.get_food(
            async_db_session, user_id=other_user.id, food_id=food.id
        )


async def test_update_food_name_conflict(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    food_one = await create_food_helper(
        async_db_session, user=user, name="Protein Shake"
    )
    food_two = await create_food_helper(async_db_session, user=user, name="Smoothie")

    with pytest.raises(FoodAlreadyExistsError):
        await food_service.update_food(
            async_db_session,
            user_id=user.id,
            food_id=food_two.id,
            update_in=FoodUpdate(name=food_one.name),
        )


async def test_delete_food_requires_ownership(async_db_session):
    owner = await create_user(async_db_session, skip_onboarding_defaults=True)
    other_user = await create_user(async_db_session, skip_onboarding_defaults=True)
    food = await create_food_helper(async_db_session, user=owner, name="Family Recipe")

    with pytest.raises(FoodOperationNotAllowedError):
        await food_service.delete_food(
            async_db_session, user_id=other_user.id, food_id=food.id
        )

    await food_service.delete_food(async_db_session, user_id=owner.id, food_id=food.id)
    result = await async_db_session.execute(
        select(Food.deleted_at).where(Food.id == food.id)
    )
    assert result.scalar_one() is not None
