"""Server-side refresh session model."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin


class AuthRefreshSession(Base, TimestampMixin):
    """Persisted refresh session state for cookie-auth rotation and revocation."""

    __tablename__ = "auth_refresh_sessions"
    __table_args__ = (
        Index(
            "ix_auth_refresh_sessions_user_id_revoked_at",
            "user_id",
            "revoked_at",
        ),
        {"schema": SCHEMA_NAME},
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Owner of this refresh session.",
    )
    current_jti = Column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        comment="Current accepted refresh JWT jti for this session.",
    )
    previous_jti = Column(
        String(64),
        nullable=True,
        comment="Immediately previous refresh JWT jti tolerated during rotation races.",
    )
    previous_jti_expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Expiry timestamp for short replay grace on the previous refresh JWT jti.",
    )
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Current refresh session expiry timestamp.",
    )
    last_rotated_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the latest successful refresh rotation.",
    )
    last_used_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the latest accepted refresh/logout operation.",
    )
    created_ip = Column(
        String(64),
        nullable=True,
        comment="Client IP captured when the refresh session was created.",
    )
    created_user_agent = Column(
        String(512),
        nullable=True,
        comment="Client User-Agent captured when the refresh session was created.",
    )
    last_seen_ip = Column(
        String(64),
        nullable=True,
        comment="Last client IP that used this refresh session.",
    )
    last_seen_user_agent = Column(
        String(512),
        nullable=True,
        comment="Last client User-Agent that used this refresh session.",
    )
    revoked_at = Column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Revocation timestamp (NULL means still active).",
    )
    revoke_reason = Column(
        String(64),
        nullable=True,
        comment="Reason for revocation when the session is no longer active.",
    )
