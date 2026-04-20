"""Durable dispatch task for self-management background execution."""

from __future__ import annotations

from typing import ClassVar

from sqlalchemy import Column, DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class SelfManagementDispatchTask(Base, TimestampMixin, UserOwnedMixin):
    """Persisted background dispatch task for self-management execution."""

    __tablename__ = "self_management_dispatch_tasks"
    __table_args__ = (
        UniqueConstraint(
            "dedupe_key",
            name="uq_self_management_dispatch_tasks_dedupe_key",
        ),
        Index(
            "ix_self_management_dispatch_tasks_status_updated_at",
            "status",
            "updated_at",
        ),
        Index(
            "ix_self_management_dispatch_tasks_kind_status",
            "task_kind",
            "status",
        ),
        {"schema": SCHEMA_NAME},
    )

    STATUS_WAITING: ClassVar[str] = "waiting"
    STATUS_RUNNING: ClassVar[str] = "running"
    STATUS_COMPLETED: ClassVar[str] = "completed"
    STATUS_FAILED: ClassVar[str] = "failed"
    STATUS_CANCELLED: ClassVar[str] = "cancelled"

    KIND_PERMISSION_REPLY_CONTINUATION: ClassVar[str] = "permission_reply_continuation"
    KIND_DELEGATED_INVOKE: ClassVar[str] = "delegated_invoke"

    task_kind = Column(
        String(64),
        nullable=False,
        comment="Dispatch task kind for one self-management background request.",
    )
    status = Column(
        String(32),
        nullable=False,
        default=STATUS_WAITING,
        server_default=STATUS_WAITING,
        comment="Lifecycle status for the durable dispatch task.",
    )
    dedupe_key = Column(
        String(255),
        nullable=True,
        comment="Optional idempotency key used to deduplicate durable dispatch tasks.",
    )
    task_payload = Column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Serialized durable dispatch payload for one background request.",
    )
    last_run_started_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp when the most recent dispatch run started.",
    )
    last_run_finished_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp when the most recent dispatch run finished.",
    )
    last_run_error = Column(
        String(255),
        nullable=True,
        comment="Most recent durable dispatch error, if any.",
    )
