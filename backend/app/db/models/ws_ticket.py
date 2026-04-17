"""WebSocket ticket model for short-lived WS authentication."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Index, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class WsTicket(Base, TimestampMixin, UserOwnedMixin):
    """One-time WebSocket ticket bound to a user and an invocation scope."""

    __tablename__ = "ws_tickets"
    __table_args__ = (
        Index("ix_ws_tickets_expires_at", "expires_at"),
        {"schema": SCHEMA_NAME},
    )

    scope_type = Column(
        String(32),
        nullable=True,
        index=True,
        comment="Scope type for this ticket (e.g., me_a2a_agent, hub_a2a_agent)",
    )
    scope_id = Column(
        "agent_id",
        PG_UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Scope identifier (UUID) bound to this ticket",
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
