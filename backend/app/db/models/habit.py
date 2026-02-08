"""
Habit SQLAlchemy model

This model represents user habits that generate daily action records.
Each habit represents a recurring behavior that the user wants to establish.
The habit serves as the template for generating daily action records.
"""

from datetime import date, timedelta

from sqlalchemy import CheckConstraint, Column, Date, ForeignKey, Integer, String, Text
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


class Habit(Base, UserOwnedMixin, TimestampMixin, SoftDeleteMixin, UserFilterMixin):
    """
    Habit model representing recurring behaviors to establish

    Each habit generates daily action records from start_date for duration_days.
    The habit cannot be modified once created to maintain consistency.
    """

    __tablename__ = "habits"
    __table_args__ = (
        CheckConstraint(
            "duration_days IN (5, 7, 14, 21, 100, 365, 1000)",
            name="valid_duration_days",
        ),
        {"schema": SCHEMA_NAME},
    )

    # Basic habit information
    title = Column(
        String(200),
        nullable=False,
        index=True,
        comment="Habit title (e.g., 'Daily Exercise', 'Read 30 minutes')",
    )
    description = Column(
        Text,
        nullable=True,
        comment="Detailed description of this habit and its significance",
    )

    # Habit timing and duration
    start_date = Column(
        Date,
        nullable=False,
        index=True,
        comment="Start date of the habit (cannot be modified after creation)",
    )
    duration_days = Column(
        Integer,
        nullable=False,
        comment="Duration in days: 5, 7, 14, 21, 100, 365, or 1000",
    )

    # Habit status
    status = Column(
        String(20),
        nullable=False,
        default="active",
        index=True,
        comment="Habit status: 'active', 'completed', 'paused', 'expired'",
    )

    # Task association
    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="ID of the associated task (optional)",
    )

    # Relationships
    actions = relationship(
        "HabitAction",
        back_populates="habit",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    task = relationship("Task", foreign_keys=[task_id])

    # Note: Timestamps and soft delete are inherited from mixins

    def __repr__(self):
        return f"<Habit(id={self.id}, title='{self.title}', status='{self.status}', duration_days={self.duration_days})>"

    @property
    def end_date(self) -> date:
        """Calculate the end date of the habit"""

        return self.start_date + timedelta(days=self.duration_days - 1)

    @property
    def is_completed(self) -> bool:
        """Check if the habit duration has been completed"""
        return date.today() > self.end_date

    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage based on current date"""
        if self.is_completed:
            return 100.0

        days_elapsed = (date.today() - self.start_date).days + 1  # type: ignore[attr-defined]
        if days_elapsed <= 0:
            return 0.0

        return min(100.0, (days_elapsed / self.duration_days) * 100.0)
