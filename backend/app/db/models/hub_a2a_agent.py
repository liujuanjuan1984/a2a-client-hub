"""Admin-managed global A2A agent catalog model."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON, UUID

from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
)


class HubA2AAgent(Base, TimestampMixin, SoftDeleteMixin):
    """Global (admin-managed) A2A agent entry."""

    __tablename__ = "hub_a2a_agents"
    __table_args__ = {"schema": SCHEMA_NAME}

    name = Column(
        String(120),
        nullable=False,
        comment="Admin-managed label for the hub A2A agent",
    )
    card_url = Column(
        String(1024),
        nullable=False,
        comment="Agent card URL",
    )
    availability_policy = Column(
        String(32),
        nullable=False,
        default="public",
        server_default="public",
        comment="Availability policy (public/allowlist)",
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
        comment="Whether this hub agent is enabled for invocation",
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
    created_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Admin user id that created this agent",
    )
    updated_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="RESTRICT"),
        nullable=True,
        comment="Admin user id that last updated this agent",
    )

    def __repr__(self) -> str:
        return (
            f"<HubA2AAgent(id={self.id}, name={self.name}, card_url={self.card_url}, "
            f"availability_policy={self.availability_policy}, enabled={self.enabled})>"
        )


__all__ = ["HubA2AAgent"]

