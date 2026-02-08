"""
Task SQLAlchemy model

This model represents tasks that orbit around visions (satellites around trees).
Tasks can be hierarchical (parent-child relationships) and have different statuses.
Completing tasks provides energy that feeds into the vision's growth.
"""

import logging

from sqlalchemy import Column, Date, ForeignKey, Index, Integer, String, inspect, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.orm.attributes import NO_VALUE

from app.db.mixins.user_filter import UserFilterMixin
from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)


class Task(Base, UserOwnedMixin, TimestampMixin, SoftDeleteMixin, UserFilterMixin):
    """
    Task model representing specific actions needed to achieve a vision

    Each task is visualized as a satellite orbiting around the vision tree.
    Tasks can have parent-child relationships for hierarchical organization.
    """

    __tablename__ = "tasks"
    __table_args__ = (
        # Composite index to accelerate planning cycle queries (user + cycle filters)
        Index(
            "ix_tasks_user_cycle_type_start",
            "user_id",
            "planning_cycle_type",
            "planning_cycle_start_date",
            postgresql_where=text("planning_cycle_start_date IS NOT NULL"),
        ),
        # Composite index matching list_tasks ORDER BY, speeds up pagination
        Index(
            "ix_tasks_user_vision_order_created",
            "user_id",
            "vision_id",
            "display_order",
            "created_at",
        ),
        {"schema": SCHEMA_NAME},
    )

    # Foreign keys
    vision_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.visions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID of the vision this task belongs to",
    )
    parent_task_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.tasks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="ID of the parent task (for hierarchical tasks)",
    )

    # Task content and properties
    content = Column(
        String(500), nullable=False, index=True, comment="Task description or title"
    )
    notes_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of notes associated with this task",
    )

    # Task status and organization
    status = Column(
        String(20),
        nullable=False,
        default="todo",
        index=True,
        comment="Task status: 'todo', 'in_progress', 'done', 'cancelled', 'paused'",
    )
    priority = Column(
        Integer,
        nullable=False,
        default=0,
        index=True,
        comment="Task priority (higher numbers = higher priority)",
    )
    display_order = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Display order within the same parent/vision",
    )

    # Task complexity and effort estimation
    estimated_effort = Column(
        Integer, nullable=True, comment="Estimated effort in minutes"
    )
    # Deprecated actual_effort column removed in v0.9

    # Planning cycle configuration
    planning_cycle_type = Column(
        String(10),
        nullable=True,
        index=True,
        comment="Planning cycle type: year, month, week, day",
    )
    planning_cycle_days = Column(
        Integer, nullable=True, comment="Cycle duration in days"
    )
    planning_cycle_start_date = Column(
        Date, nullable=True, index=True, comment="Cycle start date"
    )

    # New in v0.9: precise separation of self minutes and aggregated minutes
    actual_effort_self = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Minutes from ActualEvents directly attached to this task",
    )
    actual_effort_total = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Minutes including this task self and all descendant tasks",
    )

    # Relationships
    vision = relationship("Vision", back_populates="tasks")
    parent_task = relationship(
        "Task",
        primaryjoin="Task.parent_task_id == remote(Task.id)",
        back_populates="subtasks",
    )
    subtasks = relationship(
        "Task",
        back_populates="parent_task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # One-to-many from Task to ActualEvent via ActualEvent.task_id
    time_entries = relationship(
        "ActualEvent",
        back_populates="task",
        primaryjoin="Task.id==ActualEvent.task_id",
        cascade="save-update",
        passive_deletes=True,
    )

    # Note: Timestamps and soft delete are inherited from mixins

    def __repr__(self):
        return f"<Task(id={self.id}, content='{self.content[:50]}...', status='{self.status}')>"

    def _get_loaded_subtasks(self):
        """Return the in-memory subtasks collection or raise if it was not eagerly loaded."""

        attr_state = inspect(self).attrs.subtasks
        value = attr_state.loaded_value
        if value is NO_VALUE:
            raise RuntimeError(
                "Task.subtasks relationship must be eagerly loaded before computing hierarchy "
                "properties. Use app.handlers.tasks.load_task_with_subtasks or "
                "session.refresh(task, attribute_names=['subtasks'])."
            )
        return value

    @property
    def is_root_task(self) -> bool:
        """Check if this is a root task (no parent)"""
        return self.parent_task_id is None

    @property
    def is_leaf_task(self) -> bool:
        """Check if this is a leaf task (no subtasks)"""
        return len(self._get_loaded_subtasks()) == 0

    @property
    def depth(self) -> int:
        """Calculate the depth of this task in the hierarchy"""
        # Iterative approach avoids hitting Python's recursion limit on deeply nested hierarchies.
        current = self
        depth = 0
        visited = set()

        while current is not None and current.parent_task_id is not None:
            marker = current.id or id(current)
            if marker in visited:
                logging.getLogger(__name__).warning(
                    "Detected task hierarchy cycle while computing depth for task %s",
                    getattr(self, "id", None),
                )
                break

            visited.add(marker)
            parent = current.parent_task
            if parent is None or parent is current:
                # Handles missing relationships or self-referential parent pointers gracefully.
                break

            depth += 1
            current = parent

        return depth

    def get_all_subtasks(self, include_self: bool = False) -> list:
        """
        Get all subtasks recursively

        Args:
            include_self: Whether to include this task in the result

        Returns:
            List of all subtasks (and optionally self)
        """
        result = [self] if include_self else []

        for subtask in self._get_loaded_subtasks():
            if not subtask.is_deleted:
                result.extend(subtask.get_all_subtasks(include_self=True))

        return result

    def get_completion_percentage(self) -> float:
        """
        Calculate completion percentage based on subtasks

        Returns:
            Completion percentage (0.0 to 1.0)
        """
        subtasks = [t for t in self._get_loaded_subtasks() if not t.is_deleted]
        if self.is_leaf_task:
            return 1.0 if self.status == "done" else 0.0
        if not subtasks:
            return 1.0 if self.status == "done" else 0.0

        completed_count = sum(1 for t in subtasks if t.status == "done")
        return completed_count / len(subtasks)

    def can_complete(self) -> bool:
        """Check if the task can be marked as completed"""
        subtasks = [t for t in self._get_loaded_subtasks() if not t.is_deleted]
        if self.is_leaf_task:
            return self.status != "done"

        # For parent tasks, all subtasks must be completed
        return all(t.status == "done" for t in subtasks)

    def complete(self) -> bool:
        """
        Mark the task as completed if possible

        Returns:
            bool: True if task was completed, False otherwise
        """
        if self.can_complete():
            self.status = "done"
            return True
        return False

    def validate_planning_cycle(self) -> bool:
        """
        Validate planning cycle data consistency

        Returns:
            bool: True if planning cycle data is valid or not set
        """
        cycle_fields = [
            self.planning_cycle_type,
            self.planning_cycle_days,
            self.planning_cycle_start_date,
        ]

        # Check if any field is set
        any_set = any(field is not None for field in cycle_fields)
        # Check if all fields are set
        all_set = all(field is not None for field in cycle_fields)

        # Either all fields must be set or none should be set
        if any_set and not all_set:
            return False

        # If no planning cycle is set, it's valid
        if not any_set:
            return True

        # Validate cycle type
        valid_types = {"year", "month", "week", "day"}
        if self.planning_cycle_type not in valid_types:
            return False

        # Validate days is positive
        if self.planning_cycle_days <= 0:
            return False

        return True
