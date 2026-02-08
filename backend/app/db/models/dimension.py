"""
Dimension SQLAlchemy model

This model represents life dimensions (branches of the tree of life).
Each dimension represents a different aspect of life (work, health, family, etc.).
"""

from sqlalchemy import Boolean, Column, Integer, String, Text, UniqueConstraint

from app.db.mixins.user_filter import UserFilterMixin
from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class Dimension(Base, UserOwnedMixin, TimestampMixin, UserFilterMixin):
    """
    Dimension model representing different aspects of life

    Each dimension represents a branch of the user's life tree,
    such as work, health, family, learning, creativity, etc.
    """

    __tablename__ = "dimensions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "name", name="uq_common_compass_schema_dimensions_user_name"
        ),
        {"schema": SCHEMA_NAME},
    )

    # Basic dimension information
    name = Column(
        String(100),
        nullable=False,
        index=False,
        comment="Dimension name (e.g., 'Work', 'Health', 'Family')",
    )
    description = Column(
        Text, nullable=True, comment="Detailed description of this life dimension"
    )

    # Visual properties
    color = Column(
        String(7),
        nullable=False,
        default="#3B82F6",
        comment="Color code for this dimension (hex format, e.g., '#3B82F6')",
    )
    icon = Column(
        String(50),
        nullable=True,
        comment="Icon identifier for this dimension (e.g., 'work', 'health')",
    )

    # Status and ordering
    is_active = Column(
        Boolean, default=True, comment="Whether this dimension is currently active"
    )
    display_order = Column(
        Integer, default=0, comment="Display order for this dimension"
    )

    # Note: Timestamps are inherited from TimestampMixin

    def __repr__(self):
        return f"<Dimension(id={self.id}, name='{self.name}', color='{self.color}')>"
