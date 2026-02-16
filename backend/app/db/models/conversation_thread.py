"""Canonical conversation thread model."""

from __future__ import annotations

from typing import ClassVar

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, validates

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin
from app.utils.timezone_util import utc_now


class ConversationThread(Base, TimestampMixin, UserOwnedMixin):
    """Canonical user conversation identity across local and external sources."""

    __tablename__ = "conversation_threads"
    __table_args__ = {"schema": SCHEMA_NAME}

    STATUS_ACTIVE: ClassVar[str] = "active"
    STATUS_MERGED: ClassVar[str] = "merged"
    STATUS_ARCHIVED: ClassVar[str] = "archived"
    SOURCE_MANUAL: ClassVar[str] = "manual"
    SOURCE_SCHEDULED: ClassVar[str] = "scheduled"
    SOURCE_OPENCODE: ClassVar[str] = "opencode"
    TITLE_MAX_LENGTH: ClassVar[int] = 255

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
    source = Column(
        String(16),
        nullable=False,
        default=SOURCE_MANUAL,
        server_default=SOURCE_MANUAL,
        comment="Conversation source kind: manual/scheduled/opencode.",
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

    bindings = relationship(
        "ConversationBinding",
        back_populates="conversation",
        foreign_keys="ConversationBinding.conversation_id",
    )
    messages = relationship(
        "AgentMessage",
        back_populates="conversation",
        foreign_keys="AgentMessage.conversation_id",
    )

    @staticmethod
    def normalize_title(value: str | None) -> str:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized[: ConversationThread.TITLE_MAX_LENGTH]
        return "Session"

    @validates("title")
    def _validate_title(self, _: str, value: str | None) -> str:
        return self.normalize_title(value)


__all__ = ["ConversationThread"]
