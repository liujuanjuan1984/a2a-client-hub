"""Conversation binding model for local/external/protocol references."""

from __future__ import annotations

from typing import ClassVar

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin
from app.utils.timezone_util import utc_now


class ConversationBinding(Base, TimestampMixin, UserOwnedMixin):
    """Maps canonical conversations to local sessions and external references."""

    __tablename__ = "conversation_bindings"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    KIND_LOCAL_SESSION: ClassVar[str] = "local_session"
    KIND_EXTERNAL_SESSION: ClassVar[str] = "external_session"
    KIND_PROTOCOL_CONTEXT: ClassVar[str] = "protocol_context"

    STATUS_ACTIVE: ClassVar[str] = "active"
    STATUS_STALE: ClassVar[str] = "stale"

    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.conversation_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    binding_kind = Column(
        String(32),
        nullable=False,
        comment="Binding kind: local_session/external_session/protocol_context.",
    )
    provider = Column(
        String(64),
        nullable=True,
        index=True,
        comment="External provider key (e.g., opencode).",
    )
    agent_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="Agent id for scoping external bindings.",
    )
    agent_source = Column(
        String(16),
        nullable=True,
        comment="Agent source scope (personal/shared).",
    )
    local_session_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.agent_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
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
        comment="Protocol context identifier (A2A contextId).",
    )
    binding_metadata = Column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Provider-specific binding metadata.",
    )
    confidence = Column(
        Float,
        nullable=False,
        default=1.0,
        server_default="1.0",
        comment="Binding confidence for reconciliation workflows.",
    )
    is_primary = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="Whether this binding is the primary locator for the conversation.",
    )
    status = Column(
        String(16),
        nullable=False,
        default=STATUS_ACTIVE,
        server_default=STATUS_ACTIVE,
        comment="Binding lifecycle status: active/stale.",
    )
    first_seen_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: utc_now(),
    )
    last_seen_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: utc_now(),
        index=True,
    )

    conversation = relationship("ConversationThread", back_populates="bindings")


__all__ = ["ConversationBinding"]
