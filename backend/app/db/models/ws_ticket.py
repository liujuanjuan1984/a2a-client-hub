"""WebSocket ticket model for short-lived WS authentication."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class WsTicket(Base, TimestampMixin, UserOwnedMixin):
    """One-time WebSocket ticket bound to a user and agent."""

    __tablename__ = "ws_tickets"
    __table_args__ = (
        Index("ix_ws_tickets_expires_at", "expires_at"),
        {"schema": SCHEMA_NAME},
    )

    agent_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.a2a_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="A2A agent bound to the ticket",
    )
    token_hash = Column(
        String(64),
        nullable=False,
        unique=True,
        comment="HMAC-SHA256 hash of the WS ticket",
    )
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Ticket expiration timestamp",
    )
    used_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when the ticket was consumed",
    )


__all__ = ["WsTicket"]
