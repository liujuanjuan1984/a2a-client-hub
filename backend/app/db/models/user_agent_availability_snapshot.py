"""User-scoped availability snapshots for non-personal agents."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin


class UserAgentAvailabilitySnapshot(Base, TimestampMixin):
    """Persist the latest availability check for one user-visible agent."""

    __tablename__ = "user_agent_availability_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "agent_source",
            "agent_id",
            name="uq_user_agent_availability_snapshots_user_source_agent",
        ),
        {"schema": SCHEMA_NAME},
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Snapshot owner (UUID).",
    )
    agent_source = Column(
        String(16),
        nullable=False,
        index=True,
        comment="Agent source scope (shared/builtin).",
    )
    agent_id = Column(
        String(120),
        nullable=False,
        index=True,
        comment="User-visible agent identifier.",
    )
    health_status = Column(
        String(16),
        nullable=False,
        default="unknown",
        server_default="unknown",
        index=True,
        comment="Latest persisted availability status.",
    )
    consecutive_health_check_failures = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Consecutive failed checks for degraded/unavailable detection.",
    )
    last_health_check_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the latest availability check attempt.",
    )
    last_successful_health_check_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the latest successful availability check attempt.",
    )
    last_health_check_error = Column(
        Text,
        nullable=True,
        comment="Latest persisted availability check error summary.",
    )
    last_health_check_reason_code = Column(
        String(64),
        nullable=True,
        comment="Latest persisted structured availability reason code.",
    )

    def __repr__(self) -> str:
        return (
            "<UserAgentAvailabilitySnapshot("
            f"id={self.id}, user_id={self.user_id}, "
            f"agent_source={self.agent_source}, agent_id={self.agent_id})>"
        )


__all__ = ["UserAgentAvailabilitySnapshot"]
