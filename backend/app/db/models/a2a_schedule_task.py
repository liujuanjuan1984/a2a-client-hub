"""Scheduled A2A task model."""

from __future__ import annotations

from typing import ClassVar

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)


class A2AScheduleTask(Base, TimestampMixin, SoftDeleteMixin, UserOwnedMixin):
    """User-defined recurring schedule for invoking an owned A2A agent."""

    __tablename__ = "a2a_schedule_tasks"
    __table_args__ = (
        Index(
            "ix_a2a_schedule_tasks_due",
            "user_id",
            "enabled",
            "next_run_at",
        ),
        {"schema": SCHEMA_NAME},
    )

    STATUS_IDLE: ClassVar[str] = "idle"
    STATUS_RUNNING: ClassVar[str] = "running"
    STATUS_SUCCESS: ClassVar[str] = "success"
    STATUS_FAILED: ClassVar[str] = "failed"

    CYCLE_DAILY: ClassVar[str] = "daily"
    CYCLE_WEEKLY: ClassVar[str] = "weekly"
    CYCLE_MONTHLY: ClassVar[str] = "monthly"
    CYCLE_INTERVAL: ClassVar[str] = "interval"

    name = Column(
        String(120),
        nullable=False,
        comment="User-facing task name",
    )
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.a2a_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Target A2A agent identifier",
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Scheduled session used to store recurring conversation messages",
    )
    prompt = Column(
        Text,
        nullable=False,
        comment="Prompt sent to the target agent on each run",
    )
    cycle_type = Column(
        String(16),
        nullable=False,
        comment="Cycle type: daily/weekly/monthly",
    )
    time_point = Column(
        JSONB,
        nullable=False,
        comment="Cycle-specific trigger point definition",
    )
    enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="Whether the schedule is active",
    )
    next_run_at = Column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Next planned trigger time in UTC",
    )
    last_run_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Most recent execution completion time in UTC",
    )
    last_run_status = Column(
        String(32),
        nullable=False,
        default=STATUS_IDLE,
        server_default=STATUS_IDLE,
        comment="Status of the most recent execution",
    )


__all__ = ["A2AScheduleTask"]
