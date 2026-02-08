"""
Generic Association SQLAlchemy model

This model represents flexible, low-frequency, contextual links between
any two domain entities using a directional edge: source -> target.
"""

from sqlalchemy import JSON, Column, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)


class Association(Base, UserOwnedMixin, TimestampMixin, SoftDeleteMixin):
    """Generic, flexible association to connect any two domain entities.

    Examples:
        - Note -> Person (link_type='is_about' or 'mentions')
        - ActualEvent -> Person (link_type='attended_by')
        - Vision -> Person (link_type='involves')
    """

    __tablename__ = "associations"
    __table_args__ = (
        # Prevent duplicate semantic edges
        UniqueConstraint(
            "source_model",
            "source_id",
            "target_model",
            "target_id",
            "link_type",
            name="uq_associations_source_target_type",
        ),
        # Common query patterns
        Index(
            "ix_associations_source_model_id_type",
            "source_model",
            "source_id",
            "link_type",
        ),
        Index(
            "ix_associations_target_model_id_type",
            "target_model",
            "target_id",
            "link_type",
        ),
        {"schema": SCHEMA_NAME},
    )

    # Primary key now UUID via TimestampMixin.id

    # Directional source endpoint
    source_model = Column(String(100), nullable=False, index=True)
    source_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Directional target endpoint
    target_model = Column(String(100), nullable=False, index=True)
    target_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Semantic type of the relationship
    link_type = Column(String(50), nullable=False, index=True)

    # Optional metadata for extensibility (role, tags, source channel, etc.)
    extra_data = Column(JSON, nullable=True)
