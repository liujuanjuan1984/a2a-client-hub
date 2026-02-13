"""
Agent-related database models.
"""

from typing import ClassVar

from sqlalchemy import Boolean, Column, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class AgentMessage(Base, TimestampMixin, UserOwnedMixin):
    """Agent chat and notification message model."""

    __tablename__ = "agent_messages"
    __table_args__ = {"schema": SCHEMA_NAME}

    SEVERITY_INFO: ClassVar[str] = "info"
    SEVERITY_WARNING: ClassVar[str] = "warning"
    SEVERITY_CRITICAL: ClassVar[str] = "critical"

    TYPE_CHAT: ClassVar[str] = "chat"
    TYPE_NOTIFICATION: ClassVar[str] = "system_notification"

    # id comes from TimestampMixin as UUID v4
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
        comment="Session identifier for grouping related messages",
        index=True,
    )
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.conversation_threads.id", ondelete="SET NULL"),
        nullable=True,
        comment="Canonical conversation identifier used for cross-source dedup.",
        index=True,
    )
    content = Column(Text, nullable=False)
    sender = Column(
        String(16),
        nullable=False,
        comment="Source of the message: user/agent/system/automation",
    )
    message_type = Column(
        String(32),
        nullable=False,
        default=TYPE_CHAT,
        server_default=TYPE_CHAT,
        comment="Message classification (chat/tool/system/etc.)",
    )
    severity = Column(
        String(16),
        nullable=False,
        default=SEVERITY_INFO,
        server_default=SEVERITY_INFO,
        comment="Notification severity indicator for system messages",
    )
    message_metadata = Column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Structured metadata for the message (tool info, etc.)",
    )
    is_typing = Column(Boolean, default=False)

    # Token usage tracking fields
    model_name = Column(String(100), nullable=True, comment="LLM model used")
    prompt_tokens = Column(Integer, nullable=True, comment="Input tokens")
    completion_tokens = Column(Integer, nullable=True, comment="Output tokens")
    total_tokens = Column(Integer, nullable=True, comment="Total tokens")
    cost_usd = Column(Numeric(10, 6), nullable=True, comment="Cost in USD")
    response_time_ms = Column(
        Integer, nullable=True, comment="Response time in milliseconds"
    )
    cardbox_card_id = Column(
        String(64), nullable=True, comment="Identifier of the synced Cardbox card"
    )

    session = relationship("AgentSession", back_populates="messages")
    conversation = relationship("ConversationThread", back_populates="messages")

    def __repr__(self) -> str:
        preview = (self.content or "")[:50]
        return (
            f"<AgentMessage(id={self.id}, sender={self.sender}, card={self.cardbox_card_id},"
            f" content={preview}...)>"
        )


__all__ = ["AgentMessage"]
