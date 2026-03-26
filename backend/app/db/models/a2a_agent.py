"""Unified A2A agent configuration model."""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON, UUID

from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)


class A2AAgent(Base, TimestampMixin, SoftDeleteMixin, UserOwnedMixin):
    """Unified A2A agent configuration (personal + shared)."""

    __tablename__ = "a2a_agents"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "agent_scope",
            "card_url",
            name="uq_a2a_agents_user_scope_card_url",
        ),
        {"schema": SCHEMA_NAME},
    )

    SCOPE_PERSONAL = "personal"
    SCOPE_SHARED = "shared"
    CREDENTIAL_NONE = "none"
    CREDENTIAL_SHARED = "shared"
    CREDENTIAL_USER = "user"
    HEALTH_UNKNOWN = "unknown"
    HEALTH_HEALTHY = "healthy"
    HEALTH_DEGRADED = "degraded"
    HEALTH_UNAVAILABLE = "unavailable"

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
    agent_scope = Column(
        String(16),
        nullable=False,
        default=SCOPE_PERSONAL,
        server_default=SCOPE_PERSONAL,
        comment="Agent scope (personal/shared).",
    )
    availability_policy = Column(
        String(32),
        nullable=False,
        default="public",
        server_default="public",
        comment="Availability policy (public/allowlist).",
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
    credential_mode = Column(
        String(16),
        nullable=False,
        default=CREDENTIAL_NONE,
        server_default=CREDENTIAL_NONE,
        index=True,
        comment="Credential source mode (none/shared/user).",
    )
    enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="Whether this agent is enabled for invocation",
    )
    health_status = Column(
        String(16),
        nullable=False,
        default=HEALTH_UNKNOWN,
        server_default=HEALTH_UNKNOWN,
        index=True,
        comment="Latest persisted health check status.",
    )
    consecutive_health_check_failures = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Consecutive failed health checks.",
    )
    last_health_check_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the latest health check attempt.",
    )
    last_successful_health_check_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the latest successful health check attempt.",
    )
    last_health_check_error = Column(
        Text,
        nullable=True,
        comment="Latest persisted health check error summary.",
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
        nullable=True,
        comment="Admin user id that created this shared agent.",
    )
    updated_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="RESTRICT"),
        nullable=True,
        comment="Admin user id that last updated this shared agent.",
    )

    def __repr__(self) -> str:
        return (
            f"<A2AAgent(id={self.id}, user_id={self.user_id}, name={self.name}, "
            f"card_url={self.card_url}, auth_type={self.auth_type}, enabled={self.enabled})>"
        )


__all__ = ["A2AAgent"]
