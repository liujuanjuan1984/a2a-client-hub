"""
User Preference SQLAlchemy model

This model stores user-specific preference settings in a simplified key-value format.
Each user can have multiple preference records, but only one record per key.
"""

from sqlalchemy import Column, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)


class UserPreference(Base, UserOwnedMixin, TimestampMixin, SoftDeleteMixin):
    """
    User preference model for storing user-specific settings

    This model uses a simplified key-value approach where:
    - Each user can have multiple preference records
    - Each user can only have one record per key (enforced by unique constraint)
    - All values are stored as JSONB for maximum flexibility
    - Module field for organization and filtering
    """

    __tablename__ = "user_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_preferences_user_key"),
        {"schema": SCHEMA_NAME},
    )

    # Primary key
    # id is UUID via TimestampMixin

    # Preference identification
    key = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Preference key (e.g., 'theme', 'language', 'notifications.email')",
    )

    # Value storage (using JSONB for all types)
    value = Column(JSONB, nullable=False, comment="Preference value stored as JSON")

    # Module/category for organization
    module = Column(
        String(50),
        index=True,
        nullable=False,
        default="general",
        comment="Module or category this preference belongs to (e.g., 'ui', 'notifications', 'calendar')",
    )

    def __repr__(self) -> str:
        return f"<UserPreference(id={self.id}, user_id={self.user_id}, key='{self.key}', value={self.value})>"
