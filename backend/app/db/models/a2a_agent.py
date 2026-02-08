"""User-managed A2A agent configuration model."""

from sqlalchemy import Boolean, Column, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON

from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)


class A2AAgent(Base, TimestampMixin, SoftDeleteMixin, UserOwnedMixin):
    """User-managed A2A agent configuration."""

    __tablename__ = "a2a_agents"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "card_url",
            name="uq_a2a_agents_user_card_url",
        ),
        {"schema": SCHEMA_NAME},
    )

    name = Column(
        String(120),
        nullable=False,
        comment="User-facing label for the A2A agent",
    )
    card_url = Column(
        String(1024),
        nullable=False,
        comment="Agent card URL",
    )
    auth_type = Column(
        String(32),
        nullable=False,
        default="none",
        server_default="none",
        comment="Authentication type (none/bearer)",
    )
    auth_header = Column(
        String(120),
        nullable=True,
        comment="HTTP header name for auth (e.g., Authorization)",
    )
    auth_scheme = Column(
        String(64),
        nullable=True,
        comment="Authentication scheme (e.g., Bearer)",
    )
    enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="Whether this agent is enabled for invocation",
    )
    tags = Column(
        JSON,
        nullable=True,
        comment="Optional tags as JSON array",
    )
    extra_headers = Column(
        JSON,
        nullable=True,
        comment="Additional headers to include when fetching card/invoking",
    )

    def __repr__(self) -> str:
        return (
            f"<A2AAgent(id={self.id}, user_id={self.user_id}, name={self.name}, "
            f"card_url={self.card_url}, auth_type={self.auth_type}, enabled={self.enabled})>"
        )


__all__ = ["A2AAgent"]
