"""
Actual Event SQLAlchemy model

This model represents actual events (footprints - what actually happened).
"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
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


class ActualEvent(
    Base, UserOwnedMixin, TimestampMixin, SoftDeleteMixin, UserFilterMixin
):
    """
    Actual Event model representing what actually happened

    This represents the "footprints on the ground" - the actual time spent and activities done.
    """

    __tablename__ = "actual_events"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    # Basic event information
    title = Column(
        String(200), nullable=False, index=True, comment="Actual activity title"
    )

    # Time information
    start_time = Column(
        DateTime(timezone=True), nullable=False, index=True, comment="Actual start time"
    )
    end_time = Column(
        DateTime(timezone=True), nullable=False, index=True, comment="Actual end time"
    )

    # Link to a single task (optional, v0.9+). Replaces legacy many-to-many usage for timelog entries
    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Reference to the associated task (many ActualEvents to one Task)",
    )

    # Life dimension relationship (optional)
    dimension_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.dimensions.id"),
        nullable=True,
        index=True,
        comment="Reference to life dimension this activity belongs to",
    )

    # Tracking information
    tracking_method = Column(
        String(20),
        default="manual",
        comment="How this was tracked: manual, automatic, imported",
    )
    location = Column(
        String(200), nullable=True, comment="Where this activity took place"
    )

    # Quality and reflection
    energy_level = Column(
        Integer, nullable=True, comment="Energy level during activity (1-5)"
    )
    notes = Column(Text, nullable=True, comment="Personal notes and reflections")

    # Metadata
    tags = Column(JSON, nullable=True, comment="Activity tags as JSON array")
    extra_data = Column(JSON, nullable=True, comment="Additional metadata as JSON")

    # Note: Timestamps are inherited from TimestampMixin

    # Relationships
    dimension = relationship("Dimension", backref="actual_events")

    # New one-to-many relationship to Task for timelog entries
    task = relationship("Task", back_populates="time_entries")

    def __repr__(self):
        return f"<ActualEvent(id={self.id}, title='{self.title}', start_time={self.start_time}, end_time={self.end_time})>"
