"""
Tests for Person Handlers

This module tests the person business logic handlers including:
- CRUD operations (create, read, update, delete)
- Person search and filtering
- Tag associations
- Anniversary management
- Person activity timeline
- Nickname management
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.db.models.anniversary import Anniversary
from app.db.models.association import Association
from app.db.models.note import Note
from app.db.models.person import Person
from app.db.models.tag import Tag
from app.db.models.task import Task
from app.db.models.user import User
from app.db.models.vision import Vision
from app.handlers import persons as persons_service
from app.handlers.associations import LinkType, ModelName
from app.handlers.persons import (
    AnniversaryNotFoundError,
    PersonAlreadyExistsError,
    PersonNotFoundError,
    TagNotFoundError,
)
from app.schemas.person import (
    AnniversaryCreate,
    AnniversaryUpdate,
    PersonCreate,
    PersonUpdate,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


class TestPersonHandlers:
    """Test cases for Person handler functions"""

    async def test_create_person_basic(self, async_db_session):
        """Test basic person creation"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        person_data = PersonCreate(
            name="John Doe", birth_date=date(1990, 5, 15), location="New York, USA"
        )

        person = await persons_service.create_person(
            async_db_session, user_id=user.id, person_in=person_data
        )

        assert person.id is not None
        assert person.name == "John Doe"
        assert person.birth_date == date(1990, 5, 15)
        assert person.location == "New York, USA"
        assert person.user_id == user.id
        assert person.created_at is not None

    async def test_create_person_with_all_fields(self, async_db_session):
        """Test creating person with all fields including tags"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="friend", entity_type="person")
        async_db_session.add(tag)
        await async_db_session.commit()

        person_data = PersonCreate(
            name="Jane Smith",
            nicknames=["Jane", "Janey", "JS"],
            birth_date=date(1985, 8, 20),
            location="Los Angeles, CA",
            tag_ids=[str(tag.id)],
        )

        person = await persons_service.create_person(
            async_db_session, user_id=user.id, person_in=person_data
        )

        assert person.name == "Jane Smith"
        assert person.nicknames == ["Jane", "Janey", "JS"]
        assert person.birth_date == date(1985, 8, 20)
        assert person.location == "Los Angeles, CA"
        assert len(person.tags) == 1
        assert person.tags[0].name == "friend"

    async def test_create_person_minimal(self, async_db_session):
        """Test creating person with minimal data"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        person_data = PersonCreate()  # No fields provided

        person = await persons_service.create_person(
            async_db_session, user_id=user.id, person_in=person_data
        )

        assert person.id is not None
        assert person.name is None
        assert person.nicknames is None
        assert person.birth_date is None
        assert person.location is None

    async def test_create_person_with_invalid_tags(self, async_db_session):
        """Test creating person with invalid tag IDs"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        person_data = PersonCreate(
            name="Test Person",
            tag_ids=[str(uuid4()), str(uuid4())],  # Non-existent tag IDs
        )

        with pytest.raises(TagNotFoundError):
            await persons_service.create_person(
                async_db_session, user_id=user.id, person_in=person_data
            )

    async def test_create_person_whitespace_handling(self, async_db_session):
        """Test person creation with content that needs trimming"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        person_data = PersonCreate(
            name="  John Doe  ",
            location="  New York, USA  ",
            nicknames=["  Johnny  ", "  JD  "],
        )

        person = await persons_service.create_person(
            async_db_session, user_id=user.id, person_in=person_data
        )

        # Schema validation should trim whitespace
        assert person.name == "John Doe"
        assert person.location == "New York, USA"
        assert person.nicknames == ["Johnny", "JD"]

    async def test_get_person(self, async_db_session):
        """Test getting a specific person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.commit()

        retrieved_person = await persons_service.get_person(
            async_db_session, user_id=user.id, person_id=person.id
        )

        assert retrieved_person is not None
        assert retrieved_person.id == person.id
        assert retrieved_person.name == "Test Person"

    async def test_get_person_not_found(self, async_db_session):
        """Test getting non-existent person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        result = await persons_service.get_person(
            async_db_session, user_id=user.id, person_id=uuid4()
        )
        assert result is None

    async def test_get_person_soft_deleted(self, async_db_session):
        """Test getting a soft deleted person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.commit()

        # Soft delete the person
        person.soft_delete()
        await async_db_session.commit()

        # Should not find the soft deleted person
        result = await persons_service.get_person(
            async_db_session, user_id=user.id, person_id=person.id
        )
        assert result is None

    async def test_list_persons_basic(self, async_db_session):
        """Test basic person listing"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Create multiple persons
        persons = []
        for i in range(3):
            person = Person(
                id=uuid4(), user_id=user.id, name=f"Person {chr(65 + i)}"  # A, B, C
            )
            persons.append(person)
        async_db_session.add_all(persons)
        await async_db_session.commit()

        result_persons, total = await persons_service.list_persons(
            async_db_session, user_id=user.id
        )

        assert len(result_persons) == 3
        assert total == 3
        assert all(person.user_id == user.id for person in result_persons)
        # Verify that tags relationship is loaded (even if empty)
        assert all(hasattr(person, "tags") for person in result_persons)

    async def test_list_persons_with_pagination(self, async_db_session):
        """Test person listing with pagination"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Create more persons than will fit in one page
        persons = []
        for i in range(5):
            person = Person(id=uuid4(), user_id=user.id, name=f"Person {i+1}")
            persons.append(person)
        async_db_session.add_all(persons)
        await async_db_session.commit()

        # Test pagination
        page1, total1 = await persons_service.list_persons(
            async_db_session, user_id=user.id, skip=0, limit=2
        )
        page2, total2 = await persons_service.list_persons(
            async_db_session, user_id=user.id, skip=2, limit=2
        )
        page3, total3 = await persons_service.list_persons(
            async_db_session, user_id=user.id, skip=4, limit=2
        )

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1
        assert total1 == total2 == total3 == 5

        # Ensure no overlaps
        page1_ids = {p.id for p in page1}
        page2_ids = {p.id for p in page2}
        page3_ids = {p.id for p in page3}

        assert len(page1_ids.intersection(page2_ids)) == 0
        assert len(page2_ids.intersection(page3_ids)) == 0
        assert len(page1_ids.intersection(page3_ids)) == 0

    async def test_list_persons_with_search(self, async_db_session):
        """Test person listing with search functionality"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person1 = Person(id=uuid4(), user_id=user.id, name="John Smith")
        person2 = Person(
            id=uuid4(), user_id=user.id, name="Jane Doe", nicknames=["Janey"]
        )
        person3 = Person(id=uuid4(), user_id=user.id, name="Bob Johnson")
        async_db_session.add_all([person1, person2, person3])
        await async_db_session.commit()

        # Search by name
        john_results, total = await persons_service.list_persons(
            async_db_session, user_id=user.id, search="john smith"
        )
        assert len(john_results) == 1
        assert john_results[0].name == "John Smith"

        # Search by nickname
        janey_results, total = await persons_service.list_persons(
            async_db_session, user_id=user.id, search="janey"
        )
        assert len(janey_results) == 1
        assert janey_results[0].name == "Jane Doe"

        # Search with partial match
        smith_results, total = await persons_service.list_persons(
            async_db_session, user_id=user.id, search="smith"
        )
        assert len(smith_results) == 1
        assert smith_results[0].name == "John Smith"

    async def test_list_persons_with_tag_filter(self, async_db_session):
        """Test listing persons with tag filter"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        friend_tag = Tag(
            id=uuid4(), user_id=user.id, name="friend", entity_type="person"
        )
        work_tag = Tag(id=uuid4(), user_id=user.id, name="work", entity_type="person")
        async_db_session.add_all([friend_tag, work_tag])
        await async_db_session.commit()

        person1 = Person(id=uuid4(), user_id=user.id, name="Friend Person")
        person2 = Person(id=uuid4(), user_id=user.id, name="Work Colleague")
        async_db_session.add_all([person1, person2])
        await async_db_session.commit()

        await persons_service.add_tag_to_person(
            async_db_session,
            user_id=user.id,
            person_id=person1.id,
            tag_id=friend_tag.id,
        )
        await persons_service.add_tag_to_person(
            async_db_session,
            user_id=user.id,
            person_id=person2.id,
            tag_id=work_tag.id,
        )

        # Filter by tag
        friend_results, total = await persons_service.list_persons(
            async_db_session, user_id=user.id, tag_filter="friend"
        )
        assert len(friend_results) == 1
        assert friend_results[0].name == "Friend Person"
        # Verify that tags are still loaded correctly
        assert len(friend_results[0].tags) == 1
        assert friend_results[0].tags[0].name == "friend"

    async def test_search_persons_by_tag_id(self, async_db_session):
        """Test searching persons by tag ID"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="family", entity_type="person")
        person = Person(id=uuid4(), user_id=user.id, name="Family Member")
        async_db_session.add_all([tag, person])
        await async_db_session.commit()

        # Add tag association

        await persons_service.add_tag_to_person(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            tag_id=tag.id,
        )

        results = await persons_service.search_persons_by_tag(
            async_db_session, user_id=user.id, tag_id=tag.id
        )

        assert len(results) == 1
        assert results[0].id == person.id
        assert results[0].name == "Family Member"

    async def test_search_persons_by_tag_name(self, async_db_session):
        """Test searching persons by tag name"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="colleague", entity_type="person")
        person = Person(id=uuid4(), user_id=user.id, name="Work Colleague")
        async_db_session.add_all([tag, person])
        await async_db_session.commit()

        await persons_service.add_tag_to_person(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            tag_id=tag.id,
        )

        results = await persons_service.search_persons_by_tag(
            async_db_session, user_id=user.id, tag_name="colleague"
        )

        assert len(results) == 1
        assert results[0].id == person.id
        assert results[0].name == "Work Colleague"

    async def test_search_persons_by_nonexistent_tag(self, async_db_session):
        """Test searching persons by non-existent tag"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        # Search by non-existent tag ID
        with pytest.raises(TagNotFoundError):
            await persons_service.search_persons_by_tag(
                async_db_session, user_id=user.id, tag_id=uuid4()
            )

        # Search by non-existent tag name
        with pytest.raises(TagNotFoundError):
            await persons_service.search_persons_by_tag(
                async_db_session, user_id=user.id, tag_name="nonexistent"
            )

    async def test_update_person_basic(self, async_db_session):
        """Test updating a person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(
            id=uuid4(),
            user_id=user.id,
            name="Original Name",
            location="Original Location",
        )
        async_db_session.add(person)
        await async_db_session.commit()

        update_data = PersonUpdate(
            name="Updated Name",
            birth_date=date(1990, 6, 15),
            location="Updated Location",
        )

        updated_person = await persons_service.update_person(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            update_in=update_data,
        )

        assert updated_person.name == "Updated Name"
        assert updated_person.birth_date == date(1990, 6, 15)
        assert updated_person.location == "Updated Location"

    async def test_update_person_not_found(self, async_db_session):
        """Test updating non-existent person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        update_data = PersonUpdate(name="Updated Name")

        result = await persons_service.update_person(
            async_db_session, user_id=user.id, person_id=uuid4(), update_in=update_data
        )
        assert result is None

    async def test_update_person_with_tags(self, async_db_session):
        """Test updating person with tags"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag1 = Tag(id=uuid4(), user_id=user.id, name="friend", entity_type="person")
        tag2 = Tag(id=uuid4(), user_id=user.id, name="colleague", entity_type="person")
        async_db_session.add_all([tag1, tag2])
        await async_db_session.commit()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.commit()

        # Update with tags
        update_data = PersonUpdate(
            name="Updated Person", tag_ids=[str(tag1.id), str(tag2.id)]
        )

        updated_person = await persons_service.update_person(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            update_in=update_data,
        )

        assert updated_person.name == "Updated Person"

    async def test_update_person_replace_tags(self, async_db_session):
        """Test updating person and replacing existing tags"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        old_tag = Tag(id=uuid4(), user_id=user.id, name="old tag", entity_type="person")
        new_tag = Tag(id=uuid4(), user_id=user.id, name="new tag", entity_type="person")
        async_db_session.add_all([old_tag, new_tag])
        await async_db_session.commit()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.commit()

        await persons_service.add_tag_to_person(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            tag_id=old_tag.id,
        )

        # Update with new tags (replacing old tags)
        update_data = PersonUpdate(tag_ids=[str(new_tag.id)])

        updated_person = await persons_service.update_person(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            update_in=update_data,
        )

        assert updated_person is not None

    async def test_update_person_clear_tags(self, async_db_session):
        """Test updating person and clearing all tags"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="tag", entity_type="person")
        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add_all([tag, person])
        await async_db_session.commit()

        await persons_service.add_tag_to_person(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            tag_id=tag.id,
        )

        # Update with empty tag list
        update_data = PersonUpdate(tag_ids=[])

        updated_person = await persons_service.update_person(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            update_in=update_data,
        )

        assert updated_person is not None

    async def test_update_person_invalid_tags(self, async_db_session):
        """Test updating person with invalid tag IDs"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.commit()

        update_data = PersonUpdate(
            tag_ids=[str(uuid4()), str(uuid4())]  # Non-existent tag IDs
        )

        with pytest.raises(TagNotFoundError):
            await persons_service.update_person(
                async_db_session,
                user_id=user.id,
                person_id=person.id,
                update_in=update_data,
            )

    async def test_delete_person_soft(self, async_db_session):
        """Test soft deleting a person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(id=uuid4(), user_id=user.id, name="Person to Delete")
        async_db_session.add(person)
        await async_db_session.commit()

        # Soft delete
        result = await persons_service.delete_person(
            async_db_session, user_id=user.id, person_id=person.id, hard_delete=False
        )

        assert result is True
        await async_db_session.refresh(person)
        assert person.deleted_at is not None
        assert person.is_deleted is True

    async def test_delete_person_hard(self, async_db_session):
        """Test hard deleting a person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(id=uuid4(), user_id=user.id, name="Person to Delete")
        async_db_session.add(person)
        await async_db_session.commit()
        person_id = person.id

        # Hard delete
        result = await persons_service.delete_person(
            async_db_session, user_id=user.id, person_id=person.id, hard_delete=True
        )

        assert result is True
        deleted_person = await async_db_session.get(Person, person_id)
        assert deleted_person is None or deleted_person.is_deleted is True

    async def test_delete_person_not_found(self, async_db_session):
        """Test deleting non-existent person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        result = await persons_service.delete_person(
            async_db_session, user_id=user.id, person_id=uuid4()
        )
        assert result is False

    async def test_add_tag_to_person(self, async_db_session):
        """Test adding a tag to a person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="test tag", entity_type="person")
        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add_all([tag, person])
        await async_db_session.commit()

        updated_person = await persons_service.add_tag_to_person(
            async_db_session, user_id=user.id, person_id=person.id, tag_id=tag.id
        )

        assert updated_person is not None
        assert updated_person.id == person.id

    async def test_add_tag_to_person_not_found(self, async_db_session):
        """Test adding tag to non-existent person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="test tag", entity_type="person")
        async_db_session.add(tag)
        await async_db_session.commit()

        with pytest.raises(PersonNotFoundError):
            await persons_service.add_tag_to_person(
                async_db_session, user_id=user.id, person_id=uuid4(), tag_id=tag.id
            )

    async def test_add_tag_to_person_tag_not_found(self, async_db_session):
        """Test adding non-existent tag to person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.commit()

        with pytest.raises(TagNotFoundError):
            await persons_service.add_tag_to_person(
                async_db_session, user_id=user.id, person_id=person.id, tag_id=uuid4()
            )

    async def test_add_tag_to_person_already_associated(self, async_db_session):
        """Test adding already associated tag to person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="test tag", entity_type="person")
        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add_all([tag, person])
        await async_db_session.commit()

        # First association
        await persons_service.add_tag_to_person(
            async_db_session, user_id=user.id, person_id=person.id, tag_id=tag.id
        )

        # Second association should fail
        with pytest.raises(PersonAlreadyExistsError):
            await persons_service.add_tag_to_person(
                async_db_session, user_id=user.id, person_id=person.id, tag_id=tag.id
            )

    async def test_remove_tag_from_person(self, async_db_session):
        """Test removing a tag from a person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="test tag", entity_type="person")
        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add_all([tag, person])
        await async_db_session.commit()

        # First add the tag
        await persons_service.add_tag_to_person(
            async_db_session, user_id=user.id, person_id=person.id, tag_id=tag.id
        )

        # Then remove it
        updated_person = await persons_service.remove_tag_from_person(
            async_db_session, user_id=user.id, person_id=person.id, tag_id=tag.id
        )

        assert updated_person is not None
        assert updated_person.id == person.id

    async def test_remove_tag_from_person_not_found(self, async_db_session):
        """Test removing tag from non-existent person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="test tag", entity_type="person")
        async_db_session.add(tag)
        await async_db_session.commit()

        with pytest.raises(PersonNotFoundError):
            await persons_service.remove_tag_from_person(
                async_db_session, user_id=user.id, person_id=uuid4(), tag_id=tag.id
            )

    async def test_remove_tag_from_person_tag_not_found(self, async_db_session):
        """Test removing non-existent tag from person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.commit()

        with pytest.raises(TagNotFoundError):
            await persons_service.remove_tag_from_person(
                async_db_session, user_id=user.id, person_id=person.id, tag_id=uuid4()
            )

    async def test_remove_tag_from_person_not_associated(self, async_db_session):
        """Test removing tag that's not associated with person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="test tag", entity_type="person")
        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add_all([tag, person])
        await async_db_session.commit()

        with pytest.raises(PersonNotFoundError):
            await persons_service.remove_tag_from_person(
                async_db_session, user_id=user.id, person_id=person.id, tag_id=tag.id
            )

    async def test_create_anniversary(self, async_db_session):
        """Test creating an anniversary for a person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.commit()

        anniversary_data = AnniversaryCreate(name="First Met", date=date(2020, 3, 15))

        anniversary = await persons_service.create_anniversary(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            anniversary_data=anniversary_data,
        )

        assert anniversary.id is not None
        assert anniversary.person_id == person.id
        assert anniversary.name == "First Met"
        assert anniversary.date == date(2020, 3, 15)
        assert anniversary.created_at is not None

    async def test_create_anniversary_person_not_found(self, async_db_session):
        """Test creating anniversary for non-existent person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        anniversary_data = AnniversaryCreate(name="First Met", date=date(2020, 3, 15))

        with pytest.raises(PersonNotFoundError):
            await persons_service.create_anniversary(
                async_db_session,
                user_id=user.id,
                person_id=uuid4(),
                anniversary_data=anniversary_data,
            )

    async def test_update_anniversary(self, async_db_session):
        """Test updating anniversary for a person."""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.flush()

        anniversary = Anniversary(
            id=uuid4(),
            user_id=user.id,
            person_id=person.id,
            name="Old",
            date=date(2020, 1, 1),
        )
        async_db_session.add(anniversary)
        await async_db_session.commit()

        updated = await persons_service.update_anniversary(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            anniversary_id=anniversary.id,
            update_data=AnniversaryUpdate(name="New", date=date(2021, 2, 2)),
        )

        assert updated is not None
        assert updated.name == "New"
        assert updated.date == date(2021, 2, 2)

    async def test_update_anniversary_not_found(self, async_db_session):
        """Update should raise when anniversary does not exist."""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.commit()

        with pytest.raises(AnniversaryNotFoundError):
            await persons_service.update_anniversary(
                async_db_session,
                user_id=user.id,
                person_id=person.id,
                anniversary_id=uuid4(),
                update_data=AnniversaryUpdate(name="New"),
            )

    async def test_get_person_anniversaries(self, async_db_session):
        """Test getting all anniversaries for a person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.commit()

        # Create multiple anniversaries
        anniversary1 = Anniversary(
            id=uuid4(),
            person_id=person.id,
            user_id=user.id,
            name="First Met",
            date=date(2020, 3, 15),
        )
        anniversary2 = Anniversary(
            id=uuid4(),
            person_id=person.id,
            user_id=user.id,
            name="Birthday",
            date=date(1990, 5, 15),
        )
        async_db_session.add_all([anniversary1, anniversary2])
        await async_db_session.commit()

        anniversaries = await persons_service.get_person_anniversaries(
            async_db_session, user_id=user.id, person_id=person.id
        )

        assert len(anniversaries) == 2
        assert all(anniversary.person_id == person.id for anniversary in anniversaries)
        # Should be sorted by date
        assert anniversaries[0].date == date(1990, 5, 15)  # Birthday (earlier)
        assert anniversaries[1].date == date(2020, 3, 15)  # First Met (later)

    async def test_get_person_anniversaries_person_not_found(self, async_db_session):
        """Test getting anniversaries for non-existent person"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        with pytest.raises(PersonNotFoundError):
            await persons_service.get_person_anniversaries(
                async_db_session, user_id=user.id, person_id=uuid4()
            )

    async def test_delete_anniversary(self, async_db_session):
        """Test deleting an anniversary"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.flush()

        anniversary = Anniversary(
            id=uuid4(),
            person_id=person.id,
            user_id=user.id,
            name="Test Anniversary",
            date=date(2020, 1, 1),
        )
        async_db_session.add(anniversary)
        await async_db_session.commit()

        # Delete the anniversary
        result = await persons_service.delete_anniversary(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            anniversary_id=anniversary.id,
        )

        assert result is True

        # Verify anniversary is deleted
        deleted_anniversary = await async_db_session.get(Anniversary, anniversary.id)
        assert deleted_anniversary is None

    async def test_delete_anniversary_not_found(self, async_db_session):
        """Test deleting non-existent anniversary"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.commit()

        with pytest.raises(AnniversaryNotFoundError):
            await persons_service.delete_anniversary(
                async_db_session,
                user_id=user.id,
                person_id=person.id,
                anniversary_id=uuid4(),
            )

    async def test_get_person_activities_empty(self, async_db_session):
        """Test getting activities for person with no activities"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.commit()

        activities = await persons_service.get_person_activities(
            async_db_session, user_id=user.id, person_id=person.id
        )

        assert activities.meta.person_id == person.id
        assert activities.meta.person_name == person.display_name
        assert activities.items == []
        assert activities.pagination.total == 0
        assert activities.pagination.pages == 0

    async def test_get_person_activities_with_vision(self, async_db_session):
        """Test getting activities for person with associated vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        vision = Vision(id=uuid4(), user_id=user.id, name="Vision involving Person")
        async_db_session.add(vision)
        await async_db_session.commit()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.commit()

        # This test is basic since actual association requires Association service
        # which would need more complex setup
        activities = await persons_service.get_person_activities(
            async_db_session, user_id=user.id, person_id=person.id
        )

        assert activities.meta.person_id == person.id
        assert activities.meta.person_name == "Test Person"

    async def test_get_person_activities_type_filter_pagination(self, async_db_session):
        """Test filtering activities by type with pagination"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        person = Person(id=uuid4(), user_id=user.id, name="Test Person")
        async_db_session.add(person)
        await async_db_session.commit()

        vision = Vision(id=uuid4(), user_id=user.id, name="Vision Root")
        async_db_session.add(vision)
        await async_db_session.commit()

        task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Test Task",
        )
        note_one = Note(
            id=uuid4(),
            user_id=user.id,
            content="First note",
        )
        note_two = Note(
            id=uuid4(),
            user_id=user.id,
            content="Second note",
        )
        async_db_session.add_all([task, note_one, note_two])
        await async_db_session.commit()

        associations = [
            Association(
                user_id=user.id,
                source_model=ModelName.Task.value,
                source_id=task.id,
                target_model=ModelName.Person.value,
                target_id=person.id,
                link_type=LinkType.INVOLVES.value,
            ),
            Association(
                user_id=user.id,
                source_model=ModelName.Note.value,
                source_id=note_one.id,
                target_model=ModelName.Person.value,
                target_id=person.id,
                link_type=LinkType.IS_ABOUT.value,
            ),
            Association(
                user_id=user.id,
                source_model=ModelName.Note.value,
                source_id=note_two.id,
                target_model=ModelName.Person.value,
                target_id=person.id,
                link_type=LinkType.IS_ABOUT.value,
            ),
        ]
        async_db_session.add_all(associations)
        await async_db_session.commit()

        all_activities = await persons_service.get_person_activities(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            page=1,
            size=10,
        )

        assert all_activities.pagination.total == 3
        assert len(all_activities.items) == 3

        note_page_one = await persons_service.get_person_activities(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            page=1,
            size=1,
            activity_type="note",
        )

        assert note_page_one.pagination.total == 2
        assert note_page_one.pagination.pages == 2
        assert len(note_page_one.items) == 1
        assert all(item.type == "note" for item in note_page_one.items)

        note_page_two = await persons_service.get_person_activities(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            page=2,
            size=1,
            activity_type="note",
        )

        assert note_page_two.pagination.total == 2
        assert len(note_page_two.items) == 1
        assert all(item.type == "note" for item in note_page_two.items)

        task_only = await persons_service.get_person_activities(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            page=1,
            size=10,
            activity_type="task",
        )

        assert task_only.pagination.total == 1
        assert len(task_only.items) == 1
        assert task_only.items[0].type == "task"

    async def test_update_person_whitespace_handling(self, async_db_session):
        """Test updating person with content that needs trimming"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        person = Person(
            id=uuid4(),
            user_id=user.id,
            name="Original Name",
            location="Original Location",
        )
        async_db_session.add(person)
        await async_db_session.commit()

        update_data = PersonUpdate(
            name="  Updated Name with spaces  ",
            location="  Updated Location with spaces  ",
            nicknames=["  New Nickname  "],
        )

        updated_person = await persons_service.update_person(
            async_db_session,
            user_id=user.id,
            person_id=person.id,
            update_in=update_data,
        )

        # Schema validation should trim whitespace
        assert updated_person.name == "Updated Name with spaces"
        assert updated_person.location == "Updated Location with spaces"
        assert updated_person.nicknames == ["New Nickname"]

    async def test_list_persons_empty_result(self, async_db_session):
        """Test listing persons when user has no persons"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        result_persons, total = await persons_service.list_persons(
            async_db_session, user_id=user.id
        )

        assert len(result_persons) == 0
        assert total == 0
