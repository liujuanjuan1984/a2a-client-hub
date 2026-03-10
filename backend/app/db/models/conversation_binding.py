"""Conversation binding model for mapping various session identities to canonical threads."""

from __future__ import annotations

from typing import ClassVar

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin
from app.utils.timezone_util import utc_now


class ConversationBinding(Base, TimestampMixin, UserOwnedMixin):
    """Binding between a specific session/context and a canonical conversation thread."""

    __tablename__ = "conversation_bindings"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "local_session_id",
            name="uq_conversation_bindings_local_session",
            # Note: status='active' filtering would be better as partial index if supported
        ),
        UniqueConstraint(
            "user_id",
            "provider",
            "agent_source",
            "agent_id",
            "external_session_id",
            name="uq_conversation_bindings_external_session",
        ),
        Index(
            "ix_conversation_bindings_provider_context",
            "user_id",
            "provider",
            "context_id",
        ),
        Index(
            "ix_conversation_bindings_conversation_primary",
            "conversation_id",
            "is_primary",
        ),
        {"schema": SCHEMA_NAME},
    )

    KIND_LOCAL: ClassVar[str] = "local_session"
    KIND_EXTERNAL: ClassVar[str] = "external_session"
    KIND_PROTOCOL: ClassVar[str] = "protocol_context"

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
        comment="Binding type: local_session, external_session, protocol_context.",
    )
    provider = Column(
        String(64),
        nullable=True,
        index=True,
        comment="Provider name (e.g., 'opencode').",
    )
    agent_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    agent_source = Column(
        String(16),
        nullable=True,
    )
    local_session_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    external_session_id = Column(
        String(255),
        nullable=True,
        index=True,
    )
    context_id = Column(
        String(255),
        nullable=True,
        index=True,
    )
    binding_metadata = Column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    confidence = Column(
        Float,
        nullable=False,
        default=1.0,
        server_default="1.0",
    )
    is_primary = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    status = Column(
        String(16),
        nullable=False,
        default=STATUS_ACTIVE,
        server_default=STATUS_ACTIVE,
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
    )

    conversation = relationship("ConversationThread", back_populates="bindings")


__all__ = ["ConversationBinding"]
