"""Allowlist entries for hub A2A agents."""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin


class HubA2AAgentAllowlistEntry(Base, TimestampMixin):
    """Allowlist entry mapping a hub agent to a user."""

    __tablename__ = "hub_a2a_agent_allowlist"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "user_id",
            name="uq_hub_a2a_agent_allowlist_agent_user",
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
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Allowlisted user id",
    )
    created_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Admin user id that created the allowlist entry",
    )

    def __repr__(self) -> str:
        return (
            f"<HubA2AAgentAllowlistEntry(id={self.id}, agent_id={self.agent_id}, "
            f"user_id={self.user_id})>"
        )


__all__ = ["HubA2AAgentAllowlistEntry"]

