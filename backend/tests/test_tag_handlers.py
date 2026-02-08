"""
Tests for Tag Handlers

This module tests the tag business logic handlers including:
- CRUD operations (create, read, update, delete)
- Tag uniqueness validation
- Entity type validation
- Tag usage statistics
- Tag upsert behavior
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.db.models.tag import Tag
from app.db.models.user import User
from app.handlers import tags as tags_service
from app.handlers.tags import TagAlreadyExistsError
from app.schemas.tag import TagCreate, TagUpdate

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


class TestTagHandlers:
    """Test cases for Tag handler functions"""

    async def test_create_tag_basic(self, async_db_session):
        """Test basic tag creation"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag_data = TagCreate(name="test tag", entity_type="general")

        tag = await tags_service.create_tag(
            async_db_session, user_id=user.id, tag_in=tag_data
        )

        assert tag.id is not None
        assert tag.name == "test tag"
        assert tag.entity_type == "general"
        assert tag.user_id == user.id
        assert tag.created_at is not None

    async def test_create_tag_with_all_fields(self, async_db_session):
        """Test creating tag with all fields"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag_data = TagCreate(
            name="important",
            entity_type="task",
            description="Important tasks that need attention",
            color="#FF0000",
        )

        tag = await tags_service.create_tag(
            async_db_session, user_id=user.id, tag_in=tag_data
        )

        assert tag.name == "important"
        assert tag.entity_type == "task"
        assert tag.description == "Important tasks that need attention"
        assert tag.color == "#FF0000"

    async def test_create_tag_whitespace_handling(self, async_db_session):
        """Test tag creation with content that needs trimming"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag_data = TagCreate(name="  test tag with spaces  ", entity_type="general")

        tag = await tags_service.create_tag(
            async_db_session, user_id=user.id, tag_in=tag_data
        )

        # Schema validation should trim whitespace and convert to lowercase
        assert tag.name == "test tag with spaces"

    async def test_create_tag_upsert_behavior(self, async_db_session):
        """Test that creating an existing tag returns the existing one"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag_data = TagCreate(name="duplicate tag", entity_type="general")

        # Create first tag
        tag1 = await tags_service.create_tag(
            async_db_session, user_id=user.id, tag_in=tag_data
        )

        # Create same tag again - should return existing tag
        tag2 = await tags_service.create_tag(
            async_db_session, user_id=user.id, tag_in=tag_data
        )

        assert tag1.id == tag2.id
        assert tag1.name == tag2.name

    async def test_create_tag_different_entity_types_same_name(self, async_db_session):
        """Test creating tags with same name but different entity types"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag_data1 = TagCreate(name="same name", entity_type="note")
        tag_data2 = TagCreate(name="same name", entity_type="task")

        tag1 = await tags_service.create_tag(
            async_db_session, user_id=user.id, tag_in=tag_data1
        )
        tag2 = await tags_service.create_tag(
            async_db_session, user_id=user.id, tag_in=tag_data2
        )

        # Should be different tags since entity types differ
        assert tag1.id != tag2.id
        assert tag1.name == tag2.name
        assert tag1.entity_type == "note"
        assert tag2.entity_type == "task"

    async def test_create_tag_default_entity_type(self, async_db_session):
        """Test creating tag with default entity type"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag_data = TagCreate(name="default type tag")
        # entity_type should default to "general"

        tag = await tags_service.create_tag(
            async_db_session, user_id=user.id, tag_in=tag_data
        )

        assert tag.entity_type == "general"

    async def test_get_tag(self, async_db_session):
        """Test getting a specific tag"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        tag = Tag(id=uuid4(), user_id=user.id, name="test tag", entity_type="general")
        async_db_session.add(tag)
        await async_db_session.commit()

        retrieved_tag = await tags_service.get_tag(
            async_db_session, user_id=user.id, tag_id=tag.id
        )

        assert retrieved_tag is not None
        assert retrieved_tag.id == tag.id
        assert retrieved_tag.name == "test tag"

    async def test_get_tag_not_found(self, async_db_session):
        """Test getting non-existent tag"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        result = await tags_service.get_tag(
            async_db_session, user_id=user.id, tag_id=uuid4()
        )
        assert result is None

    async def test_get_tag_soft_deleted(self, async_db_session):
        """Test getting a soft deleted tag"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        tag = Tag(id=uuid4(), user_id=user.id, name="test tag", entity_type="general")
        async_db_session.add(tag)
        await async_db_session.commit()

        # Soft delete the tag
        tag.soft_delete()
        await async_db_session.commit()

        # Should not find the soft deleted tag
        result = await tags_service.get_tag(
            async_db_session, user_id=user.id, tag_id=tag.id
        )
        assert result is None

    async def test_list_tags_basic(self, async_db_session):
        """Test basic tag listing"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Create multiple tags
        tags = []
        for i in range(3):
            tag = Tag(
                id=uuid4(),
                user_id=user.id,
                name=f"Tag {chr(67 + i)}",  # C, D, E
                entity_type="general",
            )
            tags.append(tag)
        async_db_session.add_all(tags)
        await async_db_session.commit()

        result_tags = await tags_service.list_tags(async_db_session, user_id=user.id)
        assert len(result_tags) == 3
        assert all(tag.user_id == user.id for tag in result_tags)
        # Should be sorted alphabetically by name
        assert result_tags[0].name == "Tag C"
        assert result_tags[1].name == "Tag D"
        assert result_tags[2].name == "Tag E"

    async def test_list_tags_with_entity_type_filter(self, async_db_session):
        """Test listing tags with entity type filter"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Create tags with different entity types
        note_tag = Tag(id=uuid4(), user_id=user.id, name="note tag", entity_type="note")
        task_tag = Tag(id=uuid4(), user_id=user.id, name="task tag", entity_type="task")
        general_tag = Tag(
            id=uuid4(), user_id=user.id, name="general tag", entity_type="general"
        )
        async_db_session.add_all([note_tag, task_tag, general_tag])
        await async_db_session.commit()

        # Filter by entity type
        note_tags = await tags_service.list_tags(
            async_db_session, user_id=user.id, entity_type="note"
        )
        assert len(note_tags) == 1
        assert note_tags[0].entity_type == "note"

        general_tags = await tags_service.list_tags(
            async_db_session, user_id=user.id, entity_type="general"
        )
        assert len(general_tags) == 1
        assert general_tags[0].entity_type == "general"

    async def test_list_tags_with_none_filter(self, async_db_session):
        """Test listing tags with None entity type filter"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Create tags with different entity types
        note_tag = Tag(id=uuid4(), user_id=user.id, name="note tag", entity_type="note")
        task_tag = Tag(id=uuid4(), user_id=user.id, name="task tag", entity_type="task")
        async_db_session.add_all([note_tag, task_tag])
        await async_db_session.commit()

        # Filter with None should return all tags
        all_tags = await tags_service.list_tags(
            async_db_session, user_id=user.id, entity_type=None
        )
        assert len(all_tags) == 2

    async def test_list_tags_empty_result(self, async_db_session):
        """Test listing tags when user has no tags"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        result_tags = await tags_service.list_tags(async_db_session, user_id=user.id)
        assert len(result_tags) == 0

    async def test_list_tags_soft_deleted_excluded(self, async_db_session):
        """Test that soft deleted tags are excluded from listing"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        active_tag = Tag(
            id=uuid4(), user_id=user.id, name="active tag", entity_type="general"
        )
        deleted_tag = Tag(
            id=uuid4(), user_id=user.id, name="deleted tag", entity_type="general"
        )
        async_db_session.add_all([active_tag, deleted_tag])
        await async_db_session.commit()

        # Soft delete one tag
        deleted_tag.soft_delete()
        await async_db_session.commit()

        result_tags = await tags_service.list_tags(async_db_session, user_id=user.id)
        assert len(result_tags) == 1
        assert result_tags[0].id == active_tag.id

    async def test_update_tag_basic(self, async_db_session):
        """Test updating a tag"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        tag = Tag(
            id=uuid4(), user_id=user.id, name="original name", entity_type="general"
        )
        async_db_session.add(tag)
        await async_db_session.commit()

        update_data = TagUpdate(
            name="updated name", description="Updated description", color="#FF0000"
        )

        updated_tag = await tags_service.update_tag(
            async_db_session, user_id=user.id, tag_id=tag.id, update_in=update_data
        )

        assert updated_tag.name == "updated name"
        assert updated_tag.description == "Updated description"
        assert updated_tag.color == "#FF0000"

    async def test_update_tag_not_found(self, async_db_session):
        """Test updating non-existent tag"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        update_data = TagUpdate(name="updated name")

        result = await tags_service.update_tag(
            async_db_session, user_id=user.id, tag_id=uuid4(), update_in=update_data
        )
        assert result is None

    async def test_update_tag_name_conflict(self, async_db_session):
        """Test updating tag to a name that already exists"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        tag1 = Tag(id=uuid4(), user_id=user.id, name="tag1", entity_type="general")
        tag2 = Tag(id=uuid4(), user_id=user.id, name="tag2", entity_type="general")
        async_db_session.add_all([tag1, tag2])
        await async_db_session.commit()

        # Try to rename tag2 to tag1's name
        update_data = TagUpdate(name="tag1")

        with pytest.raises(TagAlreadyExistsError):
            await tags_service.update_tag(
                async_db_session, user_id=user.id, tag_id=tag2.id, update_in=update_data
            )

    async def test_update_tag_name_different_entity_type(self, async_db_session):
        """Test updating tag name to one that exists in different entity type"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note_tag = Tag(
            id=uuid4(), user_id=user.id, name="same name", entity_type="note"
        )
        task_tag = Tag(
            id=uuid4(), user_id=user.id, name="different name", entity_type="task"
        )
        async_db_session.add_all([note_tag, task_tag])
        await async_db_session.commit()

        # Should be able to rename task_tag to "same name" since entity_type differs
        update_data = TagUpdate(name="same name")
        updated_tag = await tags_service.update_tag(
            async_db_session, user_id=user.id, tag_id=task_tag.id, update_in=update_data
        )

        assert updated_tag.name == "same name"

    async def test_update_tag_partial(self, async_db_session):
        """Test updating only some tag fields"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        tag = Tag(
            id=uuid4(),
            user_id=user.id,
            name="original name",
            entity_type="general",
            description="Original description",
            color="#00FF00",
        )
        async_db_session.add(tag)
        await async_db_session.commit()

        # Update only the color
        update_data = TagUpdate(color="#FF0000")
        updated_tag = await tags_service.update_tag(
            async_db_session, user_id=user.id, tag_id=tag.id, update_in=update_data
        )

        assert updated_tag.name == "original name"  # Unchanged
        assert updated_tag.description == "Original description"  # Unchanged
        assert updated_tag.color == "#FF0000"  # Updated

    async def test_update_tag_whitespace_handling(self, async_db_session):
        """Test updating tag with content that needs trimming"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        tag = Tag(
            id=uuid4(), user_id=user.id, name="original name", entity_type="general"
        )
        async_db_session.add(tag)
        await async_db_session.commit()

        update_data = TagUpdate(name="  updated name with spaces  ")
        updated_tag = await tags_service.update_tag(
            async_db_session, user_id=user.id, tag_id=tag.id, update_in=update_data
        )

        # Schema validation should trim whitespace and convert to lowercase
        assert updated_tag.name == "updated name with spaces"

    async def test_delete_tag_soft(self, async_db_session):
        """Test soft deleting a tag"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        tag = Tag(
            id=uuid4(), user_id=user.id, name="tag to delete", entity_type="general"
        )
        async_db_session.add(tag)
        await async_db_session.commit()

        # Soft delete
        result = await tags_service.delete_tag(
            async_db_session, user_id=user.id, tag_id=tag.id, hard_delete=False
        )

        assert result is True
        await async_db_session.refresh(tag)
        assert tag.deleted_at is not None
        assert tag.is_deleted is True

    async def test_delete_tag_hard(self, async_db_session):
        """Test hard deleting a tag"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        tag = Tag(
            id=uuid4(), user_id=user.id, name="tag to delete", entity_type="general"
        )
        async_db_session.add(tag)
        await async_db_session.commit()
        tag_id = tag.id

        # Hard delete
        result = await tags_service.delete_tag(
            async_db_session, user_id=user.id, tag_id=tag.id, hard_delete=True
        )

        assert result is True
        deleted_tag = await async_db_session.get(Tag, tag_id)
        assert deleted_tag is None or deleted_tag.is_deleted is True

    async def test_delete_tag_not_found(self, async_db_session):
        """Test deleting non-existent tag"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        result = await tags_service.delete_tag(
            async_db_session, user_id=user.id, tag_id=uuid4()
        )
        assert result is False

    async def test_delete_tag_already_soft_deleted(self, async_db_session):
        """Test deleting a tag that's already soft deleted"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        tag = Tag(
            id=uuid4(),
            user_id=user.id,
            name="already deleted tag",
            entity_type="general",
        )
        async_db_session.add(tag)
        await async_db_session.commit()

        # Soft delete first
        tag.soft_delete()
        await async_db_session.commit()

        # Try to delete again
        result = await tags_service.delete_tag(
            async_db_session, user_id=user.id, tag_id=tag.id
        )
        assert result is False

    async def test_get_tag_usage(self, async_db_session):
        """Test getting tag usage statistics"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="test tag", entity_type="general")
        async_db_session.add(tag)
        await async_db_session.commit()

        # Note: In a real scenario, usage stats would come from tag_associations
        # For this test, we're testing the basic structure
        usage_stats = await tags_service.get_tag_usage(
            async_db_session, user_id=user.id, tag_id=tag.id
        )

        assert usage_stats is not None
        assert usage_stats["tag_id"] == tag.id
        assert usage_stats["tag_name"] == "test tag"
        assert usage_stats["entity_type"] == "general"
        assert "usage_by_entity_type" in usage_stats
        assert "total_usage" in usage_stats

    async def test_get_tag_usage_not_found(self, async_db_session):
        """Test getting usage statistics for non-existent tag"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        result = await tags_service.get_tag_usage(
            async_db_session, user_id=user.id, tag_id=uuid4()
        )
        assert result is None

    async def test_get_entity_types(self, async_db_session):
        """Test getting all supported entity types"""
        entity_types = tags_service.get_entity_types()

        expected_types = ["person", "note", "task", "vision", "general"]
        assert entity_types == expected_types

    async def test_create_tag_for_different_entity_types(self, async_db_session):
        """Test creating tags for all supported entity types"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        entity_types = tags_service.get_entity_types()
        created_tags = []

        for entity_type in entity_types:
            tag_data = TagCreate(
                name=f"{entity_type} tag",
                entity_type=entity_type,
                description=f"Tag for {entity_type} entities",
            )
            tag = await tags_service.create_tag(
                async_db_session, user_id=user.id, tag_in=tag_data
            )
            created_tags.append(tag)

        assert len(created_tags) == len(entity_types)
        for i, tag in enumerate(created_tags):
            assert tag.entity_type == entity_types[i]
            assert tag.name == f"{entity_types[i]} tag"

    async def test_list_tags_for_specific_entity_type(self, async_db_session):
        """Test listing tags for specific entity types"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        # Create tags for different entity types
        entity_types = ["note", "task", "vision"]
        for entity_type in entity_types:
            for i in range(2):
                tag = Tag(
                    id=uuid4(),
                    user_id=user.id,
                    name=f"{entity_type} tag {i+1}",
                    entity_type=entity_type,
                )
                async_db_session.add(tag)
        await async_db_session.commit()

        # Test filtering by each entity type
        for entity_type in entity_types:
            filtered_tags = await tags_service.list_tags(
                async_db_session, user_id=user.id, entity_type=entity_type
            )
            assert len(filtered_tags) == 2
            assert all(tag.entity_type == entity_type for tag in filtered_tags)

    async def test_update_tag_entity_type(self, async_db_session):
        """Test updating tag's entity type"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        tag = Tag(id=uuid4(), user_id=user.id, name="test tag", entity_type="general")
        async_db_session.add(tag)
        await async_db_session.commit()

        update_data = TagUpdate(entity_type="task")
        updated_tag = await tags_service.update_tag(
            async_db_session, user_id=user.id, tag_id=tag.id, update_in=update_data
        )

        assert updated_tag.entity_type == "task"
        assert updated_tag.name == "test tag"  # Unchanged

    async def test_update_tag_name_and_entity_type_conflict(self, async_db_session):
        """Test updating tag name and entity type when combination already exists"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        tag1 = Tag(
            id=uuid4(), user_id=user.id, name="existing name", entity_type="general"
        )
        tag2 = Tag(
            id=uuid4(), user_id=user.id, name="different name", entity_type="task"
        )
        async_db_session.add_all([tag1, tag2])
        await async_db_session.commit()

        # Try to rename tag2 to have same name + entity_type as tag1
        update_data = TagUpdate(name="existing name", entity_type="general")

        with pytest.raises(TagAlreadyExistsError):
            await tags_service.update_tag(
                async_db_session, user_id=user.id, tag_id=tag2.id, update_in=update_data
            )
