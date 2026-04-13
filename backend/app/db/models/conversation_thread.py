"""Canonical conversation thread model."""

from __future__ import annotations

from typing import ClassVar

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, validates

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin
from app.utils.timezone_util import utc_now


class ConversationThread(Base, TimestampMixin, UserOwnedMixin):
    """Canonical user conversation identity across local and external sources."""

    __tablename__ = "conversation_threads"
    __table_args__ = (
        Index(
            "ix_conversation_threads_user_id_updated_at",
            "user_id",
            "updated_at",
        ),
        UniqueConstraint(
            "user_id",
            "external_provider",
            "external_session_id",
            name="uq_conversation_threads_user_provider_external_session",
        ),
        CheckConstraint(
            "source IN ('manual', 'scheduled')",
            name="ck_conversation_threads_source_allowed_values",
        ),
        CheckConstraint(
            "(external_session_id IS NULL) OR (external_provider IS NOT NULL)",
            name="ck_conversation_threads_external_session_requires_provider",
        ),
        {"schema": SCHEMA_NAME},
    )

    STATUS_ACTIVE: ClassVar[str] = "active"
    STATUS_ARCHIVED: ClassVar[str] = "archived"
    SOURCE_MANUAL: ClassVar[str] = "manual"
    SOURCE_SCHEDULED: ClassVar[str] = "scheduled"
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
        comment="Conversation initiation kind: manual/scheduled.",
    )
    external_provider = Column(
        String(64),
        nullable=True,
        index=True,
        comment="External provider key bound to this conversation (e.g., opencode).",
    )
    external_session_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="External provider session identifier.",
    )
    context_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="External protocol context identifier (e.g., A2A contextId).",
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

    @staticmethod
    def is_placeholder_title(value: str | None) -> bool:
        normalized = value.strip() if isinstance(value, str) else ""
        if not normalized:
            return True
        if normalized == "Session":
            return True
        return normalized.lower().startswith("manual session")

    @validates("title")
    def _validate_title(self, _: str, value: str | None) -> str:
        return self.normalize_title(value)


__all__ = ["ConversationThread"]
