"""
Note model for Common Compass Backend

This module defines the Note model for storing user notes/quick entries.
Notes are designed for instant capture with minimal structure.
"""

from sqlalchemy import Column, Text, and_
from sqlalchemy.orm import relationship

from app.db.mixins.user_filter import UserFilterMixin
from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)
from app.db.models.tag import Tag
from app.db.models.tag_associations import tag_associations


class Note(Base, UserOwnedMixin, TimestampMixin, SoftDeleteMixin, UserFilterMixin):
    """
    Model for storing user notes/quick entries

    This model is designed for the `quick notes` feature,
    supporting instant capture with minimal structure.
    """

    __tablename__ = "notes"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    content = Column(Text, nullable=False, comment="The main content of the note")

    # Relationships with tags (many-to-many)
    tags = relationship(
        "Tag",
        secondary=tag_associations,
        primaryjoin=lambda: and_(
            Note.id == tag_associations.c.entity_id,
            tag_associations.c.entity_type == "note",
        ),
        secondaryjoin=lambda: Tag.id == tag_associations.c.tag_id,
        lazy="selectin",  # Use selectin for better performance
        cascade="save-update, merge",
    )

    def __repr__(self) -> str:
        """String representation of Note instance"""
        content_preview = (
            self.content[:50] + "..." if len(self.content) > 50 else self.content
        )
        return f"<Note(id={self.id}, content='{content_preview}', created_at={self.created_at})>"
