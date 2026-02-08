"""
Tag SQLAlchemy model

This model represents a unified tagging system for categorizing various entities.
Examples: "family", "important", "work", "personal", etc.
"""

from sqlalchemy import Column, Index, String, Text

from app.db.mixins.user_filter import UserFilterMixin
from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)


class Tag(Base, UserOwnedMixin, TimestampMixin, SoftDeleteMixin, UserFilterMixin):
    """
    Unified Tag model for categorizing various entities

    This model stores tags that can be applied to different types of entities
    such as persons, notes, tasks, visions, etc.
    """

    __tablename__ = "tags"
    __table_args__ = (
        # Ensure tag names are scoped by entity type + category (among non-deleted tags)
        Index("ix_tags_name_entity_type_category", "name", "entity_type", "category"),
        {"schema": SCHEMA_NAME},
    )

    # Tag name (must be unique among non-deleted tags of the same entity type)
    name = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Tag name (e.g., 'family', 'important', 'work', 'personal')",
    )

    # Entity type this tag is designed for
    entity_type = Column(
        String(50),
        nullable=False,
        default="general",
        index=True,
        comment="Entity type this tag is designed for: 'person', 'note', 'task', 'vision', 'general'",
    )
    category = Column(
        String(50),
        nullable=False,
        default="general",
        index=True,
        comment="Tag category for semantic grouping (e.g., 'general', 'location')",
    )

    # Optional description for the tag
    description = Column(
        Text,
        nullable=True,
        comment="Optional description explaining the purpose of this tag",
    )

    # Optional color for visual representation
    color = Column(
        String(7),
        nullable=True,
        comment="Color code for this tag (hex format, e.g., '#3B82F6')",
    )

    def __repr__(self):
        return f"<Tag(id={self.id}, name='{self.name}', entity_type='{self.entity_type}', deleted_at={self.deleted_at})>"

    def to_dict(self) -> dict:
        """Convert Tag instance to dictionary"""
        return {
            "id": self.id,
            "name": self.name,
            "entity_type": self.entity_type,
            "category": self.category,
            "description": self.description,
            "color": self.color,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
