"""
Tests for Vision Handlers

This module tests the vision business logic handlers including:
- CRUD operations (create, read, update, delete)
- Vision experience management
- Vision harvesting functionality
- Vision statistics and queries
- Person associations
- Vision status management
"""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models.dimension import Dimension
from app.db.models.person import Person
from app.db.models.task import Task
from app.db.models.user import User
from app.db.models.vision import Vision
from app.handlers import visions as vision_service
from app.schemas.vision import (
    VisionCreate,
    VisionExperienceUpdate,
    VisionHarvestRequest,
    VisionUpdate,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def create_vision(async_db_session, **kwargs):
    return await vision_service.create_vision(async_db_session, **kwargs)


async def list_visions(async_db_session, **kwargs):
    return await vision_service.list_visions(async_db_session, **kwargs)


async def get_vision(async_db_session, **kwargs):
    return await vision_service.get_vision(async_db_session, **kwargs)


async def get_vision_with_tasks(async_db_session, **kwargs):
    return await vision_service.get_vision_with_tasks(async_db_session, **kwargs)


async def update_vision(async_db_session, **kwargs):
    return await vision_service.update_vision(async_db_session, **kwargs)


async def delete_vision(async_db_session, **kwargs):
    return await vision_service.delete_vision(async_db_session, **kwargs)


async def add_experience_to_vision(async_db_session, **kwargs):
    return await vision_service.add_experience_to_vision(async_db_session, **kwargs)


async def sync_vision_experience(async_db_session, **kwargs):
    return await vision_service.sync_vision_experience(async_db_session, **kwargs)


async def harvest_vision(async_db_session, **kwargs):
    return await vision_service.harvest_vision(async_db_session, **kwargs)


async def get_vision_stats(async_db_session, **kwargs):
    return await vision_service.get_vision_stats(async_db_session, **kwargs)


InvalidVisionStatusError = vision_service.InvalidVisionStatusError
VisionAlreadyExistsError = vision_service.VisionAlreadyExistsError
VisionNotFoundError = vision_service.VisionNotFoundError
VisionNotReadyForHarvestError = vision_service.VisionNotReadyForHarvestError


class TestVisionHandlers:
    """Test cases for Vision handler functions"""

    async def test_create_vision_basic(self, async_db_session):
        """Test basic vision creation"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        vision_data = VisionCreate(
            name="Test Vision", description="A test vision for unit testing"
        )

        vision = await create_vision(
            async_db_session, user_id=user.id, vision_in=vision_data
        )

        assert vision.id is not None
        assert vision.name == "Test Vision"
        assert vision.description == "A test vision for unit testing"
        assert vision.user_id == user.id
        assert vision.status == "active"  # Default status
        assert vision.stage == 0  # Default stage
        assert vision.experience_points == 0  # Default experience

    async def test_create_vision_with_dimension(self, async_db_session):
        """Test creating vision with dimension"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()  # Commit user first to satisfy foreign key constraint

        dimension = Dimension(
            id=uuid4(), user_id=user.id, name="Test Dimension", color="#FF0000"
        )
        async_db_session.add(dimension)
        await async_db_session.commit()

        vision_data = VisionCreate(
            name="Vision with Dimension",
            description="Vision with associated dimension",
            dimension_id=dimension.id,
        )

        vision = await create_vision(
            async_db_session, user_id=user.id, vision_in=vision_data
        )

        assert vision.dimension_id == dimension.id

    async def test_create_vision_duplicate_name(self, async_db_session):
        """Test creating vision with duplicate name"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Create first vision
        vision1 = Vision(
            id=uuid4(), user_id=user.id, name="Duplicate Vision", status="active"
        )
        async_db_session.add(vision1)
        await async_db_session.commit()

        # Try to create second vision with same name
        vision_data = VisionCreate(
            name="Duplicate Vision", description="This should fail"
        )

        with pytest.raises(VisionAlreadyExistsError):
            await create_vision(
                async_db_session, user_id=user.id, vision_in=vision_data
            )

    async def test_create_vision_with_persons(self, async_db_session):
        """Test creating vision with person associations"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()  # Commit user first to satisfy foreign key constraint

        person1 = Person(id=uuid4(), user_id=user.id, name="Person 1")
        person2 = Person(id=uuid4(), user_id=user.id, name="Person 2")
        async_db_session.add_all([person1, person2])
        await async_db_session.commit()

        vision_data = VisionCreate(
            name="Vision with Persons",
            description="Vision with associated persons",
            person_ids=[str(person1.id), str(person2.id)],
        )

        vision = await create_vision(
            async_db_session, user_id=user.id, vision_in=vision_data
        )

        assert vision.id is not None
        # Persons should be associated through weak links (tested via response loading)

    async def test_create_vision_invalid_person_ids(self, async_db_session):
        """Test creating vision with invalid person IDs"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        vision_data = VisionCreate(
            name="Vision with Invalid Persons",
            description="Vision with non-existent person IDs",
            person_ids=[str(uuid4()), str(uuid4())],  # Non-existent person IDs
        )

        with pytest.raises(VisionNotFoundError):
            await create_vision(
                async_db_session, user_id=user.id, vision_in=vision_data
            )

    async def test_get_vision(self, async_db_session):
        """Test getting a specific vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(), user_id=user.id, name="Test Vision", status="active"
        )
        async_db_session.add(vision)
        await async_db_session.commit()

        retrieved_vision = await get_vision(
            async_db_session, user_id=user.id, vision_id=vision.id
        )

        assert retrieved_vision is not None
        assert retrieved_vision.id == vision.id
        assert retrieved_vision.name == "Test Vision"

    async def test_get_vision_not_found(self, async_db_session):
        """Test getting non-existent vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        result = await get_vision(async_db_session, user_id=user.id, vision_id=uuid4())
        assert result is None

    async def test_list_visions_basic(self, async_db_session):
        """Test basic vision listing"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Create multiple visions
        visions = []
        for i in range(3):
            vision = Vision(
                id=uuid4(), user_id=user.id, name=f"Vision {i+1}", status="active"
            )
            visions.append(vision)
        async_db_session.add_all(visions)
        await async_db_session.commit()

        result_visions = await list_visions(async_db_session, user_id=user.id)
        assert len(result_visions) == 3
        assert all(vision.user_id == user.id for vision in result_visions)

    async def test_list_visions_with_status_filter(self, async_db_session):
        """Test vision listing with status filter"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Create visions with different statuses
        active_vision = Vision(
            id=uuid4(), user_id=user.id, name="Active Vision", status="active"
        )
        archived_vision = Vision(
            id=uuid4(), user_id=user.id, name="Archived Vision", status="archived"
        )
        fruit_vision = Vision(
            id=uuid4(), user_id=user.id, name="Completed Vision", status="fruit"
        )
        async_db_session.add_all([active_vision, archived_vision, fruit_vision])
        await async_db_session.commit()

        # Filter by status
        active_visions = await list_visions(
            async_db_session, user_id=user.id, status_filter="active"
        )
        assert len(active_visions) == 1
        assert active_visions[0].status == "active"

        archived_visions = await list_visions(
            async_db_session, user_id=user.id, status_filter="archived"
        )
        assert len(archived_visions) == 1
        assert archived_visions[0].status == "archived"

    async def test_list_visions_invalid_status_filter(self, async_db_session):
        """Test vision listing with invalid status filter"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        with pytest.raises(InvalidVisionStatusError):
            await list_visions(
                async_db_session, user_id=user.id, status_filter="invalid_status"
            )

    async def test_list_visions_with_pagination(self, async_db_session):
        """Test vision listing with pagination"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Create more visions than will fit in one page
        visions = []
        for i in range(5):
            vision = Vision(
                id=uuid4(), user_id=user.id, name=f"Vision {i+1}", status="active"
            )
            visions.append(vision)
        async_db_session.add_all(visions)
        await async_db_session.commit()

        # Test pagination
        page1 = await list_visions(async_db_session, user_id=user.id, skip=0, limit=2)
        page2 = await list_visions(async_db_session, user_id=user.id, skip=2, limit=2)
        page3 = await list_visions(async_db_session, user_id=user.id, skip=4, limit=2)

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1

        # Ensure no overlaps
        page1_ids = {v.id for v in page1}
        page2_ids = {v.id for v in page2}
        page3_ids = {v.id for v in page3}

        assert len(page1_ids.intersection(page2_ids)) == 0
        assert len(page2_ids.intersection(page3_ids)) == 0
        assert len(page1_ids.intersection(page3_ids)) == 0

    async def test_get_vision_with_tasks(self, async_db_session):
        """Test getting vision with its tasks"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(), user_id=user.id, name="Vision with Tasks", status="active"
        )
        async_db_session.add(vision)
        await async_db_session.flush()

        # Create tasks for the vision
        task1 = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Task 1",
            status="todo",
        )
        task2 = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Task 2",
            status="done",
        )
        async_db_session.add_all([task1, task2])
        await async_db_session.commit()

        result = await get_vision_with_tasks(
            async_db_session, user_id=user.id, vision_id=vision.id
        )

        assert result is not None
        assert result["id"] == vision.id
        assert len(result["tasks"]) == 2
        task_contents = [task.content for task in result["tasks"]]
        assert "Task 1" in task_contents
        assert "Task 2" in task_contents

    async def test_get_vision_with_tasks_not_found(self, async_db_session):
        """Test getting non-existent vision with tasks"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        result = await get_vision_with_tasks(
            async_db_session, user_id=user.id, vision_id=uuid4()
        )
        assert result is None

    async def test_update_vision(self, async_db_session):
        """Test updating a vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Original Vision",
            description="Original description",
            status="active",
        )
        async_db_session.add(vision)
        await async_db_session.commit()

        update_data = VisionUpdate(
            name="Updated Vision", description="Updated description", status="archived"
        )

        updated_vision = await update_vision(
            async_db_session,
            user_id=user.id,
            vision_id=vision.id,
            update_in=update_data,
        )

        assert updated_vision.name == "Updated Vision"
        assert updated_vision.description == "Updated description"
        assert updated_vision.status == "archived"

    async def test_update_vision_not_found(self, async_db_session):
        """Test updating non-existent vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        update_data = VisionUpdate(name="Updated Vision")

        result = await update_vision(
            async_db_session, user_id=user.id, vision_id=uuid4(), update_in=update_data
        )
        assert result is None

    async def test_update_vision_duplicate_name(self, async_db_session):
        """Test updating vision to duplicate name"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision1 = Vision(id=uuid4(), user_id=user.id, name="Vision 1", status="active")
        vision2 = Vision(id=uuid4(), user_id=user.id, name="Vision 2", status="active")
        async_db_session.add_all([vision1, vision2])
        await async_db_session.commit()

        # Try to rename vision2 to vision1's name
        update_data = VisionUpdate(name="Vision 1")

        with pytest.raises(VisionAlreadyExistsError):
            await update_vision(
                async_db_session,
                user_id=user.id,
                vision_id=vision2.id,
                update_in=update_data,
            )

    async def test_delete_vision_soft(self, async_db_session):
        """Test soft deleting a vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(), user_id=user.id, name="Vision to Delete", status="active"
        )
        async_db_session.add(vision)
        await async_db_session.commit()

        # Soft delete
        result = await delete_vision(
            async_db_session, user_id=user.id, vision_id=vision.id, hard_delete=False
        )

        assert result is True
        await async_db_session.refresh(vision)
        assert vision.deleted_at is not None
        assert vision.is_deleted is True

    async def test_delete_vision_hard(self, async_db_session):
        """Test hard deleting a vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(), user_id=user.id, name="Vision to Delete", status="active"
        )
        async_db_session.add(vision)
        await async_db_session.commit()
        vision_id = vision.id

        # Hard delete
        result = await delete_vision(
            async_db_session, user_id=user.id, vision_id=vision.id, hard_delete=True
        )

        assert result is True
        verification = await async_db_session.execute(
            select(Vision).where(Vision.id == vision_id)
        )
        deleted_vision = verification.scalar_one_or_none()
        assert deleted_vision is None

    async def test_delete_vision_not_found(self, async_db_session):
        """Test deleting non-existent vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        result = await delete_vision(
            async_db_session, user_id=user.id, vision_id=uuid4()
        )
        assert result is False

    async def test_add_experience_to_vision(self, async_db_session):
        """Test adding experience to a vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Vision for Experience",
            status="active",
            experience_points=100,
        )
        async_db_session.add(vision)
        await async_db_session.commit()

        experience_data = VisionExperienceUpdate(experience_points=50)
        updated_vision = await add_experience_to_vision(
            async_db_session,
            user_id=user.id,
            vision_id=vision.id,
            experience_data=experience_data,
        )

        assert updated_vision.experience_points == 150

    async def test_add_experience_to_vision_not_found(self, async_db_session):
        """Test adding experience to non-existent vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        experience_data = VisionExperienceUpdate(experience_points=50)
        result = await add_experience_to_vision(
            async_db_session,
            user_id=user.id,
            vision_id=uuid4(),
            experience_data=experience_data,
        )
        assert result is None

    async def test_add_experience_to_inactive_vision(self, async_db_session):
        """Test adding experience to inactive vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Inactive Vision",
            status="archived",  # Not active
        )
        async_db_session.add(vision)
        await async_db_session.commit()

        experience_data = VisionExperienceUpdate(experience_points=50)

        with pytest.raises(InvalidVisionStatusError):
            await add_experience_to_vision(
                async_db_session,
                user_id=user.id,
                vision_id=vision.id,
                experience_data=experience_data,
            )

    async def test_sync_vision_experience(self, async_db_session):
        """Test syncing vision experience with actual effort"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Vision for Sync",
            status="active",
            experience_points=50,  # Initially different from actual effort
        )
        async_db_session.add(vision)
        await async_db_session.flush()

        # Create root task with actual effort
        root_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Root task",
            status="done",
            actual_effort_total=200,
        )
        async_db_session.add(root_task)
        await async_db_session.commit()

        # Sync experience
        updated_vision = await sync_vision_experience(
            async_db_session, user_id=user.id, vision_id=vision.id
        )

        assert updated_vision.experience_points == 200  # Should match actual effort

    async def test_sync_vision_experience_not_found(self, async_db_session):
        """Test syncing experience for non-existent vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        result = await sync_vision_experience(
            async_db_session, user_id=user.id, vision_id=uuid4()
        )
        assert result is None

    async def test_harvest_vision(self, async_db_session):
        """Test harvesting a ready vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Ready Vision",
            status="active",
            stage=8,  # Ready for harvest
        )
        async_db_session.add(vision)
        await async_db_session.commit()

        harvest_data = VisionHarvestRequest()
        harvested_vision = await harvest_vision(
            async_db_session,
            user_id=user.id,
            vision_id=vision.id,
            harvest_data=harvest_data,
        )

        assert harvested_vision.status == "fruit"

    async def test_harvest_vision_not_ready(self, async_db_session):
        """Test harvesting a vision that's not ready"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Not Ready Vision",
            status="active",
            stage=3,  # Not ready for harvest
        )
        async_db_session.add(vision)
        await async_db_session.commit()

        harvest_data = VisionHarvestRequest()

        with pytest.raises(VisionNotReadyForHarvestError):
            await harvest_vision(
                async_db_session,
                user_id=user.id,
                vision_id=vision.id,
                harvest_data=harvest_data,
            )

    async def test_harvest_vision_not_found(self, async_db_session):
        """Test harvesting non-existent vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        harvest_data = VisionHarvestRequest()
        result = await harvest_vision(
            async_db_session,
            user_id=user.id,
            vision_id=uuid4(),
            harvest_data=harvest_data,
        )
        assert result is None

    async def test_get_vision_stats(self, async_db_session):
        """Test getting vision statistics"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(), user_id=user.id, name="Vision for Stats", status="active"
        )
        async_db_session.add(vision)
        await async_db_session.flush()

        # Create tasks with different statuses
        todo_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Todo Task",
            status="todo",
            estimated_effort=60,
        )
        in_progress_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="In Progress Task",
            status="in_progress",
            estimated_effort=30,
        )
        done_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Done Task",
            status="done",
            estimated_effort=45,
        )
        async_db_session.add_all([todo_task, in_progress_task, done_task])
        await async_db_session.commit()

        stats = await get_vision_stats(
            async_db_session, user_id=user.id, vision_id=vision.id
        )

        assert stats.total_tasks == 3
        assert stats.todo_tasks == 1
        assert stats.in_progress_tasks == 1
        assert stats.completed_tasks == 1
        assert stats.completion_percentage == 1 / 3
        assert stats.total_estimated_effort == 135  # 60 + 30 + 45

    async def test_get_vision_stats_not_found(self, async_db_session):
        """Test getting statistics for non-existent vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        result = await get_vision_stats(
            async_db_session, user_id=user.id, vision_id=uuid4()
        )
        assert result is None

    async def test_get_vision_stats_with_hierarchical_tasks(self, async_db_session):
        """Test vision statistics with hierarchical tasks (avoid double counting)"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Vision with Hierarchical Tasks",
            status="active",
        )
        async_db_session.add(vision)
        await async_db_session.flush()

        # Create hierarchical tasks
        root_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Root Task",
            status="done",
            estimated_effort=60,
            actual_effort_total=120,  # Includes child effort
        )
        child_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=root_task.id,
            content="Child Task",
            status="done",
            estimated_effort=30,
            actual_effort_total=30,
        )
        async_db_session.add_all([root_task, child_task])
        await async_db_session.commit()

        stats = await get_vision_stats(
            async_db_session, user_id=user.id, vision_id=vision.id
        )

        # Should count both tasks for total_tasks but only root task for actual_effort
        assert stats.total_tasks == 2
        assert (
            stats.total_actual_effort == 120
        )  # Only root task's total, avoiding double counting
        assert stats.total_estimated_effort == 90  # 60 + 30 (sum of all tasks)

    async def test_update_vision_with_persons(self, async_db_session):
        """Test updating vision with person associations"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()  # Commit user first to satisfy foreign key constraint

        person1 = Person(id=uuid4(), user_id=user.id, name="Person 1")
        person2 = Person(id=uuid4(), user_id=user.id, name="Person 2")
        async_db_session.add_all([person1, person2])
        await async_db_session.commit()

        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Vision for Person Update",
            status="active",
        )
        async_db_session.add(vision)
        await async_db_session.commit()

        # Update with persons
        update_data = VisionUpdate(
            name="Updated Vision with Persons",
            person_ids=[str(person1.id), str(person2.id)],
        )

        updated_vision = await update_vision(
            async_db_session,
            user_id=user.id,
            vision_id=vision.id,
            update_in=update_data,
        )

        assert updated_vision.name == "Updated Vision with Persons"

    async def test_update_vision_clear_persons(self, async_db_session):
        """Test clearing person associations from vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()  # Commit user first to satisfy foreign key constraint

        person = Person(id=uuid4(), user_id=user.id, name="Person")
        async_db_session.add(person)
        await async_db_session.commit()

        vision = Vision(
            id=uuid4(), user_id=user.id, name="Vision with Person", status="active"
        )
        async_db_session.add(vision)
        await async_db_session.commit()

        # Update with empty person list to clear associations
        update_data = VisionUpdate(person_ids=[])

        updated_vision = await update_vision(
            async_db_session,
            user_id=user.id,
            vision_id=vision.id,
            update_in=update_data,
        )

        assert updated_vision is not None
        # Person associations should be cleared
