"""
Reduced tests for Person model custom behaviors.
"""

from uuid import uuid4

import pytest

from app.db.models.person import Person
from app.db.models.user import User

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _create_user(async_db_session) -> User:
    user = User(
        id=uuid4(),
        email="test@example.com",
        name="Test User",
        password_hash="hashed_password",
    )
    async_db_session.add(user)
    await async_db_session.flush()
    return user


async def test_person_display_name_with_name(async_db_session):
    user = await _create_user(async_db_session)
    person = Person(id=uuid4(), user_id=user.id, name="John Doe")
    async_db_session.add(person)
    await async_db_session.commit()

    assert person.display_name == "John Doe"


async def test_person_display_name_without_name(async_db_session):
    user = await _create_user(async_db_session)
    person = Person(id=uuid4(), user_id=user.id)
    async_db_session.add(person)
    await async_db_session.commit()

    assert person.display_name == f"Person #{person.id}"


async def test_person_primary_nickname_with_nicknames(async_db_session):
    user = await _create_user(async_db_session)
    person = Person(
        id=uuid4(),
        user_id=user.id,
        name="John Doe",
        nicknames=["Johnny", "JD"],
    )
    async_db_session.add(person)
    await async_db_session.commit()

    assert person.get_primary_nickname() == "Johnny, JD"


async def test_person_primary_nickname_without_nicknames(async_db_session):
    user = await _create_user(async_db_session)
    person = Person(id=uuid4(), user_id=user.id, name="John Doe")
    async_db_session.add(person)
    await async_db_session.commit()

    assert person.get_primary_nickname() == "John Doe"


async def test_person_primary_nickname_anonymous(async_db_session):
    user = await _create_user(async_db_session)
    person = Person(id=uuid4(), user_id=user.id)
    async_db_session.add(person)
    await async_db_session.commit()

    assert person.get_primary_nickname() == f"Person #{person.id}"


async def test_person_add_nickname_dedupes(async_db_session):
    user = await _create_user(async_db_session)
    person = Person(id=uuid4(), user_id=user.id, name="John Doe", nicknames=["JD"])
    async_db_session.add(person)
    await async_db_session.commit()

    person.add_nickname("JD")
    person.add_nickname("Johnny")
    await async_db_session.commit()
    await async_db_session.refresh(person)

    assert person.nicknames == ["JD", "Johnny"]


async def test_person_remove_nickname(async_db_session):
    user = await _create_user(async_db_session)
    person = Person(
        id=uuid4(),
        user_id=user.id,
        name="John Doe",
        nicknames=["JD", "Johnny"],
    )
    async_db_session.add(person)
    await async_db_session.commit()

    person.remove_nickname("JD")
    await async_db_session.commit()
    await async_db_session.refresh(person)

    assert person.nicknames == ["Johnny"]


async def test_person_soft_delete_and_restore(async_db_session):
    user = await _create_user(async_db_session)
    person = Person(id=uuid4(), user_id=user.id, name="John Doe")
    async_db_session.add(person)
    await async_db_session.commit()

    person.soft_delete()
    await async_db_session.commit()
    assert person.is_deleted is True

    person.restore()
    await async_db_session.commit()
    assert person.is_deleted is False
