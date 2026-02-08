"""
Planned Event SQLAlchemy model

This model represents planned events (compass needle - the direction/intention).
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
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


class PlannedEvent(
    Base, UserOwnedMixin, TimestampMixin, SoftDeleteMixin, UserFilterMixin
):
    """
    Planned Event model representing user's intended schedule

    This represents the "compass needle" - the direction user wants to go.
    """

    __tablename__ = "planned_events"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    # Basic event information
    title = Column(String(200), nullable=False, index=True, comment="Event title")
    # description removed in v0.8

    # Time information
    start_time = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="Planned start time",
    )
    end_time = Column(
        DateTime(timezone=True), nullable=True, index=True, comment="Planned end time"
    )

    # category removed in v0.8
    priority = Column(
        Integer,
        default=0,
        index=True,
        comment="Priority level (0-5, higher is more important)",
    )

    # Life dimension relationship (optional)
    dimension_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.dimensions.id"),
        nullable=True,
        index=True,
        comment="Reference to life dimension this event belongs to",
    )

    # Task relationship (optional - for planned work sessions)
    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Optional reference to task this event is planned to work on",
    )
    is_all_day = Column(
        Boolean, default=False, comment="Whether this is an all-day event"
    )

    # Recurrence information
    is_recurring = Column(
        Boolean, default=False, index=True, comment="Whether this event recurs"
    )
    recurrence_pattern = Column(
        JSON, nullable=True, comment="Recurrence pattern details"
    )
    # RRULE string for complex recurring patterns (RFC 5545 standard)
    rrule_string = Column(
        Text, nullable=True, comment="RRULE string for recurring events (RFC 5545)"
    )

    # Status and metadata
    status = Column(
        String(20),
        default="planned",
        index=True,
        comment="Event status: planned, cancelled, completed",
    )
    tags = Column(JSON, nullable=True, comment="Event tags as JSON array")
    extra_data = Column(JSON, nullable=True, comment="Additional metadata as JSON")

    # Note: Timestamps are inherited from TimestampMixin

    # Relationships
    dimension = relationship("Dimension", backref="planned_events")
    task = relationship("Task", backref="planned_events")

    def __repr__(self):
        return f"<PlannedEvent(id={self.id}, title='{self.title}', start_time={self.start_time})>"
