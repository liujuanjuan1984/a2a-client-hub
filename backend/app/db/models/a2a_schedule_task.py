"""Scheduled A2A task model."""

from __future__ import annotations

from typing import ClassVar

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
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

    POLICY_NEW: ClassVar[str] = "new_each_run"
    POLICY_REUSE: ClassVar[str] = "reuse_single"

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
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.conversation_threads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Scheduled conversation thread used to store recurring messages",
    )
    conversation_policy = Column(
        String(32),
        nullable=False,
        default=POLICY_NEW,
        server_default=POLICY_NEW,
        comment="Session policy: new_each_run / reuse_single",
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
    consecutive_failures = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Consecutive failed invocations before circuit break",
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
    current_run_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        comment="Identifier of the currently running execution attempt",
    )
    running_started_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when the current running execution was claimed",
    )


__all__ = ["A2AScheduleTask"]
