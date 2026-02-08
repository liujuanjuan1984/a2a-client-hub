"""Agent session SQLAlchemy model."""

from decimal import Decimal
from typing import ClassVar

from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)
from app.utils.timezone_util import utc_now


class AgentSession(Base, UserOwnedMixin, TimestampMixin, SoftDeleteMixin):
    """Session metadata tracking agent conversations."""

    __tablename__ = "agent_sessions"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    TYPE_CHAT: ClassVar[str] = "chat"
    TYPE_SYSTEM: ClassVar[str] = "system"
    TYPE_SCHEDULED: ClassVar[str] = "scheduled"

    # Accept externally provided UUIDs; no default generation here
    id = Column(UUID(as_uuid=True), primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)  # TODO: remove this column in the future
    module_key = Column(String(64), nullable=True)
    summary = Column(Text, nullable=True)
    cardbox_name = Column(String(255), nullable=True, index=True)
    is_favorite = Column(Boolean, nullable=False, default=False)
    session_type = Column(
        String(32),
        nullable=False,
        default=TYPE_CHAT,
        server_default=TYPE_CHAT,
        comment="Session classification: chat/system/scheduled",
    )
    prompt_tokens_total = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Accumulated prompt tokens for the session",
    )
    completion_tokens_total = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Accumulated completion tokens for the session",
    )
    total_tokens_total = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Accumulated total tokens for the session",
    )
    cost_usd_total = Column(
        Numeric(10, 6),
        nullable=False,
        default=Decimal("0"),
        comment="Accumulated USD cost for the session",
    )
    last_activity_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: utc_now(),
    )

    messages = relationship("AgentMessage", back_populates="session")

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity_at = utc_now()

    def __repr__(self) -> str:
        return (
            f"<AgentSession(id={self.id}, name='{self.name}', user_id={self.user_id},"
            f" cardbox='{self.cardbox_name}')>"
        )


__all__ = ["AgentSession"]
