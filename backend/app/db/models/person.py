"""
Person SQLAlchemy model

This model represents people in the user's social network.
Each person can be associated with various activities, tasks, visions, etc.
"""

from sqlalchemy import JSON, Column, Date, String, and_
from sqlalchemy.orm import relationship
from sqlalchemy.orm.attributes import flag_modified

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


class Person(Base, UserOwnedMixin, TimestampMixin, SoftDeleteMixin, UserFilterMixin):
    """
    Person model representing people in the user's social network

    This model stores core information about people and enables
    social dimension tracking across all activities.
    """

    __tablename__ = "persons"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    # Basic person information
    name = Column(
        String(200),
        nullable=True,
        index=True,
        comment="Person's name (can be null for anonymous contacts)",
    )
    nicknames = Column(
        JSON,
        nullable=True,
        comment="Array of nicknames/aliases for this person",
    )
    birth_date = Column(
        Date,
        nullable=True,
        comment="Person's birth date",
    )
    location = Column(
        String(100),
        index=True,
        nullable=True,
        comment="Person's location or address",
    )

    # Relationships with tags (many-to-many)
    tags = relationship(
        "Tag",
        secondary=tag_associations,
        primaryjoin=lambda: and_(
            Person.id == tag_associations.c.entity_id,
            tag_associations.c.entity_type == "person",
        ),
        secondaryjoin=lambda: Tag.id == tag_associations.c.tag_id,
        viewonly=True,
        cascade="save-update, merge",
        lazy="selectin",
    )

    # Relationship with anniversaries (one-to-many)
    anniversaries = relationship(
        "Anniversary",
        back_populates="person",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        display_name = self.name or f"Person#{self.id}"
        return f"<Person(id={self.id}, name='{display_name}', deleted_at={self.deleted_at})>"

    def soft_delete(self) -> None:
        """Mark the person as soft deleted via SoftDeleteMixin"""
        super().soft_delete()

    def restore(self) -> None:
        """Restore a soft deleted person via SoftDeleteMixin"""
        super().restore()

    @property
    def display_name(self) -> str:
        """Get display name for the person"""
        if self.name:
            return self.name
        return f"Person #{self.id}"

    def get_primary_nickname(self) -> str:
        """Get all nicknames joined by comma, or name as primary identifier"""
        if self.nicknames and len(self.nicknames) > 0:
            return ", ".join(self.nicknames)
        return self.display_name

    def add_nickname(self, nickname: str) -> None:
        """Add a nickname to the person"""
        if self.nicknames is None:
            self.nicknames = []
        if nickname not in self.nicknames:
            self.nicknames.append(nickname)
            # Mark the field as changed for SQLAlchemy

            flag_modified(self, "nicknames")

    def remove_nickname(self, nickname: str) -> None:
        """Remove a nickname from the person"""
        if self.nicknames and nickname in self.nicknames:
            self.nicknames.remove(nickname)
            # Mark the field as changed for SQLAlchemy

            flag_modified(self, "nicknames")
