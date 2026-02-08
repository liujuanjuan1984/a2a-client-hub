"""
Tests for Task Handlers

This module tests the task business logic handlers including:
- CRUD operations (create, read, update, delete)
- Task status management
- Hierarchical task operations
- Task reordering and moving
- Task statistics and queries
- Planning cycle operations
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.db.models.person import Person
from app.db.models.task import Task
from app.db.models.user import User
from app.db.models.vision import Vision
from app.handlers import tasks as tasks_service
from app.handlers.tasks import (
    CircularReferenceError,
    InvalidStatusError,
    ParentTaskNotFoundError,
    TaskCannotBeCompletedError,
    TaskNotFoundError,
    VisionNotFoundError,
)
from app.schemas.task import (
    TaskCreate,
    TaskMoveRequest,
    TaskReorderRequest,
    TaskResponse,
    TaskStatusUpdate,
    TaskUpdate,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


@pytest.fixture(autouse=True)
def _disable_work_recalc(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.handlers.tasks._schedule_recalc_jobs", _noop)


class TestTaskHandlers:
    """Test cases for Task handler functions"""

    async def test_list_tasks_basic(self, async_db_session):
        """Test basic task listing"""
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

        # Create multiple tasks
        tasks = []
        for i in range(5):
            task = Task(
                id=uuid4(),
                user_id=user.id,
                vision_id=vision.id,
                content=f"Task {i+1}",
                status="todo",
                display_order=i,
            )
            tasks.append(task)
        async_db_session.add_all(tasks)
        await async_db_session.commit()

        # List tasks
        result_tasks = await tasks_service.list_tasks(async_db_session, user_id=user.id)
        assert len(result_tasks) == 5
        assert all(task.user_id == user.id for task in result_tasks)

    async def test_list_tasks_excludes_deleted_vision(self, async_db_session):
        """Test task listing excludes tasks from deleted visions"""
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
            content="Task 1",
            status="todo",
        )
        async_db_session.add(task)
        await async_db_session.commit()

        result_tasks = await tasks_service.list_tasks(async_db_session, user_id=user.id)
        assert len(result_tasks) == 1

        vision.soft_delete()
        await async_db_session.commit()

        result_tasks = await tasks_service.list_tasks(async_db_session, user_id=user.id)
        assert result_tasks == []

    async def test_list_tasks_with_vision_filter(self, async_db_session):
        """Test task listing with vision filter"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        vision1 = Vision(
            id=uuid4(), user_id=user.id, name="Vision 1", description="First vision"
        )
        vision2 = Vision(
            id=uuid4(), user_id=user.id, name="Vision 2", description="Second vision"
        )
        async_db_session.add(user)
        async_db_session.add_all([vision1, vision2])
        await async_db_session.flush()

        # Create tasks for different visions
        task1 = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision1.id,
            content="Task 1",
            status="todo",
        )
        task2 = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision2.id,
            content="Task 2",
            status="todo",
        )
        async_db_session.add_all([task1, task2])
        await async_db_session.commit()

        # Filter by vision
        vision1_tasks = await tasks_service.list_tasks(
            async_db_session, user_id=user.id, vision_id=vision1.id
        )
        assert len(vision1_tasks) == 1
        assert vision1_tasks[0].vision_id == vision1.id

        vision2_tasks = await tasks_service.list_tasks(
            async_db_session, user_id=user.id, vision_id=vision2.id
        )
        assert len(vision2_tasks) == 1
        assert vision2_tasks[0].vision_id == vision2.id

    async def test_list_tasks_with_status_filter(self, async_db_session):
        """Test task listing with status filter"""
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

        # Create tasks with different statuses
        todo_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Todo task",
            status="todo",
        )
        done_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Done task",
            status="done",
        )
        in_progress_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="In progress task",
            status="in_progress",
        )
        async_db_session.add_all([todo_task, done_task, in_progress_task])
        await async_db_session.commit()

        # Filter by status
        todo_tasks = await tasks_service.list_tasks(
            async_db_session, user_id=user.id, status_filter="todo"
        )
        assert len(todo_tasks) == 1
        assert todo_tasks[0].status == "todo"

        # Filter by multiple statuses
        active_tasks = await tasks_service.list_tasks(
            async_db_session, user_id=user.id, status_in="todo,in_progress"
        )
        assert len(active_tasks) == 2
        assert all(task.status in ["todo", "in_progress"] for task in active_tasks)

        # Exclude status
        non_done_tasks = await tasks_service.list_tasks(
            async_db_session, user_id=user.id, exclude_status="done"
        )
        assert len(non_done_tasks) == 2
        assert all(task.status != "done" for task in non_done_tasks)

    async def test_list_tasks_invalid_status_filter(self, async_db_session):
        """Test task listing with invalid status filter"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        with pytest.raises(InvalidStatusError):
            await tasks_service.list_tasks(
                async_db_session, user_id=user.id, status_filter="invalid_status"
            )

    async def test_create_task_basic(self, async_db_session):
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
        await async_db_session.commit()

        task_data = TaskCreate(
            vision_id=vision.id,
            content="New task",
            priority=2,
            estimated_effort=60,
        )

        task = await tasks_service.create_task(
            async_db_session, user_id=user.id, task_data=task_data
        )

        assert task.id is not None
        assert task.content == "New task"
        assert task.priority == 2
        assert task.estimated_effort == 60
        assert task.notes_count == 0
        assert task.vision_id == vision.id
        assert task.user_id == user.id
        assert task.status == "todo"  # Default status
        assert task.display_order == 0  # First task gets order 0

    async def test_create_task_returns_person_summary(self, async_db_session):
        """确保创建任务时返回的人员信息包含primary_nickname"""
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
            description="Test vision description",
        )
        async_db_session.add(vision)
        await async_db_session.flush()

        person = Person(
            id=uuid4(),
            user_id=user.id,
            name="测试成员",
            nicknames=["小张"],
        )
        async_db_session.add(person)
        await async_db_session.flush()

        task_data = TaskCreate(
            vision_id=vision.id,
            content="Task with person",
            person_ids=[str(person.id)],
        )

        task = await tasks_service.create_task(
            async_db_session, user_id=user.id, task_data=task_data
        )

        response = TaskResponse.model_validate(task)
        assert response.persons
        assert response.persons[0].id == person.id
        assert response.persons[0].primary_nickname == "小张"

    async def test_create_task_with_parent(self, async_db_session):
        """Test creating task with parent"""
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

        # Create parent task
        parent_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Parent task",
            status="todo",
            display_order=0,
        )
        async_db_session.add(parent_task)
        await async_db_session.commit()

        task_data = TaskCreate(
            vision_id=vision.id, parent_task_id=parent_task.id, content="Child task"
        )

        child_task = await tasks_service.create_task(
            async_db_session, user_id=user.id, task_data=task_data
        )

        assert child_task.parent_task_id == parent_task.id
        assert child_task.display_order == 0  # First child gets order 0

    async def test_create_task_invalid_vision(self, async_db_session):
        """Test creating task with non-existent vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        task_data = TaskCreate(vision_id=uuid4(), content="Task with invalid vision")

        with pytest.raises(VisionNotFoundError):
            await tasks_service.create_task(
                async_db_session, user_id=user.id, task_data=task_data
            )

    async def test_create_task_invalid_parent(self, async_db_session):
        """Test creating task with non-existent parent"""
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
        await async_db_session.commit()

        task_data = TaskCreate(
            vision_id=vision.id,
            parent_task_id=uuid4(),  # Non-existent parent
            content="Task with invalid parent",
        )

        with pytest.raises(ParentTaskNotFoundError):
            await tasks_service.create_task(
                async_db_session, user_id=user.id, task_data=task_data
            )

    async def test_create_task_with_planning_cycle(self, async_db_session):
        """Test creating task with planning cycle"""
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
        await async_db_session.commit()

        task_data = TaskCreate(
            vision_id=vision.id,
            content="Task with planning cycle",
            planning_cycle_type="week",
            planning_cycle_days=7,
            planning_cycle_start_date=date.today(),
        )

        task = await tasks_service.create_task(
            async_db_session, user_id=user.id, task_data=task_data
        )

        assert task.planning_cycle_type == "week"
        assert task.planning_cycle_days == 7
        assert task.planning_cycle_start_date == date.today()

    async def test_create_task_invalid_planning_cycle(self, async_db_session):
        """Test creating task with invalid planning cycle - this should fail at schema validation"""
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
        await async_db_session.commit()

        # Invalid planning cycle (missing start_date) - should fail at Pydantic validation
        with pytest.raises(Exception):  # Pydantic validation error
            TaskCreate(
                vision_id=vision.id,
                content="Task with invalid planning cycle",
                planning_cycle_type="week",
                planning_cycle_days=7
                # Missing planning_cycle_start_date
            )

    async def test_get_task(self, async_db_session):
        """Test getting a specific task"""
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
            content="Test task",
            status="todo",
        )
        async_db_session.add(task)
        await async_db_session.commit()

        retrieved_task = await tasks_service.get_task(
            async_db_session, user_id=user.id, task_id=task.id
        )

        assert retrieved_task is not None
        assert retrieved_task.id == task.id
        assert retrieved_task.content == "Test task"

    async def test_get_task_not_found(self, async_db_session):
        """Test getting non-existent task"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        with pytest.raises(TaskNotFoundError):
            await tasks_service.get_task_with_subtasks(
                async_db_session, user_id=user.id, task_id=uuid4()
            )

    async def test_update_task(self, async_db_session):
        """Test updating a task"""
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
            content="Original content",
            status="todo",
            priority=1,
        )
        async_db_session.add(task)
        await async_db_session.commit()

        update_data = TaskUpdate(
            content="Updated content", status="in_progress", priority=3
        )

        updated_task = await tasks_service.update_task(
            async_db_session, user_id=user.id, task_id=task.id, task_data=update_data
        )

        assert updated_task.content == "Updated content"
        assert updated_task.status == "in_progress"
        assert updated_task.priority == 3

    async def test_update_task_returns_person_summary(self, async_db_session):
        """确保更新任务后返回的人员信息包含primary_nickname"""
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
            description="Test vision description",
        )
        async_db_session.add(vision)
        await async_db_session.flush()

        person = Person(
            id=uuid4(),
            user_id=user.id,
            name="测试成员",
            nicknames=["小明", "阿明"],
        )
        async_db_session.add(person)
        await async_db_session.flush()

        task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Original content",
            status="todo",
            priority=1,
        )
        async_db_session.add(task)
        await async_db_session.commit()

        update_data = TaskUpdate(person_ids=[str(person.id)])

        updated_task = await tasks_service.update_task(
            async_db_session, user_id=user.id, task_id=task.id, task_data=update_data
        )

        response = TaskResponse.model_validate(updated_task)

        assert response.persons
        person_summary = response.persons[0]
        assert person_summary.id == person.id
        assert person_summary.primary_nickname == ", ".join(person.nicknames)

    async def test_update_task_not_found(self, async_db_session):
        """Test updating non-existent task"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        update_data = TaskUpdate(content="Updated content")

        with pytest.raises(TaskNotFoundError):
            await tasks_service.update_task(
                async_db_session,
                user_id=user.id,
                task_id=uuid4(),
                task_data=update_data,
            )

    async def test_update_task_circular_reference(self, async_db_session):
        """Test updating task to create circular reference"""
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

        # Create parent-child relationship
        parent_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Parent task",
            status="todo",
        )
        child_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=parent_task.id,
            content="Child task",
            status="todo",
        )
        async_db_session.add_all([parent_task, child_task])
        await async_db_session.commit()

        # Try to make parent task a child of its own child
        update_data = TaskUpdate(parent_task_id=child_task.id)

        with pytest.raises(CircularReferenceError):
            await tasks_service.update_task(
                async_db_session,
                user_id=user.id,
                task_id=parent_task.id,
                task_data=update_data,
            )

    async def test_update_task_status(self, async_db_session):
        """Test updating task status"""
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
            content="Test task",
            status="todo",
        )
        async_db_session.add(task)
        await async_db_session.commit()

        updated_task = await tasks_service.update_task_status(
            async_db_session,
            user_id=user.id,
            task_id=task.id,
            status_data=TaskStatusUpdate(status="in_progress"),
        )

        assert updated_task.status == "in_progress"

    async def test_complete_task_with_incomplete_subtasks(self, async_db_session):
        """Test completing task that has incomplete subtasks"""
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
        child_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=parent_task.id,
            content="Child task",
            status="todo",
        )
        async_db_session.add_all([parent_task, child_task])
        await async_db_session.commit()

        # Try to complete parent task while child is incomplete
        with pytest.raises(TaskCannotBeCompletedError):
            await tasks_service.update_task_status(
                async_db_session,
                user_id=user.id,
                task_id=parent_task.id,
                status_data=TaskStatusUpdate(status="done"),
            )

    async def test_delete_task_soft(self, async_db_session):
        """Test soft deleting a task"""
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

        # Soft delete
        result = await tasks_service.delete_task(
            async_db_session, user_id=user.id, task_id=task.id, hard_delete=False
        )

        assert result is True
        await async_db_session.refresh(task)
        assert task.deleted_at is not None
        assert task.is_deleted is True

    async def test_delete_task_hard(self, async_db_session):
        """Test hard deleting a task"""
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
        task_id = task.id

        # Hard delete
        result = await tasks_service.delete_task(
            async_db_session, user_id=user.id, task_id=task.id, hard_delete=True
        )

        assert result is True
        deleted_task = await async_db_session.get(Task, task_id)
        assert deleted_task is None

    async def test_reorder_tasks(self, async_db_session):
        """Test reordering multiple tasks"""
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

        # Create tasks
        tasks = []
        for i in range(3):
            task = Task(
                id=uuid4(),
                user_id=user.id,
                vision_id=vision.id,
                content=f"Task {i+1}",
                status="todo",
                display_order=i,
            )
            tasks.append(task)
        async_db_session.add_all(tasks)
        await async_db_session.commit()

        # Reorder tasks
        reorder_data = TaskReorderRequest(
            task_orders=[
                {"id": str(tasks[0].id), "display_order": 2},
                {"id": str(tasks[1].id), "display_order": 0},
                {"id": str(tasks[2].id), "display_order": 1},
            ]
        )

        await tasks_service.reorder_tasks(
            async_db_session, user_id=user.id, reorder_data=reorder_data
        )

        # Verify new order
        await async_db_session.refresh(tasks[0])
        await async_db_session.refresh(tasks[1])
        await async_db_session.refresh(tasks[2])

        assert tasks[0].display_order == 2
        assert tasks[1].display_order == 0
        assert tasks[2].display_order == 1

    async def test_move_task_to_new_parent(self, async_db_session):
        """Test moving task to new parent"""
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

        # Create tasks
        old_parent = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Old parent",
            status="todo",
        )
        new_parent = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="New parent",
            status="todo",
        )
        child_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=old_parent.id,
            content="Child task",
            status="todo",
        )
        async_db_session.add_all([old_parent, new_parent, child_task])
        await async_db_session.commit()

        # Move task to new parent
        move_data = TaskMoveRequest(
            old_parent_task_id=old_parent.id,
            new_parent_task_id=new_parent.id,
            new_display_order=0,
        )

        move_result = await tasks_service.move_task(
            async_db_session,
            user_id=user.id,
            task_id=child_task.id,
            move_data=move_data,
        )

        assert move_result.task.parent_task_id == new_parent.id
        assert move_result.updated_descendants == []

    async def test_move_task_to_new_vision(self, async_db_session):
        """Test moving task to new vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        old_vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="Old Vision",
            description="Old vision description",
        )
        new_vision = Vision(
            id=uuid4(),
            user_id=user.id,
            name="New Vision",
            description="New vision description",
        )
        async_db_session.add(user)
        async_db_session.add_all([old_vision, new_vision])
        await async_db_session.flush()

        task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=old_vision.id,
            content="Task to move",
            status="todo",
        )
        child = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=old_vision.id,
            parent_task_id=task.id,
            content="Child task",
            status="todo",
        )
        async_db_session.add_all([task, child])
        await async_db_session.commit()

        # Move task to new vision
        move_data = TaskMoveRequest(new_vision_id=new_vision.id, new_display_order=0)

        move_result = await tasks_service.move_task(
            async_db_session, user_id=user.id, task_id=task.id, move_data=move_data
        )

        assert move_result.task.vision_id == new_vision.id
        assert len(move_result.updated_descendants) == 1
        assert move_result.updated_descendants[0].id == child.id
        await async_db_session.refresh(child)
        assert child.vision_id == new_vision.id

    async def test_get_task_hierarchy(self, async_db_session):
        """Test getting task hierarchy for a vision"""
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
            display_order=0,
        )
        child_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=root_task.id,
            content="Child task",
            status="todo",
            display_order=0,
        )
        async_db_session.add_all([root_task, child_task])
        await async_db_session.commit()

        hierarchy = await tasks_service.get_vision_task_hierarchy(
            async_db_session, user_id=user.id, vision_id=vision.id
        )

        assert hierarchy.vision_id == vision.id
        assert len(hierarchy.root_tasks) == 1
        assert hierarchy.root_tasks[0].id == root_task.id
        assert len(hierarchy.root_tasks[0].subtasks) == 1
        assert hierarchy.root_tasks[0].subtasks[0].id == child_task.id

    async def test_get_task_hierarchy_invalid_vision(self, async_db_session):
        """Test getting task hierarchy for non-existent vision"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        with pytest.raises(VisionNotFoundError):
            await tasks_service.get_vision_task_hierarchy(
                async_db_session, user_id=user.id, vision_id=uuid4()
            )

    async def test_get_task_stats(self, async_db_session):
        """Test getting task statistics"""
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

        # Create parent task with subtasks
        parent_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            content="Parent task",
            status="todo",
            estimated_effort=60,
            actual_effort_self=30,
        )
        child_task1 = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=parent_task.id,
            content="Child task 1",
            status="done",
            estimated_effort=30,
            actual_effort_self=20,
        )
        child_task2 = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=parent_task.id,
            content="Child task 2",
            status="todo",
            estimated_effort=45,
            actual_effort_self=10,
        )
        async_db_session.add_all([parent_task, child_task1, child_task2])
        await async_db_session.commit()

        stats = await tasks_service.get_task_stats(
            async_db_session, user_id=user.id, task_id=parent_task.id
        )

        assert stats.total_subtasks == 2
        assert stats.completed_subtasks == 1
        assert stats.completion_percentage == 0.5
        assert stats.total_estimated_effort == 135  # 60 + 30 + 45
        assert stats.total_actual_effort == 60  # 30 + 20 + 10

    async def test_get_task_with_subtasks(self, async_db_session):
        """Test getting task with all subtasks"""
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
        child_task = Task(
            id=uuid4(),
            user_id=user.id,
            vision_id=vision.id,
            parent_task_id=root_task.id,
            content="Child task",
            status="done",
        )
        async_db_session.add_all([root_task, child_task])
        await async_db_session.commit()

        task_with_subtasks = await tasks_service.get_task_with_subtasks(
            async_db_session, user_id=user.id, task_id=root_task.id
        )

        assert task_with_subtasks.id == root_task.id
        assert len(task_with_subtasks.subtasks) == 1
        assert task_with_subtasks.subtasks[0].id == child_task.id
        assert task_with_subtasks.depth == 0
        assert task_with_subtasks.subtasks[0].depth == 1

    async def test_get_task_actual_events(self, async_db_session):
        """Test getting actual events for a task"""
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
            content="Test task",
            status="todo",
        )
        async_db_session.add(task)
        await async_db_session.commit()

        # Note: This test only verifies the basic structure.
        # In a real application, you would need to set up ActualEvent models
        # and their associations to test this functionality completely.
        events = await tasks_service.get_task_actual_events(
            async_db_session, user_id=user.id, task_id=task.id
        )
        assert isinstance(events, list)

    async def test_get_task_actual_events_task_not_found(self, async_db_session):
        """Test getting actual events for non-existent task"""
        user = User(
            id=uuid4(),
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password",
        )
        async_db_session.add(user)
        await async_db_session.commit()

        with pytest.raises(TaskNotFoundError):
            await tasks_service.get_task_actual_events(
                async_db_session, user_id=user.id, task_id=uuid4()
            )
