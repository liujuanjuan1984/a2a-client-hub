"""
Tests for Task model

This module tests the Task SQLAlchemy model including:
- Task creation and properties
- Hierarchical relationships (parent-child)
- Task status operations
- Planning cycle validation
- Task utility methods
"""

from datetime import date
from uuid import uuid4

import pytest

from app.db.models.task import Task
from app.db.models.user import User
from app.db.models.vision import Vision
from app.handlers.tasks import load_task_with_subtasks

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _load_task_tree(async_db_session, user_id, task_id, depth=2):
    task = await load_task_with_subtasks(
        async_db_session,
        user_id=user_id,
        task_id=task_id,
        max_depth=depth,
    )
    assert task is not None
    return task


class TestTaskModel:
    """Test cases for Task model functionality"""

    async def test_task_creation(self, async_db_session):
        """Test basic task creation"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Test Vision",
            description="Test vision description",
        )
        async_db_session.add(user)
        async_db_session.add(vision)
        await async_db_session.flush()

        task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Test task content",
            status="todo",
            priority=1,
            estimated_effort=60,
            display_order=0,
            notes_count=0,
        )

        async_db_session.add(task)
        await async_db_session.commit()

        assert task.id is not None
        assert task.content == "Test task content"
        assert task.notes_count == 0
        assert task.status == "todo"
        assert task.priority == 1
        assert task.estimated_effort == 60
        assert task.vision_id == vision.id
        assert task.user_id == user.id
        assert task.parent_task_id is None
        assert task.display_order == 0
        assert task.actual_effort_self == 0
        assert task.actual_effort_total == 0
        assert task.created_at is not None
        assert task.updated_at is not None

    async def test_task_with_parent(self, async_db_session):
        """Test creating task with parent relationship"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Test Vision",
            description="Test vision description",
        )
        async_db_session.add(user)
        async_db_session.add(vision)
        await async_db_session.flush()

        parent_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Parent task",
            status="todo",
        )
        async_db_session.add(parent_task)
        await async_db_session.flush()

        child_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=parent_task.id,
            content="Child task",
            status="todo",
        )
        async_db_session.add(child_task)
        await async_db_session.commit()

        parent_task = await _load_task_tree(
            async_db_session, user.id, parent_task.id, depth=1
        )
        child_task = await _load_task_tree(
            async_db_session, user.id, child_task.id, depth=1
        )

        assert child_task.parent_task_id == parent_task.id
        assert child_task.parent_task == parent_task
        assert len(parent_task.subtasks) == 1
        assert parent_task.subtasks[0] == child_task

    async def test_task_hierarchy_properties(self, async_db_session):
        """Test task hierarchy utility properties"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Test Vision",
            description="Test vision description",
        )
        async_db_session.add(user)
        async_db_session.add(vision)
        await async_db_session.flush()

        # Create root task
        root_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Root task",
            status="todo",
        )
        async_db_session.add(root_task)
        await async_db_session.flush()

        # Create child task
        child_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=root_task.id,
            content="Child task",
            status="todo",
        )
        async_db_session.add(child_task)
        await async_db_session.flush()

        # Create grandchild task
        grandchild_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=child_task.id,
            content="Grandchild task",
            status="todo",
        )
        async_db_session.add(grandchild_task)
        await async_db_session.commit()

        root_task = await _load_task_tree(
            async_db_session, user.id, root_task.id, depth=3
        )
        child_task = await _load_task_tree(
            async_db_session, user.id, child_task.id, depth=2
        )
        grandchild_task = await _load_task_tree(
            async_db_session, user.id, grandchild_task.id, depth=1
        )

        # Test is_root_task property
        assert root_task.is_root_task is True
        assert child_task.is_root_task is False
        assert grandchild_task.is_root_task is False

        # Test is_leaf_task property
        assert root_task.is_leaf_task is False
        assert child_task.is_leaf_task is False
        assert grandchild_task.is_leaf_task is True

        # Test depth property
        assert root_task.depth == 0
        assert child_task.depth == 1
        assert grandchild_task.depth == 2

    async def test_get_all_subtasks(self, async_db_session):
        """Test recursive subtask retrieval"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Test Vision",
            description="Test vision description",
        )
        async_db_session.add(user)
        async_db_session.add(vision)
        await async_db_session.flush()

        # Create task hierarchy
        root_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Root task",
            status="todo",
        )
        async_db_session.add(root_task)
        await async_db_session.flush()

        child_task1 = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=root_task.id,
            content="Child task 1",
            status="todo",
        )
        child_task2 = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=root_task.id,
            content="Child task 2",
            status="todo",
        )
        async_db_session.add_all([child_task1, child_task2])
        await async_db_session.flush()

        grandchild_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=child_task1.id,
            content="Grandchild task",
            status="todo",
        )
        async_db_session.add(grandchild_task)
        await async_db_session.commit()

        root_task = await _load_task_tree(
            async_db_session, user.id, root_task.id, depth=3
        )

        # Test get_all_subtasks
        all_subtasks = root_task.get_all_subtasks(include_self=False)
        assert len(all_subtasks) == 3
        assert child_task1 in all_subtasks
        assert child_task2 in all_subtasks
        assert grandchild_task in all_subtasks

        # Test include_self=True
        all_with_self = root_task.get_all_subtasks(include_self=True)
        assert len(all_with_self) == 4
        assert root_task in all_with_self

    async def test_completion_percentage(self, async_db_session):
        """Test completion percentage calculation"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Test Vision",
            description="Test vision description",
        )
        async_db_session.add(user)
        async_db_session.add(vision)
        await async_db_session.flush()

        # Test leaf task completion
        leaf_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Leaf task",
            status="todo",
        )
        async_db_session.add(leaf_task)
        await async_db_session.commit()

        leaf_task = await _load_task_tree(
            async_db_session, user.id, leaf_task.id, depth=1
        )
        assert leaf_task.get_completion_percentage() == 0.0

        leaf_task.status = "done"
        await async_db_session.commit()
        assert leaf_task.get_completion_percentage() == 1.0

        # Test parent task completion
        parent_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Parent task",
            status="todo",
        )
        async_db_session.add(parent_task)
        await async_db_session.flush()

        child1 = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=parent_task.id,
            content="Child 1",
            status="todo",
        )
        child2 = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=parent_task.id,
            content="Child 2",
            status="todo",
        )
        async_db_session.add_all([child1, child2])
        await async_db_session.commit()

        parent_task = await _load_task_tree(
            async_db_session, user.id, parent_task.id, depth=2
        )

        # Initially no subtasks completed
        assert parent_task.get_completion_percentage() == 0.0

        # Complete one subtask
        child1.status = "done"
        await async_db_session.commit()
        assert parent_task.get_completion_percentage() == 0.5

        # Complete both subtasks
        child2.status = "done"
        await async_db_session.commit()
        assert parent_task.get_completion_percentage() == 1.0

    async def test_can_complete_and_complete(self, async_db_session):
        """Test task completion logic"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Test Vision",
            description="Test vision description",
        )
        async_db_session.add(user)
        async_db_session.add(vision)
        await async_db_session.flush()

        # Test leaf task completion
        leaf_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Leaf task",
            status="todo",
        )
        async_db_session.add(leaf_task)
        await async_db_session.commit()

        leaf_task = await _load_task_tree(
            async_db_session, user.id, leaf_task.id, depth=1
        )

        assert leaf_task.can_complete() is True
        assert leaf_task.complete() is True
        assert leaf_task.status == "done"
        assert leaf_task.complete() is False  # Already completed

        # Test parent task completion
        parent_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Parent task",
            status="todo",
        )
        async_db_session.add(parent_task)
        await async_db_session.flush()

        child = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=parent_task.id,
            content="Child task",
            status="todo",
        )
        async_db_session.add(child)
        await async_db_session.commit()

        parent_task = await _load_task_tree(
            async_db_session, user.id, parent_task.id, depth=2
        )

        # Parent cannot be completed while child is incomplete
        assert parent_task.can_complete() is False
        assert parent_task.complete() is False
        assert parent_task.status == "todo"

        # Complete child first
        child.status = "done"
        await async_db_session.commit()

        # Now parent can be completed
        assert parent_task.can_complete() is True
        assert parent_task.complete() is True
        assert parent_task.status == "done"

    async def test_planning_cycle_validation(self, async_db_session):
        """Test planning cycle validation"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Test Vision",
            description="Test vision description",
        )
        async_db_session.add(user)
        async_db_session.add(vision)
        await async_db_session.flush()

        # Test valid planning cycle
        task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Task with planning cycle",
            status="todo",
            planning_cycle_type="week",
            planning_cycle_days=7,
            planning_cycle_start_date=date.today(),
        )
        async_db_session.add(task)
        await async_db_session.commit()

        assert task.validate_planning_cycle() is True

        # Test missing planning cycle (all None) - should be valid
        task_no_cycle = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Task without planning cycle",
            status="todo",
        )
        async_db_session.add(task_no_cycle)
        await async_db_session.commit()

        assert task_no_cycle.validate_planning_cycle() is True

        # Test invalid planning cycle (partially filled) - should be invalid
        task_invalid_cycle = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Task with invalid planning cycle",
            status="todo",
            planning_cycle_type="week",
            planning_cycle_days=7,
            # Missing planning_cycle_start_date
        )
        async_db_session.add(task_invalid_cycle)
        await async_db_session.commit()

        assert task_invalid_cycle.validate_planning_cycle() is False

        # Test invalid cycle type
        task_invalid_type = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Task with invalid cycle type",
            status="todo",
            planning_cycle_type="invalid",
            planning_cycle_days=7,
            planning_cycle_start_date=date.today(),
        )
        async_db_session.add(task_invalid_type)
        await async_db_session.commit()

        assert task_invalid_type.validate_planning_cycle() is False

        # Test invalid days (negative)
        task_invalid_days = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Task with invalid days",
            status="todo",
            planning_cycle_type="week",
            planning_cycle_days=-1,
            planning_cycle_start_date=date.today(),
        )
        async_db_session.add(task_invalid_days)
        await async_db_session.commit()

        assert task_invalid_days.validate_planning_cycle() is False

    async def test_task_repr(self, async_db_session):
        """Test task string representation"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Test Vision",
            description="Test vision description",
        )
        async_db_session.add(user)
        async_db_session.add(vision)
        await async_db_session.flush()

        task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="This is a test task with a longer content that should be truncated",
            status="todo",
        )
        async_db_session.add(task)
        await async_db_session.commit()

        repr_str = repr(task)
        assert "Task" in repr_str
        assert str(task.id) in repr_str
        assert "This is a test task with a longer content that sho..." in repr_str
        assert "todo" in repr_str

    async def test_task_effort_fields(self, async_db_session):
        """Test effort-related fields"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Test Vision",
            description="Test vision description",
        )
        async_db_session.add(user)
        async_db_session.add(vision)
        await async_db_session.flush()

        task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Task with effort",
            status="todo",
            estimated_effort=120,
            actual_effort_self=45,
            actual_effort_total=90,
        )
        async_db_session.add(task)
        await async_db_session.commit()

        assert task.estimated_effort == 120
        assert task.actual_effort_self == 45
        assert task.actual_effort_total == 90

    async def test_soft_delete(self, async_db_session):
        """Test soft delete functionality"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Test Vision",
            description="Test vision description",
        )
        async_db_session.add(user)
        async_db_session.add(vision)
        await async_db_session.flush()

        task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Task to delete",
            status="todo",
        )
        async_db_session.add(task)
        await async_db_session.commit()

        # Task should be active initially
        assert task.deleted_at is None
        assert task.is_deleted is False

        # Soft delete the task
        task.soft_delete()
        await async_db_session.commit()

        assert task.deleted_at is not None
        assert task.is_deleted is True

    async def test_display_order_default(self, async_db_session):
        """Test display order default value"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Test Vision",
            description="Test vision description",
        )
        async_db_session.add(user)
        async_db_session.add(vision)
        await async_db_session.flush()

        task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Task with default order",
            status="todo",
        )
        async_db_session.add(task)
        await async_db_session.commit()

        assert task.display_order == 0  # Default value should be 0
