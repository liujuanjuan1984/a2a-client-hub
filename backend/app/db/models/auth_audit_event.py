"""Authentication audit event model."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin


class AuthAuditEvent(Base, TimestampMixin):
    """Structured auth activity audit record."""

    __tablename__ = "auth_audit_events"
    __table_args__ = (
        Index(
            "ix_auth_audit_events_user_id_created_at",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_auth_audit_events_event_type_created_at",
            "event_type",
            "created_at",
        ),
        {"schema": SCHEMA_NAME},
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Associated user, when known.",
    )
    session_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        comment="Associated refresh session id, when known.",
    )
    session_jti = Column(
        String(64),
        nullable=True,
        comment="Associated refresh JWT jti, when known.",
    )
    email = Column(
        String(255),
        nullable=True,
        comment="Principal email used for login-related events.",
    )
    event_type = Column(
        String(64),
        nullable=False,
        comment="Auth event type: login_success/login_failed/etc.",
    )
    outcome = Column(
        String(24),
        nullable=False,
        comment="Outcome bucket: success/failed/revoked/blocked.",
    )
    ip_address = Column(
        String(64),
        nullable=True,
        comment="Observed client IP address.",
    )
    user_agent = Column(
        String(512),
        nullable=True,
        comment="Observed client User-Agent header.",
    )
    event_metadata = Column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Structured auth event metadata.",
    )
    occurred_at = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Semantic occurrence timestamp for the auth event.",
    )
