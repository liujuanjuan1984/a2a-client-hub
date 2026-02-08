"""
Tests for Note Model

This module tests the Note SQLAlchemy model including:
- Note creation and properties
- Note content validation
- Tag associations
- Note utility methods
- Soft delete functionality
"""

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models.note import Note
from app.db.models.tag import Tag
from app.db.models.user import User
from app.handlers import notes as note_service
from app.serialization.entities import build_note_response

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def add_tag_to_note(async_db_session, *, user_id, note_id, tag_id):
    return await note_service.add_tag_to_note(
        async_db_session, user_id=user_id, note_id=note_id, tag_id=tag_id
    )


async def _load_note_with_tags(async_db_session, note_id):
    """Fetch a note with tags eagerly loaded to avoid async lazy-load calls."""

    result = await async_db_session.execute(
        select(Note)
        .options(selectinload(Note.tags))
        .execution_options(populate_existing=True)
        .where(Note.id == note_id)
    )
    return result.scalar_one()


class TestNoteModel:
    """Test cases for Note model functionality"""

    async def test_note_creation_basic(self, async_db_session):
        """Test basic note creation"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note = Note(id=uuid4(), user_id=user.id, content="This is a test note content.")

        async_db_session.add(note)
        await async_db_session.commit()

        assert note.id is not None
        assert note.content == "This is a test note content."
        assert note.user_id == user.id
        assert note.created_at is not None
        assert note.updated_at is not None
        assert note.deleted_at is None

    async def test_note_creation_with_long_content(self, async_db_session):
        """Test note creation with long content"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        long_content = (
            "This is a very long note content. " * 100
        )  # Create a long content
        note = Note(id=uuid4(), user_id=user.id, content=long_content)

        async_db_session.add(note)
        await async_db_session.commit()

        assert note.content == long_content
        assert len(note.content) > 1000

    async def test_note_repr(self, async_db_session):
        """Test note string representation"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        short_content = "Short note"
        note = Note(id=uuid4(), user_id=user.id, content=short_content)

        async_db_session.add(note)
        await async_db_session.commit()

        repr_str = repr(note)
        assert "Note" in repr_str
        assert str(note.id) in repr_str
        assert short_content in repr_str
        assert str(note.created_at) in repr_str

    async def test_note_repr_long_content_truncated(self, async_db_session):
        """Test note string representation truncates long content"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        long_content = (
            "This is a very long note content that should be truncated in the string representation. "
            * 5
        )
        note = Note(id=uuid4(), user_id=user.id, content=long_content)

        async_db_session.add(note)
        await async_db_session.commit()

        repr_str = repr(note)
        assert "Note" in repr_str
        assert str(note.id) in repr_str
        assert "..." in repr_str  # Should indicate truncation
        # Check that the content part in repr is truncated to 50 chars + "..."
        content_start = repr_str.find("content='") + len("content='")
        content_end = repr_str.find("'", content_start)
        content_part = repr_str[content_start:content_end]
        assert len(content_part) <= 53  # 50 chars + "..."

    async def test_build_note_response_basic(self, async_db_session):
        """`build_note_response` 返回基础字段"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note = Note(id=uuid4(), user_id=user.id, content="Test note content")

        async_db_session.add(note)
        await async_db_session.commit()

        hydrated_note = await _load_note_with_tags(async_db_session, note.id)
        response = build_note_response(hydrated_note, include_timelogs=False)

        assert response.id == note.id
        assert response.content == "Test note content"
        assert response.tags == []
        assert response.persons == []
        assert response.timelogs == []
        assert response.created_at == note.created_at
        assert response.updated_at == note.updated_at

    async def test_build_note_response_with_tags(self, async_db_session):
        """`build_note_response` 能够带出标签信息"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()  # Commit user first to satisfy foreign key constraint

        tag1 = Tag(id=uuid4(), user_id=user.id, name="Tag1", entity_type="note")
        tag2 = Tag(id=uuid4(), user_id=user.id, name="Tag2", entity_type="note")
        async_db_session.add_all([tag1, tag2])
        await async_db_session.commit()

        note = Note(id=uuid4(), user_id=user.id, content="Note with tags")
        async_db_session.add(note)
        await async_db_session.commit()

        await add_tag_to_note(
            async_db_session,
            user_id=user.id,
            note_id=note.id,
            tag_id=tag1.id,
        )
        await add_tag_to_note(
            async_db_session,
            user_id=user.id,
            note_id=note.id,
            tag_id=tag2.id,
        )

        hydrated_note = await _load_note_with_tags(async_db_session, note.id)
        assert len(hydrated_note.tags or []) == 2

        response = build_note_response(hydrated_note, include_timelogs=False)

        assert response.id == note.id
        assert response.content == "Note with tags"
        assert len(response.tags) == 2
        tag_names = {tag.name for tag in response.tags}
        assert {"Tag1", "Tag2"} == tag_names
        assert response.persons == []

    async def test_build_note_response_includes_task_summary(self):
        """`build_note_response` 复用 task 装配 helper 并带出愿景/父任务摘要"""
        vision = SimpleNamespace(
            id=uuid4(),
            name="Grow Strength",
            status="active",
            dimension_id=uuid4(),
            is_deleted=False,
        )
        parent_task = SimpleNamespace(
            id=uuid4(),
            content="Weekly Prep",
            status="in_progress",
            is_deleted=False,
        )
        task = SimpleNamespace(
            id=uuid4(),
            content="Morning Workout",
            status="done",
            vision_id=vision.id,
            parent_task_id=parent_task.id,
            priority=1,
            estimated_effort=45,
            notes_count=2,
            actual_effort_total=30,
            created_at=datetime(2025, 1, 1, 7, 0, 0),
            updated_at=datetime(2025, 1, 1, 8, 0, 0),
            vision=vision,
            parent_task=parent_task,
            deleted_at=None,
            is_deleted=False,
        )
        note = SimpleNamespace(
            id=uuid4(),
            content="Workout reflections",
            created_at=datetime(2025, 1, 1, 8, 5, 0),
            updated_at=datetime(2025, 1, 1, 8, 5, 0),
            persons=[],
            tags=[],
            task=task,
            timelogs=[],
        )

        response = build_note_response(note, include_timelogs=False)

        assert response.task is not None
        assert response.task.id == task.id
        assert response.task.vision_summary is not None
        assert response.task.vision_summary.id == vision.id
        assert response.task.parent_summary is not None
        assert response.task.parent_summary.id == parent_task.id
        assert response.task.actual_effort_total == 30

    async def test_note_soft_delete(self, async_db_session):
        """Test note soft delete functionality"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note = Note(id=uuid4(), user_id=user.id, content="Note to be deleted")

        async_db_session.add(note)
        await async_db_session.commit()

        # Note should be active initially
        assert note.deleted_at is None
        assert note.is_deleted is False

        # Soft delete the note
        note.soft_delete()
        await async_db_session.commit()
        await async_db_session.refresh(note)

        assert note.deleted_at is not None
        assert note.is_deleted is True

    async def test_note_user_relationship(self, async_db_session):
        """Test note-user relationship"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note = Note(id=uuid4(), user_id=user.id, content="User's note")

        async_db_session.add(note)
        await async_db_session.commit()

        assert note.user_id == user.id

    async def test_note_with_empty_content(self, async_db_session):
        """Test note with empty content - should fail at validation level, not DB level"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # This should work at DB level since content is not nullable
        # but would fail at application level
        note = Note(id=uuid4(), user_id=user.id, content="")

        async_db_session.add(note)
        await async_db_session.commit()

        assert note.content == ""

    async def test_note_with_none_content(self, async_db_session):
        """Test note with None content - should fail at DB level"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note = Note(id=uuid4(), user_id=user.id, content=None)

        async_db_session.add(note)

        # Should fail at commit due to NOT NULL constraint
        with pytest.raises(Exception):  # Database integrity error
            await async_db_session.commit()

    async def test_note_content_whitespace_handling(self, async_db_session):
        """Test note content with various whitespace scenarios"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Test content with leading/trailing spaces
        note_with_spaces = Note(
            id=uuid4(), user_id=user.id, content="  Note with spaces  "
        )

        async_db_session.add(note_with_spaces)
        await async_db_session.commit()

        assert note_with_spaces.content == "  Note with spaces  "

        # Test content with newlines
        note_with_newlines = Note(
            id=uuid4(), user_id=user.id, content="Note\nwith\nnewlines"
        )

        async_db_session.add(note_with_newlines)
        await async_db_session.commit()

        assert note_with_newlines.content == "Note\nwith\nnewlines"

    async def test_note_unicode_content(self, async_db_session):
        """Test note with unicode content"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        unicode_content = "Note with unicode: 测试 🚀 émojis and accénted characters"
        note = Note(id=uuid4(), user_id=user.id, content=unicode_content)

        async_db_session.add(note)
        await async_db_session.commit()

        assert note.content == unicode_content

    async def test_note_tag_relationship_empty(self, async_db_session):
        """Test note-tag relationship when no tags"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note = Note(id=uuid4(), user_id=user.id, content="Note without tags")

        async_db_session.add(note)
        await async_db_session.commit()

        hydrated_note = await _load_note_with_tags(async_db_session, note.id)

        assert hydrated_note.tags == [] or hydrated_note.tags is None

    async def test_note_timestamps(self, async_db_session):
        """Test note timestamp handling"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note = Note(id=uuid4(), user_id=user.id, content="Note for timestamp test")

        async_db_session.add(note)
        await async_db_session.commit()

        # Check that timestamps are set
        assert note.created_at is not None
        assert note.updated_at is not None
        assert note.created_at <= note.updated_at

        # Update the note
        note.content = "Updated content"
        await async_db_session.commit()
        await async_db_session.refresh(note)

        # Updated timestamp should be later than or equal to created timestamp
        assert note.updated_at >= note.created_at

    async def test_note_id_generation(self, async_db_session):
        """Test note ID generation"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note1 = Note(id=uuid4(), user_id=user.id, content="First note")
        note2 = Note(id=uuid4(), user_id=user.id, content="Second note")

        async_db_session.add_all([note1, note2])
        await async_db_session.commit()

        # Each note should have a unique ID
        assert note1.id != note2.id
        assert isinstance(note1.id, uuid4().__class__)
        assert isinstance(note2.id, uuid4().__class__)

    async def test_note_content_max_length(self, async_db_session):
        """Test note content with maximum allowed length"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Create a very long content (simulating max length validation at app level)
        max_length_content = "A" * 10000  # Assuming max length is 10000
        note = Note(id=uuid4(), user_id=user.id, content=max_length_content)

        async_db_session.add(note)
        await async_db_session.commit()

        assert note.content == max_length_content
        assert len(note.content) == 10000
