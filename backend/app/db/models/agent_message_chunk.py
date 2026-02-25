"""Stream chunk persistence model for agent messages."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class AgentMessageChunk(Base, TimestampMixin, UserOwnedMixin):
    """Append-only chunk entries for streaming agent messages."""

    __tablename__ = "agent_message_chunks"
    __table_args__ = (
        Index(
            "ix_agent_message_chunks_message_id_seq",
            "message_id",
            "seq",
            unique=False,
        ),
        Index(
            "uq_agent_message_chunks_message_id_seq",
            "message_id",
            "seq",
            unique=True,
        ),
        Index(
            "uq_agent_message_chunks_message_id_event_id",
            "message_id",
            "event_id",
            unique=True,
            postgresql_where=text("event_id IS NOT NULL"),
        ),
        {"schema": SCHEMA_NAME},
    )

    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.agent_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq = Column(
        Integer,
        nullable=False,
        comment="Monotonic sequence for a single message stream.",
    )
    event_id = Column(
        String(128),
        nullable=True,
        comment="Optional upstream event identifier for deduplication.",
    )
    block_type = Column(
        String(32),
        nullable=False,
        comment="Block type: text/reasoning/tool_call/system_error.",
    )
    content = Column(
        Text,
        nullable=False,
        default="",
        comment="Chunk delta payload.",
    )
    append = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
        comment="Whether this chunk appends to current block.",
    )
    is_finished = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="Whether this chunk marks block finished.",
    )
    source = Column(
        String(64),
        nullable=True,
        comment="Optional source hint (e.g., final_snapshot).",
    )

    message = relationship(
        "AgentMessage",
        back_populates="chunks",
        foreign_keys=[message_id],
    )


__all__ = ["AgentMessageChunk"]
