"""
User LLM credential model for storing BYOT secrets.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)


class UserLlmCredential(Base, TimestampMixin, SoftDeleteMixin, UserOwnedMixin):
    """User-supplied LLM credentials (encrypted)."""

    __tablename__ = "user_llm_credentials"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "display_name",
            name="uq_user_llm_credentials_user_label",
        ),
        {"schema": SCHEMA_NAME},
    )

    provider = Column(
        String(64),
        nullable=False,
        default="openai",
        comment="Provider key (e.g., openai, azure-openai, custom)",
    )
    display_name = Column(
        String(120),
        nullable=True,
        comment="User-friendly label for the credential",
    )
    api_base = Column(
        String(255),
        nullable=True,
        comment="Optional override for provider base URL",
    )
    model_override = Column(
        String(255),
        nullable=True,
        comment="Preferred model when using this credential",
    )
    encrypted_api_key = Column(
        Text,
        nullable=False,
        comment="Encrypted API token (Fernet)",
    )
    token_last4 = Column(
        String(12),
        nullable=True,
        comment="Last four characters of the plain token for display",
    )
    encryption_version = Column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="Secret encryption version",
    )
    is_default = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether this credential is the default for the user",
    )
    last_used_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the last successful usage",
    )

    def __repr__(self) -> str:
        return (
            f"<UserLlmCredential(id={self.id}, user_id={self.user_id}, "
            f"provider={self.provider}, display_name={self.display_name}, "
            f"is_default={self.is_default})>"
        )


__all__ = ["UserLlmCredential"]
