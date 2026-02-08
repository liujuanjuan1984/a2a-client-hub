"""Agent message read-state tracking."""

from sqlalchemy import Column, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin
from app.utils.timezone_util import utc_now


class AgentMessageReceipt(Base, TimestampMixin, UserOwnedMixin):
    """Track delivery and read state for agent/system messages."""

    __tablename__ = "agent_message_receipts"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "user_id",
            name="uq_agent_message_receipts_message_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        {"schema": SCHEMA_NAME},
    )

    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.agent_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    delivered_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="When the notification was enqueued for the user",
    )
    read_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when the user read the message",
    )


__all__ = ["AgentMessageReceipt"]
