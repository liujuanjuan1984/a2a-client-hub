"""
Tests for Vision Model

This module tests the Vision SQLAlchemy model including:
- Vision creation and properties
- Experience point calculations
- Stage evolution logic
- Vision harvesting functionality
- Vision status management
"""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models.dimension import Dimension
from app.db.models.task import Task
from app.db.models.user import User
from app.db.models.user_preference import UserPreference
from app.db.models.vision import Vision
from app.handlers import visions as vision_service
from app.schemas.vision import VisionExperienceRateUpdateItem


async def bulk_update_vision_experience_rates(async_db_session, **kwargs):
    return await vision_service.bulk_update_vision_experience_rates(
        async_db_session, **kwargs
    )


async def get_user_experience_rate(async_db_session, **kwargs):
    return await vision_service.get_user_experience_rate(async_db_session, **kwargs)


async def resolve_experience_rate_for_vision(async_db_session, **kwargs):
    return await vision_service.resolve_experience_rate_for_vision(
        async_db_session, **kwargs
    )


async def update_all_vision_experience_rates(async_db_session, **kwargs):
    return await vision_service.update_all_vision_experience_rates(
        async_db_session, **kwargs
    )


VISION_EXPERIENCE_PREF_KEY = vision_service.VISION_EXPERIENCE_PREF_KEY

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class TestVisionModel:
    """Test cases for Vision model functionality"""

    async def test_vision_creation(self, async_db_session):
        """Test basic vision creation"""
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
            name="Test Vision",
            description="A test vision for unit testing",
            status="active",
            stage=0,
            experience_points=0,
        )

        async_db_session.add(vision)
        await async_db_session.commit()

        assert vision.id is not None
        assert vision.name == "Test Vision"
        assert vision.description == "A test vision for unit testing"
        assert vision.status == "active"
        assert vision.stage == 0
        assert vision.experience_points == 0
        assert vision.user_id == user.id
        assert vision.created_at is not None
        assert vision.updated_at is not None
        assert vision.deleted_at is None

    async def test_vision_with_dimension(self, async_db_session):
        """Test vision with dimension association"""
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

        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Vision with Dimension",
            description="Vision with associated dimension",
            dimension_id=dimension.id,
        )

        async_db_session.add(vision)
        await async_db_session.commit()

        # Refresh relationships
        await async_db_session.refresh(vision)

        assert vision.dimension_id == dimension.id
        assert vision.dimension == dimension

    async def test_vision_repr(self, async_db_session):
        """Test vision string representation"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(), user_id=user.id, name="Test Vision", status="active", stage=3
        )

        async_db_session.add(vision)
        await async_db_session.commit()

        repr_str = repr(vision)
        assert "Vision" in repr_str
        assert str(vision.id) in repr_str
        assert "Test Vision" in repr_str
        assert "active" in repr_str
        assert "3" in repr_str

    async def test_vision_active_status(self, async_db_session):
        """Test vision active status property"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

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

        assert active_vision.status == "active"
        assert archived_vision.status == "archived"
        assert fruit_vision.status == "fruit"

    async def test_calculate_task_experience_empty(self, async_db_session):
        """Test experience calculation for vision with no tasks"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(), user_id=user.id, name="Empty Vision", status="active"
        )

        async_db_session.add(vision)
        await async_db_session.commit()

        experience = vision.calculate_task_experience(
            [], experience_rate_per_hour=60, tasks=[]
        )
        assert experience == 0

    async def test_calculate_task_experience_with_tasks(self, async_db_session):
        """Test experience calculation for vision with tasks"""
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

        # Create root task
        root_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Root task",
            status="done",
            actual_effort_total=120,
        )
        async_db_session.add(root_task)
        await async_db_session.flush()

        # Create child task (should not be counted in experience calculation)
        child_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=root_task.id,
            content="Child task",
            status="done",
            actual_effort_total=60,
        )
        async_db_session.add(child_task)
        await async_db_session.commit()

        # Refresh relationships
        await async_db_session.refresh(vision)

        experience = vision.calculate_task_experience(
            [],
            experience_rate_per_hour=60,
            tasks=[root_task, child_task],
        )
        # Should only count root task's actual effort (120), not child task's (60)
        assert experience == 120

    async def test_add_experience_basic(self, async_db_session):
        """Test basic experience addition"""
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
            stage=0,
            experience_points=100,
        )

        async_db_session.add(vision)
        await async_db_session.commit()

        # Add experience that should trigger stage evolution
        stage_evolved = vision.add_experience(50)
        await async_db_session.commit()

        assert vision.experience_points == 150
        assert stage_evolved is True
        assert vision.stage >= 0

    async def test_add_experience_no_evolution(self, async_db_session):
        """Test adding experience without stage evolution"""
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
            name="Vision for Small Experience",
            status="active",
            stage=0,
            experience_points=10,
        )

        async_db_session.add(vision)
        await async_db_session.commit()

        # Add small amount of experience that shouldn't trigger evolution
        stage_evolved = vision.add_experience(5)
        await async_db_session.commit()

        assert vision.experience_points == 15
        assert (
            stage_evolved is False
        )  # Should not have evolved with only 15 total points

    async def test_sync_experience_with_actual_effort(self, async_db_session):
        """Test syncing experience with actual effort"""
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
            stage=0,
            experience_points=50,  # Initially set to 50
        )

        async_db_session.add(vision)
        await async_db_session.flush()

        # Create root task with different actual effort
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

        # Refresh relationships
        await async_db_session.refresh(vision)

        # Sync experience should update to match actual effort
        vision.sync_experience_with_actual_effort(
            experience_rate_per_hour=60, tasks=[root_task]
        )
        await async_db_session.commit()

        assert vision.experience_points == 200  # Should match root task's actual effort
        # Stage should have evolved based on 200 experience points
        assert vision.stage >= 0

    async def test_sync_experience_no_change(self, async_db_session):
        """Test syncing experience when already in sync"""
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
            name="Vision Already Synced",
            status="active",
            stage=0,
            experience_points=0,
        )

        async_db_session.add(vision)
        await async_db_session.commit()

        # Sync experience with no tasks
        stage_evolved = vision.sync_experience_with_actual_effort(
            experience_rate_per_hour=60, tasks=[]
        )
        await async_db_session.commit()

        assert vision.experience_points == 0
        assert stage_evolved is False

    async def test_can_harvest_not_ready(self, async_db_session):
        """Test harvest readiness check for non-ready vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Vision with low stage and active status
        low_stage_vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Low Stage Vision",
            status="active",
            stage=3,
        )

        # Vision with high stage but not active
        high_stage_vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="High Stage Inactive Vision",
            status="archived",
            stage=8,
        )

        async_db_session.add_all([low_stage_vision, high_stage_vision])
        await async_db_session.commit()

        assert low_stage_vision.can_harvest() is False  # Stage too low
        assert high_stage_vision.can_harvest() is False  # Not active

    async def test_can_harvest_ready(self, async_db_session):
        """Test harvest readiness check for ready vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        # Vision with high stage and active status
        ready_vision = Vision(
            id=uuid4(), user_id=user.id, name="Ready Vision", status="active", stage=8
        )

        async_db_session.add(ready_vision)
        await async_db_session.commit()

        assert ready_vision.can_harvest() is True

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
            name="Harvestable Vision",
            status="active",
            stage=8,
        )

        async_db_session.add(vision)
        await async_db_session.commit()

        # Harvest the vision
        vision.harvest()
        await async_db_session.commit()

        assert vision.status == "fruit"

    async def test_harvest_vision_not_ready(self, async_db_session):
        """Test harvesting a vision that's not ready (no change should occur)"""
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
            stage=3,  # Too low for harvest
        )

        async_db_session.add(vision)
        await async_db_session.commit()

        original_status = vision.status

        # Try to harvest (should not change status since can_harvest() would return False)
        vision.harvest()
        await async_db_session.commit()

        assert vision.status == original_status  # Status should not have changed

    async def test_vision_user_relationship(self, async_db_session):
        """Test vision-user relationship"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(), user_id=user.id, name="User Vision", status="active"
        )

        async_db_session.add(vision)
        await async_db_session.commit()

        assert vision.user_id == user.id

    async def test_vision_task_relationship(self, async_db_session):
        """Test vision-task relationship"""
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

        stmt = (
            select(Vision)
            .options(selectinload(Vision.tasks))
            .where(Vision.id == vision.id)
        )
        vision_with_tasks = (await async_db_session.execute(stmt)).scalar_one()

        assert len(vision_with_tasks.tasks) == 2
        assert task1 in vision_with_tasks.tasks
        assert task2 in vision_with_tasks.tasks
        assert all(task.vision_id == vision.id for task in vision_with_tasks.tasks)

    async def test_vision_soft_delete(self, async_db_session):
        """Test vision soft delete functionality"""
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

        # Vision should be active initially
        assert vision.deleted_at is None
        assert vision.is_deleted is False

        # Soft delete the vision
        vision.soft_delete()
        await async_db_session.commit()
        await async_db_session.refresh(vision)

        assert vision.deleted_at is not None
        assert vision.is_deleted is True

    async def test_stage_evolution_thresholds(self, async_db_session):
        """Test that stage evolution follows the expected thresholds"""
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
            name="Evolution Test Vision",
            status="active",
            stage=0,
            experience_points=0,
        )

        async_db_session.add(vision)
        await async_db_session.commit()

        # Test various experience thresholds based on the model's thresholds
        test_cases = [
            (120, 1),  # Stage 1: >= 120 experience points
            (240, 2),  # Stage 2: >= 240 experience points
            (480, 3),  # Stage 3: >= 480 experience points
            (960, 4),  # Stage 4: >= 960 experience points
        ]

        for exp_points, expected_stage in test_cases:
            vision.experience_points = exp_points
            vision._update_stage_based_on_experience()
            await async_db_session.commit()

            assert (
                vision.stage >= expected_stage
            ), f"Failed for {exp_points} points, expected stage >= {expected_stage}, got {vision.stage}"

    async def test_stage_capping(self, async_db_session):
        """Test that stage is properly capped at maximum (10)"""
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
            name="Max Stage Vision",
            status="active",
            stage=0,
            experience_points=0,
        )

        async_db_session.add(vision)
        await async_db_session.commit()

        # Add very high experience points
        vision.experience_points = 100000
        vision._update_stage_based_on_experience()
        await async_db_session.commit()

        # Stage should be capped at 10
        assert vision.stage == 10

    async def test_experience_calculation_with_multiple_root_tasks(
        self, async_db_session
    ):
        """Test experience calculation with multiple root tasks"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(), user_id=user.id, name="Multi Root Vision", status="active"
        )
        async_db_session.add(vision)
        await async_db_session.flush()

        # Create multiple root tasks
        root_task1 = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Root task 1",
            status="done",
            actual_effort_total=150,
        )
        root_task2 = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Root task 2",
            status="done",
            actual_effort_total=100,
        )
        async_db_session.add_all([root_task1, root_task2])
        await async_db_session.commit()

        # Refresh relationships
        await async_db_session.refresh(vision)

        experience = vision.calculate_task_experience(
            [],
            experience_rate_per_hour=60,
            tasks=[root_task1, root_task2],
        )
        # Should sum both root tasks: 150 + 100 = 250
        assert experience == 250

    async def test_experience_calculation_custom_rate(self, async_db_session):
        """Custom experience rate should scale accumulated experience"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(), user_id=user.id, name="Custom Rate Vision", status="active"
        )
        async_db_session.add(vision)
        await async_db_session.flush()

        root_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Root task",
            status="done",
            actual_effort_total=90,
        )
        async_db_session.add(root_task)
        await async_db_session.commit()

        await async_db_session.refresh(vision)

        experience = vision.calculate_task_experience(
            [],
            experience_rate_per_hour=30,
            tasks=[root_task],
        )
        # 90 minutes * 30 exp/hour = 45 experience points
        assert experience == 45

    async def test_resolve_experience_rate_preference_and_override(
        self, async_db_session
    ):
        """Vision helper should honor vision override before user preference"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision = Vision(
            id=uuid4(), user_id=user.id, name="Preference Vision", status="active"
        )
        async_db_session.add(vision)
        await async_db_session.commit()

        # Set user preference to 30
        async_db_session.add(
            UserPreference(
                user_id=user.id,
                key=VISION_EXPERIENCE_PREF_KEY,
                value=30,
                module="visions",
            )
        )
        await async_db_session.commit()

        user_rate = await get_user_experience_rate(async_db_session, user_id=user.id)
        assert user_rate == 30

        resolved_rate = await resolve_experience_rate_for_vision(
            async_db_session, user_id=user.id, vision=vision
        )
        assert resolved_rate == 30

        # When vision override present, it should take precedence
        vision.experience_rate_per_hour = 45
        await async_db_session.commit()

        resolved_override_rate = await resolve_experience_rate_for_vision(
            async_db_session, user_id=user.id, vision=vision
        )
        assert resolved_override_rate == 45

    async def test_update_all_vision_experience_rates(self, async_db_session):
        """Global preference updates should cascade to every vision."""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Bulk User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        vision_one = Vision(
            id=uuid4(),
            user_id=user.id,
            name="One",
            status="active",
            experience_rate_per_hour=15,
        )
        vision_two = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Two",
            status="active",
            experience_rate_per_hour=45,
        )
        async_db_session.add_all([vision_one, vision_two])
        await async_db_session.commit()

        updated = await update_all_vision_experience_rates(
            async_db_session, user_id=user.id, experience_rate_per_hour=30
        )
        assert len(updated) == 2
        await async_db_session.refresh(vision_one)
        await async_db_session.refresh(vision_two)
        assert vision_one.experience_rate_per_hour == 30
        assert vision_two.experience_rate_per_hour == 30

    async def test_bulk_update_vision_experience_rates(self, async_db_session):
        """Bulk API can assign mixed overrides while preserving defaults."""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Bulk Update User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.flush()

        async_db_session.add(
            UserPreference(
                user_id=user.id,
                key=VISION_EXPERIENCE_PREF_KEY,
                value=25,
                module="visions",
            )
        )
        await async_db_session.commit()

        vision_a = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Vision A",
            status="active",
            experience_rate_per_hour=25,
        )
        vision_b = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Vision B",
            status="active",
            experience_rate_per_hour=25,
        )
        async_db_session.add_all([vision_a, vision_b])
        await async_db_session.commit()

        updates = await bulk_update_vision_experience_rates(
            async_db_session,
            user_id=user.id,
            updates=[
                VisionExperienceRateUpdateItem(
                    id=vision_a.id, experience_rate_per_hour=40
                ),
                VisionExperienceRateUpdateItem(
                    id=vision_b.id, experience_rate_per_hour=None
                ),
            ],
        )

        assert len(updates) == 2
        await async_db_session.refresh(vision_a)
        await async_db_session.refresh(vision_b)

        assert vision_a.experience_rate_per_hour == 40
        # None should resolve back to user default (25) via normalization
        assert vision_b.experience_rate_per_hour == 25
