"""Base models and mixins for a2a-client-hub.

This module contains the base model classes and common mixins used across all models.
It includes schema configuration for PostgreSQL 16 support.
"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

from app.core.config import settings
from app.utils.timezone_util import utc_now

# Schema name from settings
SCHEMA_NAME = settings.schema_name

# Create Base class for models
Base = declarative_base()


class TimestampMixin:
    """
    Mixin to add id, created_at and updated_at fields to models

    This mixin provides the basic fields that most models need:
    - id: Primary key
    - created_at: Record creation timestamp
    - updated_at: Record last update timestamp
    """

    # Primary key switched to UUID v4 (Phase 2)
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        # index=True,
        default=uuid4,
        comment="Primary key (UUID v4)",
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Record creation timestamp",
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Record last update timestamp",
    )


class UserOwnedMixin:
    """
    Mixin for models that are owned by users

    Provides user_id field for user-owned entities.
    This mixin should be used for models that need user isolation.
    """

    # User ownership (UUID FK)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Data owner (UUID)",
    )


class SoftDeleteMixin:
    """
    Mixin to add soft delete functionality to models
    """

    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Soft delete timestamp (NULL means not deleted)",
    )

    def soft_delete(self) -> None:
        """Mark the record as deleted"""
        setattr(self, "deleted_at", utc_now())


# Export all classes for easy importing
