"""SQLAlchemy model for actual event quick templates."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)


class ActualEventQuickTemplate(Base, UserOwnedMixin, TimestampMixin, SoftDeleteMixin):
    """Persisted quick template used by actual event quick entry flows."""

    __tablename__ = "actual_event_quick_templates"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "title_normalized",
            name="uq_actual_event_quick_templates_user_title",
        ),
        {"schema": SCHEMA_NAME},
    )

    title = Column(String(200), nullable=False, comment="Display name for the template")
    title_normalized = Column(
        String(200),
        nullable=False,
        comment="Lowercase trimmed title for uniqueness enforcement",
    )
    dimension_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.dimensions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    default_duration_minutes = Column(
        Integer,
        nullable=True,
        comment="Optional default duration in minutes",
    )
    position = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Manual ordering position for templates",
    )
    usage_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="How many times the template has been applied",
    )
    last_used_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the last usage event",
    )

    dimension = relationship("Dimension")

    def touch_usage(self, *, when: datetime) -> None:
        """Increment usage counters and update timestamps."""
        self.usage_count = (self.usage_count or 0) + 1
        self.last_used_at = when

    def __repr__(self) -> str:  # pragma: no cover - debug helper only
        return (
            "<ActualEventQuickTemplate(id={0}, user_id={1}, title='{2}', position={3})>"
        ).format(self.id, self.user_id, self.title, self.position)
