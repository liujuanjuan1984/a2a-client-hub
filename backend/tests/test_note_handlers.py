"""
Tests for Note Handlers

This module tests the note business logic handlers including:
- CRUD operations (create, read, update, delete)
- Note search and filtering
- Tag associations
- Person associations
- Task associations
- Batch operations
- Advanced search functionality
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models.actual_event import ActualEvent
from app.db.models.association import Association
from app.db.models.note import Note
from app.db.models.person import Person
from app.db.models.tag import Tag
from app.db.models.task import Task
from app.db.models.user import User
from app.db.models.vision import Vision
from app.handlers import notes as note_service
from app.handlers.notes_exceptions import (
    InvalidOperationError,
    NoteNotFoundError,
    TagAlreadyAssociatedError,
    TagNotAssociatedError,
    TagNotFoundError,
)
from app.schemas.note import (
    NoteAdvancedSearchRequest,
    NoteBatchContentUpdate,
    NoteBatchDeleteRequest,
    NoteBatchTagUpdate,
    NoteBatchUpdateRequest,
    NoteCreate,
    NoteUpdate,
)
from app.utils.timezone_util import utc_now

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _run_note_handler(async_db_session, handler, **kwargs):
    return await handler(async_db_session, **kwargs)


async def create_note(async_db_session, *, user_id, note_in):
    return await _run_note_handler(
        async_db_session, note_service.create_note, user_id=user_id, note_in=note_in
    )


async def batch_create_notes(async_db_session, *, user_id, note_inputs):
    return await _run_note_handler(
        async_db_session,
        note_service.batch_create_notes,
        user_id=user_id,
        note_inputs=note_inputs,
    )


async def list_notes(async_db_session, *, user_id, **kwargs):
    return await _run_note_handler(
        async_db_session,
        note_service.list_notes,
        user_id=user_id,
        **kwargs,
    )


async def advanced_search_notes(async_db_session, *, user_id, request):
    return await _run_note_handler(
        async_db_session,
        note_service.advanced_search_notes,
        user_id=user_id,
        request=request,
    )


async def get_note(async_db_session, *, user_id, note_id):
    return await _run_note_handler(
        async_db_session, note_service.get_note, user_id=user_id, note_id=note_id
    )


async def get_note_task(async_db_session, *, user_id, note_id):
    return await _run_note_handler(
        async_db_session, note_service.get_note_task, user_id=user_id, note_id=note_id
    )


async def update_note(
    async_db_session, *, user_id, note_id, note_in=None, update_in=None
):
    payload = note_in if note_in is not None else update_in
    return await _run_note_handler(
        async_db_session,
        note_service.update_note,
        user_id=user_id,
        note_id=note_id,
        note_in=payload,
    )


async def delete_note(async_db_session, *, user_id, note_id, hard_delete=False):
    return await _run_note_handler(
        async_db_session,
        note_service.delete_note,
        user_id=user_id,
        note_id=note_id,
        hard_delete=hard_delete,
    )


async def add_tag_to_note(async_db_session, *, user_id, note_id, tag_id):
    return await _run_note_handler(
        async_db_session,
        note_service.add_tag_to_note,
        user_id=user_id,
        note_id=note_id,
        tag_id=tag_id,
    )


async def remove_tag_from_note(async_db_session, *, user_id, note_id, tag_id):
    return await _run_note_handler(
        async_db_session,
        note_service.remove_tag_from_note,
        user_id=user_id,
        note_id=note_id,
        tag_id=tag_id,
    )


async def batch_update_notes(async_db_session, *, user_id, payload=None, request=None):
    payload = payload if payload is not None else request
    kwargs = {"request": payload} if payload is not None else {}
    return await _run_note_handler(
        async_db_session,
        note_service.batch_update_notes,
        user_id=user_id,
        **kwargs,
    )


async def batch_delete_notes(async_db_session, *, user_id, request):
    return await _run_note_handler(
        async_db_session,
        note_service.batch_delete_notes,
        user_id=user_id,
        request=request,
    )


async def get_notes_stats(async_db_session, *, user_id):
    return await _run_note_handler(
        async_db_session, note_service.get_notes_stats, user_id=user_id
    )


async def get_notes_person_stats(async_db_session, *, user_id):
    return await _run_note_handler(
        async_db_session,
        note_service.get_notes_person_stats,
        user_id=user_id,
    )


class TestNoteHandlers:
    """Test cases for Note handler functions"""

    async def test_create_note_basic(self, async_db_session):
        """Test basic note creation"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        note_data = NoteCreate(content="This is a test note")

        note = await create_note(async_db_session, user_id=user.id, note_in=note_data)

        assert note.id is not None
        assert note.content == "This is a test note"
        assert note.user_id == user.id
        assert note.created_at is not None
        assert note.updated_at is not None

    async def test_create_note_with_whitespace(self, async_db_session):
        """Test note creation with content that needs trimming"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        note_data = NoteCreate(content="  This is a test note with spaces  ")

        note = await create_note(async_db_session, user_id=user.id, note_in=note_data)

        assert note.content == "This is a test note with spaces"

    async def test_create_note_with_persons(self, async_db_session):
        """Test creating note with person associations"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        person1 = Person(id=uuid4(), user_id=user.id, name="Person 1")
        person2 = Person(id=uuid4(), user_id=user.id, name="Person 2")
        async_db_session.add_all([person1, person2])
        await async_db_session.commit()

        note_data = NoteCreate(
            content="Note with persons", person_ids=[str(person1.id), str(person2.id)]
        )

        note = await create_note(async_db_session, user_id=user.id, note_in=note_data)

        assert note.id is not None
        assert note.content == "Note with persons"

    async def test_create_note_with_tags(self, async_db_session):
        """Test creating note with tag associations"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag1 = Tag(id=uuid4(), user_id=user.id, name="Tag1", entity_type="note")
        tag2 = Tag(id=uuid4(), user_id=user.id, name="Tag2", entity_type="note")
        async_db_session.add_all([tag1, tag2])
        await async_db_session.commit()

        note_data = NoteCreate(
            content="Note with tags", tag_ids=[str(tag1.id), str(tag2.id)]
        )

        note = await create_note(async_db_session, user_id=user.id, note_in=note_data)

        assert note.id is not None
        assert note.content == "Note with tags"

    async def test_create_note_with_task(self, async_db_session):
        """Test creating note with task association"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        vision = Vision(id=uuid4(), user_id=user.id, name="Test Vision")
        async_db_session.add(user)
        async_db_session.add(vision)
        await async_db_session.commit()

        task = Task(
            id=uuid4(), user_id=user.id, vision_id=vision.id, content="Test Task"
        )
        async_db_session.add(task)
        await async_db_session.commit()

        note_data = NoteCreate(content="Note with task", task_id=task.id)

        note = await create_note(async_db_session, user_id=user.id, note_in=note_data)

        assert note.id is not None
        assert note.content == "Note with task"

        await async_db_session.refresh(task)
        assert task.notes_count == 1

    async def test_create_note_with_actual_events(self, async_db_session):
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        event = ActualEvent(
            id=uuid4(),
            user_id=user.id,
            title="Morning focus",
            start_time=datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc),
            end_time=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
            dimension_id=None,
            tracking_method="manual",
        )
        async_db_session.add(event)
        await async_db_session.commit()

        note_data = NoteCreate(content="Log reflection", actual_event_ids=[event.id])

        note = await create_note(async_db_session, user_id=user.id, note_in=note_data)

        result = await async_db_session.execute(
            select(Association).where(
                Association.source_model == "Note",
                Association.source_id == note.id,
                Association.target_model == "ActualEvent",
                Association.target_id == event.id,
            )
        )
        link = result.scalars().one_or_none()

        assert link is not None
        assert note.id is not None

    async def test_create_note_with_task_empty_string(self, async_db_session):
        """Test creating note with empty task_id string"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        note_data = NoteCreate(content="Note without task", task_id="")

        note = await create_note(async_db_session, user_id=user.id, note_in=note_data)

        assert note.id is not None
        assert note.content == "Note without task"

    async def test_get_note(self, async_db_session):
        """Test getting a specific note"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note = Note(id=uuid4(), user_id=user.id, content="Test note")
        async_db_session.add(note)
        await async_db_session.commit()

        retrieved_note = await get_note(
            async_db_session, user_id=user.id, note_id=note.id
        )

        assert retrieved_note is not None
        assert retrieved_note.id == note.id
        assert retrieved_note.content == "Test note"

    async def test_get_note_not_found(self, async_db_session):
        """Test getting non-existent note"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        with pytest.raises(NoteNotFoundError):
            await get_note(async_db_session, user_id=user.id, note_id=uuid4())

    async def test_list_notes_basic(self, async_db_session):
        """Test basic note listing"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Create multiple notes
        notes = []
        for i in range(3):
            note = Note(id=uuid4(), user_id=user.id, content=f"Note {i+1}")
            notes.append(note)
        async_db_session.add_all(notes)
        await async_db_session.commit()

        result_notes = await list_notes(async_db_session, user_id=user.id)
        assert len(result_notes) == 3
        assert all(note.user_id == user.id for note in result_notes)

    async def test_list_notes_with_pagination(self, async_db_session):
        """Test note listing with pagination"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Create more notes than will fit in one page
        notes = []
        for i in range(5):
            note = Note(id=uuid4(), user_id=user.id, content=f"Note {i+1}")
            notes.append(note)
        async_db_session.add_all(notes)
        await async_db_session.commit()

        # Test pagination
        page1 = await list_notes(async_db_session, user_id=user.id, limit=2, offset=0)
        page2 = await list_notes(async_db_session, user_id=user.id, limit=2, offset=2)
        page3 = await list_notes(async_db_session, user_id=user.id, limit=2, offset=4)

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1

        # Ensure no overlaps
        page1_ids = {n.id for n in page1}
        page2_ids = {n.id for n in page2}
        page3_ids = {n.id for n in page3}

        assert len(page1_ids.intersection(page2_ids)) == 0
        assert len(page2_ids.intersection(page3_ids)) == 0
        assert len(page1_ids.intersection(page3_ids)) == 0

    async def test_list_notes_with_keyword_search(self, async_db_session):
        """Test note listing with keyword search"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note1 = Note(id=uuid4(), user_id=user.id, content="Meeting notes about project")
        note2 = Note(id=uuid4(), user_id=user.id, content="Shopping list for groceries")
        note3 = Note(
            id=uuid4(), user_id=user.id, content="Project timeline and milestones"
        )
        async_db_session.add_all([note1, note2, note3])
        await async_db_session.commit()

        # Search for "project"
        project_notes = await list_notes(
            async_db_session, user_id=user.id, keyword="project"
        )
        assert len(project_notes) == 2  # note1 and note3

        # Search for multiple keywords
        multi_notes = await list_notes(
            async_db_session, user_id=user.id, keyword="meeting project"
        )
        assert len(multi_notes) == 2  # Should find both notes (OR logic)

    async def test_list_notes_untagged_filter(self, async_db_session):
        """Test listing notes with untagged filter"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="Test Tag", entity_type="note")
        async_db_session.add(tag)
        await async_db_session.commit()

        # Create tagged note
        tagged_note = Note(id=uuid4(), user_id=user.id, content="Tagged note")
        async_db_session.add(tagged_note)
        await async_db_session.commit()

        await add_tag_to_note(
            async_db_session,
            user_id=user.id,
            note_id=tagged_note.id,
            tag_id=tag.id,
        )

        # Create untagged note
        untagged_note = Note(id=uuid4(), user_id=user.id, content="Untagged note")
        async_db_session.add(untagged_note)
        await async_db_session.commit()

        # Filter for untagged notes
        untagged_results = await list_notes(
            async_db_session, user_id=user.id, untagged=True
        )
        assert len(untagged_results) == 1
        assert untagged_results[0].id == untagged_note.id

    async def test_list_notes_with_tag_filter(self, async_db_session):
        """Test listing notes with tag filter"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag1 = Tag(id=uuid4(), user_id=user.id, name="Tag1", entity_type="note")
        tag2 = Tag(id=uuid4(), user_id=user.id, name="Tag2", entity_type="note")
        async_db_session.add_all([tag1, tag2])
        await async_db_session.commit()

        note1 = Note(id=uuid4(), user_id=user.id, content="Note with tag1")
        note2 = Note(id=uuid4(), user_id=user.id, content="Note with tag2")
        note3 = Note(id=uuid4(), user_id=user.id, content="Note without tags")
        async_db_session.add_all([note1, note2, note3])
        await async_db_session.commit()

        await add_tag_to_note(
            async_db_session,
            user_id=user.id,
            note_id=note1.id,
            tag_id=tag1.id,
        )
        await add_tag_to_note(
            async_db_session,
            user_id=user.id,
            note_id=note2.id,
            tag_id=tag2.id,
        )

        # Filter by tag1
        tag1_notes = await list_notes(async_db_session, user_id=user.id, tag_id=tag1.id)
        assert len(tag1_notes) == 1
        assert tag1_notes[0].id == note1.id

    async def test_list_notes_conflicting_filters(self, async_db_session):
        """Test listing notes with conflicting tag filters"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        with pytest.raises(InvalidOperationError):
            await list_notes(
                async_db_session, user_id=user.id, tag_id=uuid4(), untagged=True
            )

    async def test_update_note(self, async_db_session):
        """Test updating a note"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note = Note(id=uuid4(), user_id=user.id, content="Original content")
        async_db_session.add(note)
        await async_db_session.commit()

        update_data = NoteUpdate(content="Updated content")

        updated_note = await update_note(
            async_db_session, user_id=user.id, note_id=note.id, update_in=update_data
        )

        assert updated_note.content == "Updated content"

    async def test_update_note_not_found(self, async_db_session):
        """Test updating non-existent note"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        update_data = NoteUpdate(content="Updated content")

        with pytest.raises(NoteNotFoundError):
            await update_note(
                async_db_session,
                user_id=user.id,
                note_id=uuid4(),
                update_in=update_data,
            )

    async def test_update_note_with_whitespace(self, async_db_session):
        """Test updating note with content that needs trimming"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note = Note(id=uuid4(), user_id=user.id, content="Original content")
        async_db_session.add(note)
        await async_db_session.commit()

        update_data = NoteUpdate(content="  Updated content with spaces  ")

        updated_note = await update_note(
            async_db_session, user_id=user.id, note_id=note.id, update_in=update_data
        )

        assert updated_note.content == "Updated content with spaces"

    async def test_delete_note_soft(self, async_db_session):
        """Test soft deleting a note"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        vision = Vision(id=uuid4(), user_id=user.id, name="Vision")
        task = Task(id=uuid4(), user_id=user.id, vision_id=vision.id, content="Task")
        async_db_session.add_all([user, vision, task])
        await async_db_session.commit()

        note = await create_note(
            async_db_session,
            user_id=user.id,
            note_in=NoteCreate(content="Note to delete", task_id=task.id),
        )

        await async_db_session.refresh(task)
        assert task.notes_count == 1

        # Soft delete
        result = await delete_note(
            async_db_session, user_id=user.id, note_id=note.id, hard_delete=False
        )

        assert result is True
        await async_db_session.refresh(note)
        assert note.deleted_at is not None
        assert note.is_deleted is True
        await async_db_session.refresh(task)
        assert task.notes_count == 0

    async def test_delete_note_hard(self, async_db_session):
        """Test hard deleting a note"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note = Note(id=uuid4(), user_id=user.id, content="Note to delete")
        async_db_session.add(note)
        await async_db_session.commit()
        note_id = note.id

        # Hard delete
        result = await delete_note(
            async_db_session, user_id=user.id, note_id=note.id, hard_delete=True
        )

        assert result is True
        result = await async_db_session.execute(select(Note).where(Note.id == note_id))
        deleted_note = result.scalars().first()
        assert deleted_note is None or deleted_note.is_deleted is True

    async def test_delete_note_not_found(self, async_db_session):
        """Test deleting non-existent note"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        with pytest.raises(NoteNotFoundError):
            await delete_note(async_db_session, user_id=user.id, note_id=uuid4())

    async def test_get_notes_stats(self, async_db_session):
        """Test getting notes statistics"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Create multiple notes
        for i in range(3):
            note = Note(id=uuid4(), user_id=user.id, content=f"Note {i+1}")
            async_db_session.add(note)
        await async_db_session.commit()

        stats = await get_notes_stats(async_db_session, user_id=user.id)

        assert stats["total_notes"] == 3

    async def test_get_notes_person_stats(self, async_db_session):
        """Test getting person usage statistics for notes"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        person1 = Person(id=uuid4(), user_id=user.id, name="Person 1")
        person2 = Person(id=uuid4(), user_id=user.id, name="Person 2")
        async_db_session.add_all([person1, person2])
        await async_db_session.commit()

        # Create notes (the actual associations would be created via the handler)
        note1 = Note(id=uuid4(), user_id=user.id, content="Note about person1")
        note2 = Note(id=uuid4(), user_id=user.id, content="Another note about person1")
        note3 = Note(id=uuid4(), user_id=user.id, content="Note about person2")
        async_db_session.add_all([note1, note2, note3])
        await async_db_session.commit()

        # Note: This test only verifies the basic structure since the actual
        # associations are created through weak links which would require
        # additional setup to test properly
        stats = await get_notes_person_stats(async_db_session, user_id=user.id)

        assert "person_stats" in stats
        assert isinstance(stats["person_stats"], list)

    async def test_add_tag_to_note(self, async_db_session):
        """Test adding a tag to a note"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="Test Tag", entity_type="note")
        note = Note(id=uuid4(), user_id=user.id, content="Test note")
        async_db_session.add_all([tag, note])
        await async_db_session.commit()

        updated_note = await add_tag_to_note(
            async_db_session, user_id=user.id, note_id=note.id, tag_id=tag.id
        )

        assert updated_note.id == note.id

    async def test_add_tag_to_note_not_found(self, async_db_session):
        """Test adding tag to non-existent note"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="Test Tag", entity_type="note")
        async_db_session.add(tag)
        await async_db_session.commit()

        with pytest.raises(NoteNotFoundError):
            await add_tag_to_note(
                async_db_session, user_id=user.id, note_id=uuid4(), tag_id=tag.id
            )

    async def test_add_tag_to_note_tag_not_found(self, async_db_session):
        """Test adding non-existent tag to note"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note = Note(id=uuid4(), user_id=user.id, content="Test note")
        async_db_session.add(note)
        await async_db_session.commit()

        with pytest.raises(TagNotFoundError):
            await add_tag_to_note(
                async_db_session, user_id=user.id, note_id=note.id, tag_id=uuid4()
            )

    async def test_add_tag_to_note_already_associated(self, async_db_session):
        """Test adding already associated tag to note"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="Test Tag", entity_type="note")
        note = Note(id=uuid4(), user_id=user.id, content="Test note")
        async_db_session.add_all([tag, note])
        await async_db_session.commit()

        # First association
        await add_tag_to_note(
            async_db_session, user_id=user.id, note_id=note.id, tag_id=tag.id
        )

        # Second association should fail
        with pytest.raises(TagAlreadyAssociatedError):
            await add_tag_to_note(
                async_db_session, user_id=user.id, note_id=note.id, tag_id=tag.id
            )

    async def test_remove_tag_from_note(self, async_db_session):
        """Test removing a tag from a note"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="Test Tag", entity_type="note")
        note = Note(id=uuid4(), user_id=user.id, content="Test note")
        async_db_session.add_all([tag, note])
        await async_db_session.commit()

        # First add the tag
        await add_tag_to_note(
            async_db_session, user_id=user.id, note_id=note.id, tag_id=tag.id
        )

        # Then remove it
        updated_note = await remove_tag_from_note(
            async_db_session, user_id=user.id, note_id=note.id, tag_id=tag.id
        )

        assert updated_note.id == note.id

    async def test_remove_tag_from_note_not_associated(self, async_db_session):
        """Test removing non-associated tag from note"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="Test Tag", entity_type="note")
        note = Note(id=uuid4(), user_id=user.id, content="Test note")
        async_db_session.add_all([tag, note])
        await async_db_session.commit()

        with pytest.raises(TagNotAssociatedError):
            await remove_tag_from_note(
                async_db_session, user_id=user.id, note_id=note.id, tag_id=tag.id
            )

    async def test_get_note_task(self, async_db_session):
        """Test getting task associated with a note"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        vision = Vision(id=uuid4(), user_id=user.id, name="Test Vision")
        async_db_session.add(user)
        async_db_session.add(vision)
        await async_db_session.commit()

        task = Task(
            id=uuid4(), user_id=user.id, vision_id=vision.id, content="Test Task"
        )
        note = Note(id=uuid4(), user_id=user.id, content="Test note")
        async_db_session.add_all([task, note])
        await async_db_session.commit()

        # This would normally be done through weak associations
        associated_task = await get_note_task(
            async_db_session, user_id=user.id, note_id=note.id
        )

        assert associated_task is None  # No association created yet

    async def test_advanced_search_notes_basic(self, async_db_session):
        """Test basic advanced search for notes"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note1 = Note(id=uuid4(), user_id=user.id, content="Meeting about project")
        note2 = Note(id=uuid4(), user_id=user.id, content="Shopping list")
        async_db_session.add_all([note1, note2])
        await async_db_session.commit()

        # Basic keyword search
        request = NoteAdvancedSearchRequest(keyword="project")
        results = await advanced_search_notes(
            async_db_session, user_id=user.id, request=request
        )

        assert len(results) == 1
        assert results[0][0].content == "Meeting about project"

    async def test_advanced_search_notes_with_date_range(self, async_db_session):
        """Test advanced search with date range"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        now = utc_now()
        yesterday = now - timedelta(days=1)

        note1 = Note(
            id=uuid4(), user_id=user.id, content="Yesterday note", created_at=yesterday
        )
        note2 = Note(id=uuid4(), user_id=user.id, content="Today note", created_at=now)
        async_db_session.add_all([note1, note2])
        await async_db_session.commit()

        # Search for today's notes
        request = NoteAdvancedSearchRequest(
            start_date=now.replace(hour=0, minute=0, second=0),
            end_date=now.replace(hour=23, minute=59, second=59),
        )
        results = await advanced_search_notes(
            async_db_session, user_id=user.id, request=request
        )

        assert len(results) == 1
        assert results[0][0].content == "Today note"

    async def test_advanced_search_notes_invalid_date_range(self, async_db_session):
        """Test advanced search with invalid date range"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        now = utc_now()
        yesterday = now - timedelta(days=1)

        # This should fail at Pydantic validation level, which is expected behavior
        with pytest.raises(Exception):  # Pydantic validation error
            NoteAdvancedSearchRequest(
                start_date=now, end_date=yesterday  # End date before start date
            )

    async def test_batch_update_notes_tags(self, async_db_session):
        """Test batch updating note tags"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag = Tag(id=uuid4(), user_id=user.id, name="Batch Tag", entity_type="note")
        note1 = Note(id=uuid4(), user_id=user.id, content="Note 1")
        note2 = Note(id=uuid4(), user_id=user.id, content="Note 2")
        async_db_session.add_all([tag, note1, note2])
        await async_db_session.commit()

        request = NoteBatchUpdateRequest(
            note_ids=[note1.id, note2.id],
            operation="tags",
            tags=NoteBatchTagUpdate(mode="replace", tag_ids=[tag.id]),
        )

        response = await batch_update_notes(
            async_db_session, user_id=user.id, request=request
        )

        assert response.updated_count == 2
        assert len(response.failed_ids) == 0

    async def test_batch_update_notes_content(self, async_db_session):
        """Test batch updating note content"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note1 = Note(id=uuid4(), user_id=user.id, content="Old content 1")
        note2 = Note(id=uuid4(), user_id=user.id, content="Old content 2")
        async_db_session.add_all([note1, note2])
        await async_db_session.commit()

        request = NoteBatchUpdateRequest(
            note_ids=[note1.id, note2.id],
            operation="content",
            content=NoteBatchContentUpdate(
                find_text="Old", replace_text="New", case_sensitive=False
            ),
        )

        response = await batch_update_notes(
            async_db_session, user_id=user.id, request=request
        )

        assert response.updated_count == 2
        assert len(response.failed_ids) == 0

    async def test_batch_delete_notes(self, async_db_session):
        """Test batch deleting notes"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        note1 = Note(id=uuid4(), user_id=user.id, content="Note to delete 1")
        note2 = Note(id=uuid4(), user_id=user.id, content="Note to delete 2")
        note3 = Note(id=uuid4(), user_id=user.id, content="Note to keep")
        async_db_session.add_all([note1, note2, note3])
        await async_db_session.commit()

        request = NoteBatchDeleteRequest(note_ids=[note1.id, note2.id])
        response = await batch_delete_notes(
            async_db_session, user_id=user.id, request=request
        )

        assert response.deleted_count == 2
        assert len(response.failed_ids) == 0

        # Verify notes are soft deleted
        await async_db_session.refresh(note1)
        await async_db_session.refresh(note2)
        assert note1.is_deleted is True
        assert note2.is_deleted is True
        assert note3.is_deleted is False

    async def test_batch_delete_notes_not_found(self, async_db_session):
        """Test batch deleting non-existent notes"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        request = NoteBatchDeleteRequest(note_ids=[uuid4(), uuid4()])
        response = await batch_delete_notes(
            async_db_session, user_id=user.id, request=request
        )

        assert response.deleted_count == 0
        assert len(response.failed_ids) == 2

    async def test_advanced_search_tag_filters(self, async_db_session):
        """Test advanced search with tag filters"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        tag1 = Tag(id=uuid4(), user_id=user.id, name="Tag1", entity_type="note")
        tag2 = Tag(id=uuid4(), user_id=user.id, name="Tag2", entity_type="note")
        note1 = Note(id=uuid4(), user_id=user.id, content="Note with tag1")
        note2 = Note(id=uuid4(), user_id=user.id, content="Note with both tags")
        note3 = Note(id=uuid4(), user_id=user.id, content="Note without tags")
        async_db_session.add_all([tag1, tag2, note1, note2, note3])
        await async_db_session.commit()

        await add_tag_to_note(
            async_db_session,
            user_id=user.id,
            note_id=note1.id,
            tag_id=tag1.id,
        )
        await add_tag_to_note(
            async_db_session,
            user_id=user.id,
            note_id=note2.id,
            tag_id=tag1.id,
        )
        await add_tag_to_note(
            async_db_session,
            user_id=user.id,
            note_id=note2.id,
            tag_id=tag2.id,
        )

        # Search for notes with any of the tags
        request = NoteAdvancedSearchRequest(tag_ids=[tag1.id, tag2.id], tag_mode="any")
        results = await advanced_search_notes(
            async_db_session, user_id=user.id, request=request
        )

        assert len(results) == 2  # note1 and note2

        # Search for notes without tags
        request_none = NoteAdvancedSearchRequest(tag_mode="none")
        results_none = await advanced_search_notes(
            async_db_session, user_id=user.id, request=request_none
        )

        assert len(results_none) == 1  # only note3

    async def test_advanced_search_person_filters(self, async_db_session):
        """Test advanced search with person filters"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        person1 = Person(id=uuid4(), user_id=user.id, name="Person 1")
        person2 = Person(id=uuid4(), user_id=user.id, name="Person 2")
        note1 = Note(id=uuid4(), user_id=user.id, content="Note about person1")
        note2 = Note(id=uuid4(), user_id=user.id, content="Note about both persons")
        note3 = Note(id=uuid4(), user_id=user.id, content="Note without persons")
        async_db_session.add_all([person1, person2, note1, note2, note3])
        await async_db_session.commit()

        # Search for notes about person1
        request = NoteAdvancedSearchRequest(person_ids=[person1.id], person_mode="any")
        results = await advanced_search_notes(
            async_db_session, user_id=user.id, request=request
        )

        # Note: This test verifies the structure but actual person associations
        # would be created through weak links in a real scenario
        assert isinstance(results, list)

    async def test_advanced_search_sort_order(self, async_db_session):
        """Test advanced search with different sort orders"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        now = utc_now()
        earlier = now - timedelta(hours=1)
        later = now + timedelta(hours=1)

        note1 = Note(
            id=uuid4(), user_id=user.id, content="Earlier note", created_at=earlier
        )
        note2 = Note(
            id=uuid4(), user_id=user.id, content="Later note", created_at=later
        )
        async_db_session.add_all([note1, note2])
        await async_db_session.commit()

        # Descending order (default)
        request_desc = NoteAdvancedSearchRequest(sort_order="desc")
        results_desc = await advanced_search_notes(
            async_db_session, user_id=user.id, request=request_desc
        )

        assert len(results_desc) == 2
        assert results_desc[0][0].content == "Later note"  # Most recent first

        # Ascending order
        request_asc = NoteAdvancedSearchRequest(sort_order="asc")
        results_asc = await advanced_search_notes(
            async_db_session, user_id=user.id, request=request_asc
        )

        assert len(results_asc) == 2
        assert results_asc[0][0].content == "Earlier note"  # Oldest first

    async def test_batch_create_notes_success(self, async_db_session):
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        inputs = [
            NoteCreate(content="Bulk note 1"),
            NoteCreate(content="Bulk note 2"),
        ]

        created, failed = await batch_create_notes(
            async_db_session, user_id=user.id, note_inputs=inputs
        )

        assert len(created) == 2
        assert failed == []
        result = await async_db_session.execute(
            select(Note).where(Note.user_id == user.id).order_by(Note.created_at)
        )
        persisted = result.scalars().all()
        assert len(persisted) == 2
        assert persisted[0].content == "Bulk note 1"

    async def test_batch_create_notes_collects_failures(
        self, async_db_session, monkeypatch
    ):
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        inputs = [
            NoteCreate(content="ok"),
            NoteCreate(content="bad"),
            NoteCreate(content="still ok"),
        ]

        original_create_note = note_service.create_note

        async def fake_create_note(db, *, user_id, note_in):
            if note_in.content == "bad":
                raise TagNotFoundError("invalid tag")
            return await original_create_note(db, user_id=user_id, note_in=note_in)

        monkeypatch.setattr("app.handlers.notes.create_note", fake_create_note)

        created, failed = await batch_create_notes(
            async_db_session, user_id=user.id, note_inputs=inputs
        )

        assert len(created) == 1
        assert len(failed) == 2
        assert failed[0]["index"] == 2
        assert failed[0]["content"] == "bad"
        assert failed[0]["error"] == "invalid tag"
        assert failed[1]["index"] == 3
        assert failed[1]["error"]

    async def test_update_note_with_null_task_id(self, async_db_session):
        """Test updating note to clear task association"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()  # Commit user first to satisfy foreign key constraint

        vision = Vision(id=uuid4(), user_id=user.id, name="Test Vision")
        async_db_session.add(vision)
        await async_db_session.commit()

        task = Task(
            id=uuid4(), user_id=user.id, vision_id=vision.id, content="Test Task"
        )
        note = Note(id=uuid4(), user_id=user.id, content="Test note")
        async_db_session.add_all([task, note])
        await async_db_session.commit()

        # Initially associate with task
        update_data = NoteUpdate(task_id=task.id)
        await update_note(
            async_db_session, user_id=user.id, note_id=note.id, update_in=update_data
        )

        # Then clear the association
        update_data_clear = NoteUpdate(task_id=None)
        cleared_note = await update_note(
            async_db_session,
            user_id=user.id,
            note_id=note.id,
            update_in=update_data_clear,
        )

        assert cleared_note.id == note.id

    async def test_update_note_replaces_actual_events(self, async_db_session):
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        event_one = ActualEvent(
            id=uuid4(),
            user_id=user.id,
            title="Work",
            start_time=datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc),
            end_time=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
            dimension_id=None,
            tracking_method="manual",
        )
        event_two = ActualEvent(
            id=uuid4(),
            user_id=user.id,
            title="Exercise",
            start_time=datetime(2025, 1, 1, 11, 0, tzinfo=timezone.utc),
            end_time=datetime(2025, 1, 1, 11, 30, tzinfo=timezone.utc),
            dimension_id=None,
            tracking_method="manual",
        )
        note = Note(id=uuid4(), user_id=user.id, content="Daily wrap")
        async_db_session.add_all([event_one, event_two, note])
        await async_db_session.commit()

        await update_note(
            async_db_session,
            user_id=user.id,
            note_id=note.id,
            update_in=NoteUpdate(actual_event_ids=[event_one.id]),
        )

        await update_note(
            async_db_session,
            user_id=user.id,
            note_id=note.id,
            update_in=NoteUpdate(actual_event_ids=[event_two.id]),
        )

        result = await async_db_session.execute(
            select(Association).where(
                Association.source_model == "Note",
                Association.source_id == note.id,
                Association.target_model == "ActualEvent",
            )
        )
        linked_ids = {record.target_id for record in result.scalars().all()}
        assert linked_ids == {event_two.id}
