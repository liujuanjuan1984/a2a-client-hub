"""Agent-related database models."""

from sqlalchemy import Column, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class AgentMessage(Base, TimestampMixin, UserOwnedMixin):
    """Agent chat and notification message model."""

    __tablename__ = "agent_messages"
    __table_args__ = (
        Index(
            "ix_agent_messages_conversation_id_created_at",
            "conversation_id",
            "created_at",
        ),
        Index(
            "uq_agent_messages_conversation_sender_invoke_idempotency_key",
            "conversation_id",
            "sender",
            "invoke_idempotency_key",
            unique=True,
            postgresql_where=text(
                "invoke_idempotency_key IS NOT NULL AND sender IN ('user', 'agent')"
            ),
        ),
        {"schema": SCHEMA_NAME},
    )

    # id comes from TimestampMixin as UUID v4
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.conversation_threads.id", ondelete="CASCADE"),
        nullable=False,
        comment="Canonical conversation identifier used for message grouping.",
        index=True,
    )
    status = Column(
        String(24),
        nullable=False,
        default="done",
        server_default="done",
        comment="Message status: streaming/done/error/interrupted.",
    )
    finish_reason = Column(
        String(64),
        nullable=True,
        comment="Finalized finish reason for stream-generated agent messages.",
    )
    error_code = Column(
        String(64),
        nullable=True,
        comment="Normalized error code for failed/incomplete stream.",
    )
    summary_text = Column(
        Text,
        nullable=True,
        comment="Short materialized summary for quick list rendering.",
    )
    sender = Column(
        String(16),
        nullable=False,
        comment="Source of the message: user/agent/system/automation",
    )
    message_metadata = Column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Structured metadata for the message (tool info, etc.)",
    )
    invoke_idempotency_key = Column(
        String(160),
        nullable=True,
        comment="Idempotency key for invoke-generated user/agent message pair.",
    )

    conversation = relationship(
        "ConversationThread",
        back_populates="messages",
        foreign_keys=[conversation_id],
    )
    blocks = relationship(
        "AgentMessageBlock",
        back_populates="message",
        foreign_keys="AgentMessageBlock.message_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<AgentMessage(id={self.id}, sender={self.sender})>"


__all__ = ["AgentMessage"]
