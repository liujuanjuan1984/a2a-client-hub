"""Encrypted system-managed credentials for hub A2A agents."""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin


class HubA2AAgentCredential(Base, TimestampMixin):
    """Bearer token credential for a hub A2A agent (system-managed)."""

    __tablename__ = "hub_a2a_agent_credentials"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            name="uq_hub_a2a_agent_credentials_agent",
        ),
        {"schema": SCHEMA_NAME},
    )

    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.hub_a2a_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Related hub A2A agent id",
    )
    encrypted_token = Column(
        Text,
        nullable=False,
        comment="Encrypted bearer token (Fernet)",
    )
    token_last4 = Column(
        String(12),
        nullable=True,
        comment="Last four characters of the token for display",
    )
    encryption_version = Column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="Secret encryption version",
    )
    created_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Admin user id that created/updated the credential",
    )

    def __repr__(self) -> str:
        return f"<HubA2AAgentCredential(id={self.id}, agent_id={self.agent_id})>"


__all__ = ["HubA2AAgentCredential"]
