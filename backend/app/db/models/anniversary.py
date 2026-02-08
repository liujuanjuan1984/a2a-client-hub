"""
Anniversary SQLAlchemy model

This model represents anniversaries and important dates related to people.
Examples: "first met", "wedding anniversary", "birthday", etc.
"""

from sqlalchemy import Column, Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class Anniversary(Base, UserOwnedMixin, TimestampMixin):
    """
    Anniversary model for storing important dates related to people

    This model stores special dates and anniversaries associated with people
    in the user's social network.
    """

    __tablename__ = "anniversaries"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    # id is UUID via TimestampMixin

    # Foreign key to person
    person_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.persons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID of the person this anniversary belongs to",
    )

    # Anniversary details
    name = Column(
        String(200),
        nullable=False,
        index=True,
        comment="Anniversary name (e.g., 'First Met', 'Wedding Anniversary')",
    )
    date = Column(
        Date,
        nullable=False,
        index=True,
        comment="Anniversary date",
    )

    # Relationship with person
    person = relationship("Person", back_populates="anniversaries")

    def __repr__(self):
        return f"<Anniversary(id={self.id}, name='{self.name}', date={self.date}, person_id={self.person_id})>"
