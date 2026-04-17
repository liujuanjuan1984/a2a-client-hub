"""Legacy stateless refresh token revocation model."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin


class AuthLegacyRefreshRevocation(Base, TimestampMixin):
    """Persisted denylist entry for legacy refresh JWTs without server sessions."""

    __tablename__ = "auth_legacy_refresh_revocations"
    __table_args__ = (
        Index(
            "ix_auth_legacy_refresh_revocations_user_id_expires_at",
            "user_id",
            "expires_at",
        ),
        {"schema": SCHEMA_NAME},
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Owner of the revoked legacy refresh token.",
    )
    token_jti = Column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        comment="Refresh JWT jti for the revoked legacy token.",
    )
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Original token expiry timestamp for retention and cleanup.",
    )
    revoked_at = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Timestamp when the legacy refresh token was revoked.",
    )
    revoke_reason = Column(
        String(64),
        nullable=True,
        comment="Reason for revoking the legacy refresh token.",
    )
