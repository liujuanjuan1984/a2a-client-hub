from __future__ import annotations

import pytest

from app.handlers import user_preferences as user_preferences_service
from app.handlers.dimensions import (
    DimensionAlreadyExistsError,
    activate_dimension,
    create_dimension,
    get_dimension_order,
    list_dimensions,
    reset_dimension_order,
    set_dimension_order,
    soft_delete_dimension,
    update_dimension,
)
from app.schemas.dimension import DimensionCreate, DimensionUpdate
from backend.tests.utils import create_user

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


async def _create_dimension(
    session,
    user,
    *,
    name: str,
    color: str = "#123456",
    is_active: bool = True,
):
    return await create_dimension(
        session,
        user_id=user.id,
        dimension_in=DimensionCreate(name=name, color=color, is_active=is_active),
    )


async def test_create_dimension_appends_to_order(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dim_input = DimensionCreate(name="Focus", color="#123456")
    dimension = await create_dimension(
        async_db_session, user_id=user.id, dimension_in=dim_input
    )

    preference = await get_dimension_order(async_db_session, user_id=user.id)
    assert preference is not None
    assert str(dimension.id) in preference.value


async def test_update_dimension_name_conflict_raises(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dim_a = await _create_dimension(async_db_session, user, name="Work")
    dim_b = await _create_dimension(async_db_session, user, name="Health")

    with pytest.raises(DimensionAlreadyExistsError):
        await update_dimension(
            async_db_session,
            user_id=user.id,
            dimension_id=dim_b.id,
            update_in=DimensionUpdate(name=dim_a.name),
        )


async def test_list_dimensions_respects_inactive_flag(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    active_dim = await _create_dimension(async_db_session, user, name="Active")
    inactive_dim = await _create_dimension(async_db_session, user, name="Inactive")

    await soft_delete_dimension(
        async_db_session, user_id=user.id, dimension_id=inactive_dim.id
    )

    results_active_only = await list_dimensions(async_db_session, user_id=user.id)
    assert [dim.id for dim in results_active_only] == [active_dim.id]

    results_all = await list_dimensions(
        async_db_session, user_id=user.id, include_inactive=True
    )
    assert {dim.id for dim in results_all} == {active_dim.id, inactive_dim.id}


async def test_activate_dimension_restores_inactive(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await _create_dimension(async_db_session, user, name="Projects")
    await soft_delete_dimension(
        async_db_session, user_id=user.id, dimension_id=dimension.id
    )

    reactivated = await activate_dimension(
        async_db_session, user_id=user.id, dimension_id=dimension.id
    )
    assert reactivated is not None
    assert reactivated.is_active is True

    preference = await get_dimension_order(async_db_session, user_id=user.id)
    assert preference is not None
    assert str(dimension.id) in preference.value


async def test_set_dimension_order_normalizes_values(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dim_one = await _create_dimension(async_db_session, user, name="One")
    dim_two = await _create_dimension(async_db_session, user, name="Two")

    await reset_dimension_order(async_db_session, user_id=user.id)
    await set_dimension_order(
        async_db_session,
        user_id=user.id,
        dimension_order=[str(dim_two.id), str(dim_one.id), "invalid"],
    )

    preference = await user_preferences_service.get_preference_by_key(
        async_db_session, user_id=user.id, key="dashboard.dimension_order"
    )
    assert preference is not None
    assert preference.value == [str(dim_two.id), str(dim_one.id)]


async def test_create_dimension_preserves_existing_order(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    first_dimension = await create_dimension(
        async_db_session,
        user_id=user.id,
        dimension_in=DimensionCreate(name="Focus", color="#111111"),
    )

    # Creating a second dimension should append without dropping the first UUID
    second_dimension = await create_dimension(
        async_db_session,
        user_id=user.id,
        dimension_in=DimensionCreate(name="Health", color="#222222"),
    )

    preference = await get_dimension_order(async_db_session, user_id=user.id)
    assert preference is not None
    assert preference.value == [
        str(first_dimension.id),
        str(second_dimension.id),
    ]


async def test_soft_delete_dimension_removes_uuid_from_order(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dim_keep = await create_dimension(
        async_db_session,
        user_id=user.id,
        dimension_in=DimensionCreate(name="Keep", color="#aaaaaa"),
    )
    dim_remove = await create_dimension(
        async_db_session,
        user_id=user.id,
        dimension_in=DimensionCreate(name="Remove", color="#bbbbbb"),
    )

    # Soft delete should remove only the targeted UUID from preference order
    await soft_delete_dimension(
        async_db_session, user_id=user.id, dimension_id=dim_remove.id
    )

    preference = await get_dimension_order(async_db_session, user_id=user.id)
    assert preference is not None
    assert preference.value == [str(dim_keep.id)]
