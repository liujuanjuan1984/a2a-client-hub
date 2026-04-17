"""Allowlist entries for A2A proxy hosts."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, String, Text

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin


class A2AProxyAllowlist(Base, TimestampMixin):
    """Allowlist entry for A2A proxy hosts."""

    __tablename__ = "a2a_proxy_allowlist"
    __table_args__ = {"schema": SCHEMA_NAME}

    host_pattern = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="The host pattern allowed (e.g., example.com, *.openai.com)",
    )
    is_enabled = Column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        comment="Whether this allowlist entry is active",
    )
    remark = Column(
        Text,
        nullable=True,
        comment="Remark or reason for this allowlist entry",
    )

    def __repr__(self) -> str:
        return f"<A2AProxyAllowlist(id={self.id}, host_pattern={self.host_pattern}, is_enabled={self.is_enabled})>"
