from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.db.models.user import User
from app.handlers import user_preferences as user_preferences_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


async def _create_user(async_db_session) -> User:
    user = User(
        email="preferences@example.com",
        name="Preferences Tester",
        password_hash="hash",
        is_superuser=False,
    )
    async_db_session.add(user)
    await async_db_session.commit()
    await async_db_session.refresh(user)
    return user


async def test_set_preference_value_saves_timezone(async_db_session):
    persisted_user = await _create_user(async_db_session)
    await user_preferences_service.set_preference_value(
        async_db_session,
        user_id=persisted_user.id,
        key="system.timezone",
        value="Europe/Berlin",
        module="system",
    )
    preference = await user_preferences_service.get_preference_by_key(
        async_db_session, user_id=persisted_user.id, key="system.timezone"
    )
    assert preference is not None
    assert preference.value == "Europe/Berlin"


async def test_set_preference_value_rejects_invalid_timezone(async_db_session):
    persisted_user = await _create_user(async_db_session)
    with pytest.raises(HTTPException):
        await user_preferences_service.set_preference_value(
            async_db_session,
            user_id=persisted_user.id,
            key="system.timezone",
            value="Mars/Phobos",
            module="system",
        )

    preference = await user_preferences_service.get_preference_by_key(
        async_db_session, user_id=persisted_user.id, key="system.timezone"
    )
    assert preference is None

    timezone_value = await user_preferences_service.get_preference_value(
        async_db_session,
        user_id=persisted_user.id,
        key="system.timezone",
        default="UTC",
    )
    assert timezone_value == "UTC"


async def test_navigation_visible_modules_normalizes_list(async_db_session):
    persisted_user = await _create_user(async_db_session)
    custom_list = ["notes", "unknown", "habits", "notes", "agent"]
    await user_preferences_service.set_preference_value(
        async_db_session,
        user_id=persisted_user.id,
        key="navigation.visible_modules",
        value=custom_list,
        module="navigation",
    )

    preference = await user_preferences_service.get_preference_by_key(
        async_db_session,
        user_id=persisted_user.id,
        key="navigation.visible_modules",
    )

    assert preference is not None
    assert preference.value == ["notes", "habits", "agent"]


async def test_navigation_visible_modules_invalid_input_falls_back_to_default(
    async_db_session,
):
    persisted_user = await _create_user(async_db_session)
    await user_preferences_service.set_preference_value(
        async_db_session,
        user_id=persisted_user.id,
        key="navigation.visible_modules",
        value="invalid",  # type: ignore[arg-type]
        module="navigation",
    )

    preference = await user_preferences_service.get_preference_by_key(
        async_db_session,
        user_id=persisted_user.id,
        key="navigation.visible_modules",
    )

    assert preference is not None
    assert "agent" in preference.value


async def test_notes_collapse_preference_defaults(async_db_session):
    persisted_user = await _create_user(async_db_session)
    preference = await user_preferences_service.get_preference_by_key(
        async_db_session,
        user_id=persisted_user.id,
        key="notes.card_min_collapsed_lines",
    )

    assert preference is None
    value = await user_preferences_service.get_preference_value(
        async_db_session,
        user_id=persisted_user.id,
        key="notes.card_min_collapsed_lines",
        default=5,
    )
    assert value == 5


async def test_todos_default_inbox_vision_allows_none(async_db_session):
    persisted_user = await _create_user(async_db_session)
    preference = await user_preferences_service.get_preference_by_key(
        async_db_session,
        user_id=persisted_user.id,
        key="todos.default_inbox_vision",
    )

    assert preference is None
    value = await user_preferences_service.get_preference_value(
        async_db_session,
        user_id=persisted_user.id,
        key="todos.default_inbox_vision",
        default=None,
    )
    assert value is None
