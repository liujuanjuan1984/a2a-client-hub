"""User-owned credentials for shared hub A2A agents."""

from sqlalchemy import Column, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin


class HubA2AUserCredential(Base, TimestampMixin):
    """User-provided auth payload for a shared A2A agent."""

    __tablename__ = "hub_a2a_user_credentials"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "user_id",
            name="uq_hub_a2a_user_credentials_agent_user",
        ),
        {"schema": SCHEMA_NAME},
    )

    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.a2a_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Related shared A2A agent id",
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Owning user id",
    )
    encrypted_token = Column(
        Text,
        nullable=False,
        comment="Encrypted auth payload (Fernet)",
    )
    auth_type = Column(
        String(24),
        nullable=False,
        comment="Auth type used when the user credential payload was stored",
    )
    token_last4 = Column(
        String(12),
        nullable=True,
        comment="Preview for bearer-style secrets",
    )
    username_hint = Column(
        String(120),
        nullable=True,
        comment="Non-secret username hint for basic auth credentials",
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
            f"<HubA2AUserCredential(id={self.id}, agent_id={self.agent_id}, "
            f"user_id={self.user_id})>"
        )


__all__ = ["HubA2AUserCredential"]
