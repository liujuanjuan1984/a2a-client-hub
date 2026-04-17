"""Persistence helpers for stored agent messages."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import AgentMessage


class AgentMessageCreationError(Exception):
    """Raised when agent message creation or persistence fails."""


async def create_agent_message(
    db: AsyncSession,
    *,
    user_id: UUID,
    sender: str,
    conversation_id: UUID,
    sync_to_cardbox: bool = True,
    **kwargs: Any,
) -> AgentMessage:
    """Create a new agent message asynchronously."""
    try:
        metadata = kwargs.pop("metadata", None)
        if "message_metadata" in kwargs and metadata is None:
            metadata = kwargs.pop("message_metadata")
        agent_message = AgentMessage(
            sender=sender,
            user_id=user_id,
            conversation_id=conversation_id,
            message_metadata=metadata,
            **kwargs,
        )
        db.add(agent_message)
        await db.flush()

        # Cardbox sync is intentionally disabled in the A2A client backend cut.
        _ = sync_to_cardbox
        return agent_message
    except Exception as exc:
        raise AgentMessageCreationError(
            f"Failed to create agent message: {str(exc)}"
        ) from exc


async def update_agent_message(
    db: AsyncSession, *, message: AgentMessage, **kwargs: Any
) -> Optional[AgentMessage]:
    """Update agent message fields."""
    try:
        if "metadata" in kwargs and "message_metadata" not in kwargs:
            kwargs["message_metadata"] = kwargs.pop("metadata")
        for field_name, value in kwargs.items():
            if hasattr(message, field_name):
                setattr(message, field_name, value)
        await db.flush()
        return message
    except Exception as exc:
        raise AgentMessageCreationError(
            f"Failed to update agent message: {str(exc)}"
        ) from exc
