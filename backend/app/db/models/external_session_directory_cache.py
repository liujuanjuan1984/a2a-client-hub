"""Cached external provider session listings per agent.

This cache is a best-effort performance optimization for the Sessions tab:
- Source of truth remains the upstream provider.
- Entries are keyed by (user_id, provider, agent_source, agent_id).
- Payload stores a minimal, sanitized session snapshot suitable for listing.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.sql import func

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin


class ExternalSessionDirectoryCacheEntry(Base, TimestampMixin):
    """Cached external session listings for a single agent visible to a user."""

    __tablename__ = "external_session_directory_cache"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            "agent_source",
            "agent_id",
            name="uq_external_session_directory_cache_user_provider_source_agent",
        ),
        {"schema": SCHEMA_NAME},
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Cache owner (UUID)",
    )
    provider = Column(
        String(32),
        nullable=False,
        index=True,
        comment="External provider key (e.g., opencode).",
    )
    agent_source = Column(
        String(16),
        nullable=False,
        comment="Agent source scope (personal/shared)",
    )
    agent_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Agent id (UUID)",
    )
    payload = Column(
        JSON,
        nullable=False,
        default=dict,
        comment="Cached session list payload (minimal snapshot)",
    )
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="Cache expiry timestamp",
    )
    last_success_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last time this cache entry was refreshed successfully",
    )
    last_error_code = Column(
        String(64),
        nullable=True,
        comment="Last upstream error_code observed during refresh (best-effort)",
    )
    last_error_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last time an upstream error was observed during refresh",
    )

    refreshed_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Last time this cache entry payload was written",
    )

    def __repr__(self) -> str:
        return (
            f"<ExternalSessionDirectoryCacheEntry(id={self.id}, user_id={self.user_id}, "
            f"provider={self.provider}, "
            f"agent_source={self.agent_source}, agent_id={self.agent_id}, "
            f"expires_at={self.expires_at})>"
        )


__all__ = ["ExternalSessionDirectoryCacheEntry"]
