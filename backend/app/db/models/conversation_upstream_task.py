"""Durable upstream task binding for one conversation."""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class ConversationUpstreamTask(Base, TimestampMixin, UserOwnedMixin):
    """Locally observed upstream A2A task owned by a conversation."""

    __tablename__ = "conversation_upstream_tasks"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "conversation_id",
            "upstream_task_id",
            name="uq_conversation_upstream_tasks_user_conversation_task",
        ),
        Index(
            "ix_conversation_upstream_tasks_user_conversation_updated",
            "user_id",
            "conversation_id",
            "updated_at",
        ),
        Index(
            "ix_conversation_upstream_tasks_user_task",
            "user_id",
            "upstream_task_id",
        ),
        {"schema": SCHEMA_NAME},
    )

    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.conversation_threads.id", ondelete="CASCADE"),
        nullable=False,
        comment="Conversation that first observed this upstream task.",
    )
    agent_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="Agent id used when the upstream task was observed.",
    )
    agent_source = Column(
        String(16),
        nullable=True,
        comment="Agent source scope used when the upstream task was observed.",
    )
    upstream_task_id = Column(
        String(255),
        nullable=False,
        comment="Upstream A2A task identifier.",
    )
    first_seen_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.agent_messages.id", ondelete="SET NULL"),
        nullable=True,
        comment="First local agent message that carried this upstream task id.",
    )
    latest_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.agent_messages.id", ondelete="SET NULL"),
        nullable=True,
        comment="Latest local agent message associated with this upstream task id.",
    )
    source = Column(
        String(32),
        nullable=False,
        default="stream_identity",
        server_default="stream_identity",
        comment="Local observation source for this binding.",
    )
    status_hint = Column(
        String(32),
        nullable=True,
        comment="Best-effort latest local status hint for this upstream task.",
    )
