"""Async agent message handlers."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.agent_message import AgentMessage
from app.db.transaction import commit_safely

logger = get_logger(__name__)


class AgentMessageCreationError(Exception):
    """Raised when agent message creation or persistence fails."""


async def create_agent_message(
    db: AsyncSession,
    *,
    user_id: UUID,
    content: str,
    sender: str,
    conversation_id: Optional[UUID] = None,
    sync_to_cardbox: bool = True,
    **kwargs,
) -> AgentMessage:
    """Create a new agent message asynchronously."""
    try:
        metadata = kwargs.pop("metadata", None)
        if "message_metadata" in kwargs and metadata is None:
            metadata = kwargs.pop("message_metadata")
        agent_message = AgentMessage(
            content=content,
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


async def list_agent_messages(
    db: AsyncSession,
    *,
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
    conversation_id: UUID,
) -> List[AgentMessage]:
    sender_priority = case(
        (AgentMessage.sender.in_(["user", "automation"]), 0),
        else_=1,
    )

    stmt = select(AgentMessage).where(
        AgentMessage.user_id == user_id,
        AgentMessage.conversation_id == conversation_id,
    )

    stmt = (
        stmt.order_by(
            AgentMessage.created_at.asc(),
            sender_priority.asc(),
            AgentMessage.id.asc(),
        )
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_recent_agent_messages(
    db: AsyncSession,
    *,
    user_id: UUID,
    limit: int = 50,
    conversation_id: UUID,
) -> List[AgentMessage]:
    stmt = select(AgentMessage).where(
        AgentMessage.user_id == user_id,
        AgentMessage.conversation_id == conversation_id,
    )
    stmt = stmt.order_by(
        AgentMessage.created_at.desc(),
        AgentMessage.id.desc(),
    ).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_agent_messages(
    db: AsyncSession,
    *,
    user_id: UUID,
    conversation_id: UUID,
) -> int:
    stmt = select(func.count(AgentMessage.id)).where(
        AgentMessage.user_id == user_id,
        AgentMessage.conversation_id == conversation_id,
    )
    result = await db.execute(stmt)
    return int(result.scalar_one())


async def get_conversation_history(
    db: AsyncSession,
    *,
    user_id: UUID,
    limit: int = 20,
    conversation_id: UUID,
) -> List[AgentMessage]:
    stmt = select(AgentMessage).where(
        AgentMessage.user_id == user_id,
        AgentMessage.conversation_id == conversation_id,
    )

    stmt = stmt.order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc()).limit(
        limit
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def delete_agent_messages(db: AsyncSession, *, user_id: UUID) -> int:
    stmt = delete(AgentMessage).where(AgentMessage.user_id == user_id)
    result = await db.execute(stmt)
    return int(result.rowcount or 0)


async def delete_agent_messages_by_conversation(
    db: AsyncSession, *, user_id: UUID, conversation_id: UUID
) -> int:
    stmt = delete(AgentMessage).where(
        AgentMessage.user_id == user_id,
        AgentMessage.conversation_id == conversation_id,
    )
    result = await db.execute(stmt)
    return int(result.rowcount or 0)


async def commit_agent_messages(db: AsyncSession) -> None:
    """Commit message changes."""
    try:
        await commit_safely(db)
    except Exception as exc:  # pragma: no cover - defensive
        raise AgentMessageCreationError(
            f"Failed to commit agent messages: {exc}"
        ) from exc


async def update_agent_message(
    db: AsyncSession, *, message: AgentMessage, **kwargs
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


__all__ = [
    "AgentMessageCreationError",
    "commit_agent_messages",
    "count_agent_messages",
    "create_agent_message",
    "delete_agent_messages",
    "delete_agent_messages_by_conversation",
    "get_conversation_history",
    "list_agent_messages",
    "list_recent_agent_messages",
    "update_agent_message",
]
