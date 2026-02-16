"""Agent-related database models."""

from sqlalchemy import Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class AgentMessage(Base, TimestampMixin, UserOwnedMixin):
    """Agent chat and notification message model."""

    __tablename__ = "agent_messages"
    __table_args__ = {"schema": SCHEMA_NAME}

    # id comes from TimestampMixin as UUID v4
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.conversation_threads.id", ondelete="CASCADE"),
        nullable=False,
        comment="Canonical conversation identifier used for message grouping.",
        index=True,
    )
    content = Column(Text, nullable=False)
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

    conversation = relationship(
        "ConversationThread",
        back_populates="messages",
        foreign_keys=[conversation_id],
    )

    def __repr__(self) -> str:
        preview = (self.content or "")[:50]
        return (
            f"<AgentMessage(id={self.id}, sender={self.sender}, content={preview}...)>"
        )


__all__ = ["AgentMessage"]
