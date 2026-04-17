"""Durable follow-up task for one built-in self-management conversation."""

from __future__ import annotations

from typing import ClassVar

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class BuiltInFollowUpTask(Base, TimestampMixin, UserOwnedMixin):
    """Persisted follow-up tracking substrate owned by one built-in conversation."""

    __tablename__ = "built_in_follow_up_tasks"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "built_in_conversation_id",
            name="uq_built_in_follow_up_tasks_user_conversation",
        ),
        Index(
            "ix_built_in_follow_up_tasks_status_updated_at",
            "status",
            "updated_at",
        ),
        Index(
            "ix_built_in_follow_up_tasks_conversation_status",
            "built_in_conversation_id",
            "status",
        ),
        {"schema": SCHEMA_NAME},
    )

    STATUS_WAITING: ClassVar[str] = "waiting"
    STATUS_RUNNING: ClassVar[str] = "running"
    STATUS_COMPLETED: ClassVar[str] = "completed"
    STATUS_FAILED: ClassVar[str] = "failed"
    STATUS_CANCELLED: ClassVar[str] = "cancelled"

    built_in_conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.conversation_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Built-in conversation that owns this follow-up substrate.",
    )
    status = Column(
        String(32),
        nullable=False,
        default=STATUS_WAITING,
        server_default=STATUS_WAITING,
        comment="Lifecycle status for the durable follow-up substrate.",
    )
    tracked_conversation_ids = Column(
        JSONB,
        nullable=False,
        default=list,
        comment="Current target conversation ids tracked by the built-in agent.",
    )
    target_agent_message_anchors = Column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Latest observed target-agent text message id per tracked conversation.",
    )
    last_run_started_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp when the most recent follow-up run started.",
    )
    last_run_finished_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp when the most recent follow-up run finished.",
    )
    last_run_error = Column(
        String(255),
        nullable=True,
        comment="Most recent background follow-up execution error, if any.",
    )
