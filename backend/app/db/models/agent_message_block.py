"""Block-level persistence model for agent messages."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class AgentMessageBlock(Base, TimestampMixin, UserOwnedMixin):
    """Persisted ordered blocks for agent messages."""

    __tablename__ = "agent_message_blocks"
    __table_args__ = (
        Index(
            "ix_agent_message_blocks_message_id_block_seq",
            "message_id",
            "block_seq",
            unique=True,
        ),
        Index(
            "ix_agent_message_blocks_message_id_block_id",
            "message_id",
            "block_id",
            unique=True,
        ),
        {"schema": SCHEMA_NAME},
    )

    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.agent_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    block_seq = Column(
        Integer,
        nullable=False,
        comment="Monotonic block sequence within a single message.",
    )
    block_id = Column(
        String(128),
        nullable=True,
        comment="Stable logical block id used by append/replace/finalize operations.",
    )
    lane_id = Column(
        String(64),
        nullable=True,
        comment="Stable render lane id for this logical block.",
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
        comment="Materialized block content.",
    )
    is_finished = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="Whether this block has been finalized.",
    )
    source = Column(
        String(64),
        nullable=True,
        comment="Optional source hint (e.g. stream/final_snapshot/finalize_snapshot).",
    )
    start_event_seq = Column(
        Integer,
        nullable=True,
        comment="First applied event sequence for this block.",
    )
    end_event_seq = Column(
        Integer,
        nullable=True,
        comment="Last applied event sequence for this block.",
    )
    base_seq = Column(
        Integer,
        nullable=True,
        comment="Latest authoritative base sequence accepted for this block.",
    )
    start_event_id = Column(
        String(128),
        nullable=True,
        comment="First applied upstream event id.",
    )
    end_event_id = Column(
        String(128),
        nullable=True,
        comment="Last applied upstream event id.",
    )

    message = relationship(
        "AgentMessage",
        back_populates="blocks",
        foreign_keys=[message_id],
    )


__all__ = ["AgentMessageBlock"]
