"""Canonical conversation thread model."""

from __future__ import annotations

from typing import ClassVar

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin
from app.utils.timezone_util import utc_now


class ConversationThread(Base, TimestampMixin, UserOwnedMixin):
    """Canonical user conversation identity across local and external sources."""

    __tablename__ = "conversation_threads"
    __table_args__ = {"schema": SCHEMA_NAME}

    STATUS_ACTIVE: ClassVar[str] = "active"
    STATUS_MERGED: ClassVar[str] = "merged"
    STATUS_ARCHIVED: ClassVar[str] = "archived"

    agent_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="Agent id associated with this thread (nullable for legacy rows).",
    )
    agent_source = Column(
        String(16),
        nullable=True,
        comment="Agent source scope (personal/shared).",
    )
    title = Column(String(255), nullable=False, default="Session")
    last_active_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: utc_now(),
        index=True,
    )
    status = Column(
        String(16),
        nullable=False,
        default=STATUS_ACTIVE,
        server_default=STATUS_ACTIVE,
        comment="Thread lifecycle status: active/merged/archived.",
    )
    merged_into_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.conversation_threads.id", ondelete="SET NULL"),
        nullable=True,
        comment="If merged, points to the surviving canonical thread.",
    )
    notes = Column(
        Text,
        nullable=True,
        comment="Optional internal notes for merge/audit operations.",
    )

    bindings = relationship("ConversationBinding", back_populates="conversation")
    messages = relationship("AgentMessage", back_populates="conversation")


__all__ = ["ConversationThread"]
