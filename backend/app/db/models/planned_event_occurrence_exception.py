"""SQLAlchemy model for planned event occurrence exceptions."""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)


class PlannedEventOccurrenceException(
    Base, TimestampMixin, SoftDeleteMixin, UserOwnedMixin
):
    """Represents an exception for a recurring planned event occurrence."""

    __tablename__ = "planned_event_occurrence_exceptions"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    master_event_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.planned_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to the recurring master event",
    )
    action = Column(
        String(32),
        nullable=False,
        index=True,
        comment="Exception action: skip, truncate, override",
    )
    instance_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="Deterministic identifier for the specific occurrence",
    )
    instance_start = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="Occurrence start time (UTC)",
    )
    payload = Column(
        JSON,
        nullable=True,
        comment="Optional override payload (future use)",
    )
