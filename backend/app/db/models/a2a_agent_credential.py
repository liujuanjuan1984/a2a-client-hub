"""Encrypted credentials for user-managed A2A agents."""

from sqlalchemy import Column, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)


class A2AAgentCredential(Base, TimestampMixin, SoftDeleteMixin, UserOwnedMixin):
    """Bearer token credential for an A2A agent."""

    __tablename__ = "a2a_agent_credentials"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "agent_id",
            name="uq_a2a_agent_credentials_user_agent",
        ),
        {"schema": SCHEMA_NAME},
    )

    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.a2a_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Related A2A agent id",
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

    def __repr__(self) -> str:
        return (
            f"<A2AAgentCredential(id={self.id}, user_id={self.user_id}, "
            f"agent_id={self.agent_id})>"
        )


__all__ = ["A2AAgentCredential"]
