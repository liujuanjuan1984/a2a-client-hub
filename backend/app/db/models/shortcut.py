"""Shortcut model for user-side quick prompts and custom command entries."""

from __future__ import annotations

from typing import ClassVar

from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class Shortcut(Base, TimestampMixin, UserOwnedMixin):
    """User-defined shortcut/preset entries for chat prompt augmentation."""

    __tablename__ = "user_shortcuts"
    __table_args__ = (
        Index("ix_user_shortcuts_user_id", "user_id"),
        Index("ix_user_shortcuts_user_sort_order", "user_id", "sort_order"),
        Index("ix_user_shortcuts_agent_id", "agent_id"),
        {"schema": SCHEMA_NAME},
    )

    TITLE_MAX_LENGTH: ClassVar[int] = 120
    PROMPT_MAX_LENGTH: ClassVar[int] = 4000
    ORDER_MIN: ClassVar[int] = 0

    title = Column(
        String(TITLE_MAX_LENGTH),
        nullable=False,
        comment="Shortcut title shown in picker list",
    )
    prompt = Column(
        Text,
        nullable=False,
        comment="Prompt text sent to conversation when selected",
    )
    is_default = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether this is a system default shortcut",
    )
    sort_order = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Display order within user-visible shortcut list",
    )
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.a2a_agents.id", ondelete="CASCADE"),
        nullable=True,
        comment="If set, shortcut only applies to this specific agent",
    )

    def __repr__(self) -> str:
        return (
            f"<Shortcut(id={self.id}, user_id={self.user_id}, agent_id={self.agent_id}, title={self.title}, "
            f"is_default={self.is_default}, sort_order={self.sort_order})>"
        )
