"""
Tag Association Tables

This module defines the many-to-many association table between Tags and various entities.
This table enables the unified tagging system across all domain entities.
"""

from sqlalchemy import Column, ForeignKey, Index, String, Table
from sqlalchemy.dialects.postgresql import UUID

from app.db.models.base import SCHEMA_NAME, Base

# Tag-Entity association table
tag_associations = Table(
    "tag_associations",
    Base.metadata,
    Column(
        "entity_id",
        UUID(as_uuid=True),
        nullable=False,
        primary_key=True,
        comment="ID of the entity being tagged",
    ),
    Column(
        "entity_type",
        String(50),
        nullable=False,
        primary_key=True,
        comment="Type of the entity being tagged (e.g., 'person', 'note', 'task')",
    ),
    Column(
        "tag_id",
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.tags.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
        comment="ID of the tag being applied",
    ),
    # Prevent duplicate tag associations for the same entity
    # Common query patterns
    Index("ix_tag_associations_entity", "entity_type", "entity_id"),
    Index("ix_tag_associations_tag", "tag_id"),
    schema=SCHEMA_NAME,
)
