"""Execution log model for scheduled A2A tasks."""

from __future__ import annotations

from typing import ClassVar

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class A2AScheduleExecution(Base, TimestampMixin, UserOwnedMixin):
    """Execution history row for one scheduled trigger attempt."""

    __tablename__ = "a2a_schedule_executions"
    __table_args__ = (
        Index(
            "ix_a2a_schedule_executions_task_created",
            "task_id",
            "created_at",
        ),
        Index(
            "ix_a2a_schedule_executions_queue_poll",
            "status",
            "scheduled_for",
        ),
        Index(
            "uq_a2a_schedule_executions_active_task",
            "task_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        UniqueConstraint(
            "task_id",
            "run_id",
            name="uq_a2a_schedule_executions_task_run",
        ),
        {"schema": SCHEMA_NAME},
    )

    STATUS_PENDING: ClassVar[str] = "pending"
    STATUS_RUNNING: ClassVar[str] = "running"
    STATUS_SUCCESS: ClassVar[str] = "success"
    STATUS_FAILED: ClassVar[str] = "failed"

    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.a2a_schedule_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Owning schedule task identifier",
    )
    run_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Unique identifier for one execution run lifecycle",
    )
    scheduled_for = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Planned trigger time for this execution",
    )
    started_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Execution start time; NULL while still pending in the durable queue",
    )
    last_heartbeat_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Most recent heartbeat observed while execution is running",
    )
    finished_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Execution completion time",
    )
    status = Column(
        String(32),
        nullable=False,
        comment="Execution lifecycle status",
    )
    error_message = Column(
        Text,
        nullable=True,
        comment="Failure reason if execution did not succeed",
    )
    response_content = Column(
        Text,
        nullable=True,
        comment="Persisted response content returned by the target agent",
    )
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.conversation_threads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Associated scheduled conversation thread",
    )
    user_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.agent_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Generated user-side message ID",
    )
    agent_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.agent_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Generated agent-side message ID",
    )


__all__ = ["A2AScheduleExecution"]
