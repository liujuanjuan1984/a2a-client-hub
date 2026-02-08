"""
Vision SQLAlchemy model

This model represents user visions (trees in the orchard).
Each vision represents a major goal or aspiration that the user wants to achieve.
The vision serves as the central trunk from which tasks (satellites) orbit.
"""

from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.mixins.user_filter import UserFilterMixin
from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)
from app.db.models.task import Task


class Vision(Base, UserOwnedMixin, TimestampMixin, SoftDeleteMixin, UserFilterMixin):
    """
    Vision model representing major life goals or aspirations

    Each vision is visualized as a tree in the user's orchard.
    The tree grows and evolves as tasks are completed and energy is injected.
    """

    __tablename__ = "visions"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    # Basic vision information
    name = Column(
        String(200),
        nullable=False,
        index=True,
        comment="Vision name (e.g., 'Complete v1.0 Prototype', 'Master Guitar')",
    )
    description = Column(
        Text,
        nullable=True,
        comment="Detailed description of this vision and its significance",
    )

    # Vision status and growth
    status = Column(
        String(20),
        nullable=False,
        index=True,
        default="active",
        comment="Vision status: 'active', 'archived', 'fruit'",
    )
    stage = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Growth stage of the tree (0-10, used for 3D model selection)",
    )
    experience_points = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Accumulated experience points that drive stage evolution",
    )
    experience_rate_per_hour = Column(
        Integer,
        nullable=True,
        comment="Optional override: experience points gained per hour of effort",
    )

    # Default dimension for this vision (optional)
    dimension_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.dimensions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Default life dimension for this vision (inherited by tasks and quick entries)",
    )

    # Relationships
    tasks = relationship(
        "Task",
        back_populates="vision",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # Relationships
    dimension = relationship("Dimension", backref="visions")

    # Note: Timestamps and soft delete are inherited from mixins

    def __repr__(self):
        return f"<Vision(id={self.id}, name='{self.name}', status='{self.status}', stage={self.stage})>"

    def calculate_task_experience(
        self,
        task_ids: list[UUID],
        *,
        experience_rate_per_hour: int,
        tasks: list["Task"] | None = None,
    ) -> int:
        """
        Calculate experience points based on actual time investment
        Experience = actual_effort_total (in minutes) for root tasks only

        Args:
            task_ids: List of task IDs that were completed (not used in new logic)

        Returns:
            int: Experience points based on total actual effort
        """
        # Calculate experience based on root tasks' actual effort total
        # 1 minute = 1 experience point
        selected_tasks = tasks if tasks is not None else []
        total_exp = 0
        for task in selected_tasks:
            if task.parent_task_id is None:  # Only root tasks
                total_exp += task.actual_effort_total or 0

        if experience_rate_per_hour <= 0:
            return 0

        return (total_exp * experience_rate_per_hour) // 60

    def inject_energy_from_tasks(
        self,
        task_ids: list[UUID],
        *,
        experience_rate_per_hour: int,
        tasks: list["Task"] | None = None,
    ) -> tuple[int, bool]:
        """
        Inject energy into the vision based on actual time investment

        Args:
            task_ids: List of task IDs that were completed (not used in new logic)

        Returns:
            tuple: (experience_gained, stage_evolved)
        """
        # Recalculate experience based on current actual effort totals
        exp_gained = self.calculate_task_experience(
            task_ids,
            experience_rate_per_hour=experience_rate_per_hour,
            tasks=tasks,
        )

        # Update experience points to match actual effort
        old_experience = self.experience_points
        self.experience_points = exp_gained

        # Check if stage evolved
        stage_evolved = self._update_stage_based_on_experience()

        # Update task status based on business logic
        selected_tasks = tasks if tasks is not None else []
        for task in selected_tasks:
            if task.id in task_ids:
                # If task is todo, change to in_progress
                # Otherwise, keep current status unchanged
                if task.status == "todo":
                    task.status = "in_progress"

        return exp_gained - old_experience, stage_evolved

    def _update_stage_based_on_experience(self) -> bool:
        """
        Update stage based on current experience points (actual effort)

        Returns:
            bool: True if stage evolved, False otherwise
        """
        old_stage = self.stage

        # Adjust stage thresholds for minute-based experience
        # Since 1 minute = 1 experience point, we need larger thresholds
        # 10 stages: initial value 2 hours, each stage = previous stage * 2, converted to minutes
        # Formula: stage_n = stage_{n-1} * 2 * 60 minutes
        stage_thresholds = [
            0,
            120,
            240,
            480,
            960,
            1920,
            3840,
            7680,
            15360,
            30720,
            61440,
        ]  # Stages 0-10

        # Calculate new stage based on experience points
        new_stage = 0
        for threshold in stage_thresholds:
            if self.experience_points >= threshold:
                new_stage += 1
            else:
                break

        # Cap at maximum stage (now 10 instead of 6)
        self.stage = min(new_stage - 1, 10)

        return self.stage > old_stage

    def add_experience(self, points: int) -> bool:
        """
        Add experience points to the vision and check for stage evolution
        Note: This method is now mainly used for manual experience addition

        Args:
            points: Experience points to add

        Returns:
            bool: True if stage evolved, False otherwise
        """
        self.stage
        self.experience_points += points

        return self._update_stage_based_on_experience()

    def sync_experience_with_actual_effort(
        self,
        *,
        experience_rate_per_hour: int,
        tasks: list["Task"] | None = None,
    ) -> bool:
        """
        Synchronize experience points with actual effort totals
        This ensures experience always reflects current time investment

        Returns:
            bool: True if stage evolved, False otherwise
        """
        # Recalculate experience based on current actual effort
        new_experience = self.calculate_task_experience(
            [],
            experience_rate_per_hour=experience_rate_per_hour,
            tasks=tasks,
        )

        if new_experience != self.experience_points:
            self.experience_points = new_experience
            return self._update_stage_based_on_experience()

        return False

    def can_harvest(self) -> bool:
        """Check if the vision is ready for harvest (has reached final stage)"""
        return self.stage >= 7 and self.status == "active"

    def harvest(self) -> None:
        """Convert the vision to a fruit (completed achievement)"""
        if self.can_harvest():
            self.status = "fruit"
