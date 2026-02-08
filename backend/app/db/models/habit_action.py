"""
HabitAction SQLAlchemy model

This model represents daily action records generated from habits.
Each action record represents a specific day's task for a habit.
Actions are automatically generated and cannot be manually created or deleted.
"""

from datetime import date

from sqlalchemy import CheckConstraint, Column, Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.constants import HABIT_EDITABLE_DAYS, get_default_habit_action_status
from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)


class HabitAction(Base, UserOwnedMixin, TimestampMixin, SoftDeleteMixin):
    """
    HabitAction model representing daily action records for habits

    Each action record is automatically generated for each day of the habit duration.
    Users can only modify the status and notes within a 3-day window after the action date.
    """

    __tablename__ = "habit_actions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'done', 'skip', 'miss')",
            name="valid_action_status",
        ),
        {"schema": SCHEMA_NAME},
    )

    # Primary key
    # id is UUID via TimestampMixin

    # Foreign keys
    habit_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.habits.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID of the habit this action belongs to",
    )

    # Action content and properties
    action_date = Column(
        Date,
        nullable=False,
        index=True,
        comment="The specific date for this action",
    )
    status = Column(
        String(20),
        nullable=False,
        default=get_default_habit_action_status,
        index=True,
        comment="Action status: 'pending', 'done', 'skip', 'miss'",
    )
    notes = Column(
        Text,
        nullable=True,
        comment="Additional notes or details about this action",
    )

    # Relationships
    habit = relationship("Habit", back_populates="actions")

    # Note: Timestamps and soft delete are inherited from mixins

    def __repr__(self):
        return f"<HabitAction(id={self.id}, habit_id={self.habit_id}, action_date={self.action_date}, status='{self.status}')>"

    @property
    def is_today(self) -> bool:
        """Check if this action is for today"""
        return self.action_date == date.today()

    @property
    def is_past(self) -> bool:
        """Check if this action is for a past date"""
        return self.action_date < date.today()

    @property
    def is_future(self) -> bool:
        """Check if this action is for a future date"""
        return self.action_date > date.today()

    @property
    def can_modify(self) -> bool:
        """Check if the user can modify this action"""
        if self.is_future:
            return False

        # Allow modification within HABIT_EDITABLE_DAYS days after action date
        days_since_action = (date.today() - self.action_date).days  # type: ignore[attr-defined]
        return days_since_action <= HABIT_EDITABLE_DAYS
