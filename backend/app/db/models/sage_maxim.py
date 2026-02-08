"""Sage Maxim models for storing public wisdom quotes and reactions."""

from uuid import uuid4

from sqlalchemy import Column, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)


class SageMaxim(Base, TimestampMixin, SoftDeleteMixin, UserOwnedMixin):
    """Public wisdom entry authored by a user."""

    __tablename__ = "sage_maxims"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    content = Column(
        Text,
        nullable=False,
        comment="Maxim content provided by the author",
    )
    language = Column(
        String(16),
        nullable=False,
        default="zh-CN",
        server_default="zh-CN",
        comment="ISO language tag for the maxim",
    )
    random_weight = Column(
        String(36),
        nullable=False,
        default="",
        server_default="",
        comment="Random seed helper for lightweight shuffling",
    )
    like_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Number of positive reactions",
    )
    dislike_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Number of negative reactions",
    )

    author = relationship(
        "User",
        backref="sage_maxims",
        lazy="joined",
    )
    reactions = relationship(
        "SageMaximReaction",
        back_populates="maxim",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def refresh_random_weight(self) -> None:
        """Assign a new random weight string for shuffle ordering."""
        self.random_weight = str(uuid4())


class SageMaximReaction(Base, TimestampMixin):
    """Single user reaction (like or dislike) for a maxim."""

    __tablename__ = "sage_maxim_reactions"
    __table_args__ = (
        UniqueConstraint("maxim_id", "user_id", name="uq_sage_maxim_reaction"),
        {"schema": SCHEMA_NAME},
    )

    maxim_id = Column(
        ForeignKey(f"{SCHEMA_NAME}.sage_maxims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reaction_type = Column(
        Enum(
            "like",
            "dislike",
            name="sage_maxim_reaction_type",
            schema=SCHEMA_NAME,
        ),
        nullable=False,
        comment="User reaction type",
    )

    maxim = relationship("SageMaxim", back_populates="reactions", lazy="joined")


__all__ = ["SageMaxim", "SageMaximReaction"]
