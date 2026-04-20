"""Durable background task owned by the built-in self-management agent."""

from __future__ import annotations

from typing import ClassVar

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class SelfManagementAgentTask(Base, TimestampMixin, UserOwnedMixin):
    """Persisted background task for one built-in self-management workflow."""

    __tablename__ = "self_management_agent_tasks"
    __table_args__ = (
        UniqueConstraint(
            "dedupe_key",
            name="uq_self_management_agent_tasks_dedupe_key",
        ),
        Index(
            "ix_self_management_agent_tasks_status_updated_at",
            "status",
            "updated_at",
        ),
        Index(
            "ix_self_management_agent_tasks_kind_status",
            "task_kind",
            "status",
        ),
        Index(
            "ix_self_management_agent_tasks_conversation_kind_status",
            "built_in_conversation_id",
            "task_kind",
            "status",
        ),
        Index(
            "uq_self_management_agent_tasks_follow_up_conversation",
            "user_id",
            "built_in_conversation_id",
            unique=True,
            postgresql_where=text("task_kind = 'follow_up_watch'"),
        ),
        {"schema": SCHEMA_NAME},
    )

    STATUS_WAITING: ClassVar[str] = "waiting"
    STATUS_RUNNING: ClassVar[str] = "running"
    STATUS_COMPLETED: ClassVar[str] = "completed"
    STATUS_FAILED: ClassVar[str] = "failed"
    STATUS_CANCELLED: ClassVar[str] = "cancelled"

    KIND_FOLLOW_UP_WATCH: ClassVar[str] = "follow_up_watch"
    KIND_PERMISSION_REPLY_CONTINUATION: ClassVar[str] = "permission_reply_continuation"
    KIND_DELEGATED_INVOKE: ClassVar[str] = "delegated_invoke"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
        nullable=False,
        comment="Data owner (UUID)",
    )
    built_in_conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.conversation_threads.id", ondelete="CASCADE"),
        nullable=False,
        comment="Built-in conversation that owns this task.",
    )
    task_kind = Column(
        String(64),
        nullable=False,
        comment="Built-in self-management task kind.",
    )
    status = Column(
        String(32),
        nullable=False,
        default=STATUS_WAITING,
        server_default=STATUS_WAITING,
        comment="Lifecycle status for the durable task.",
    )
    dedupe_key = Column(
        String(255),
        nullable=True,
        comment="Optional idempotency key used to deduplicate tasks.",
    )
    task_payload = Column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Serialized background task payload.",
    )
    last_run_started_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp when the most recent task run started.",
    )
    last_run_finished_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp when the most recent task run finished.",
    )
    last_run_error = Column(
        String(255),
        nullable=True,
        comment="Most recent background task error, if any.",
    )
