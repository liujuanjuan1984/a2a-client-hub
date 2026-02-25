"""Async handlers for streaming message chunks."""

from __future__ import annotations

from typing import Iterable
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message_chunk import AgentMessageChunk


async def list_chunks_by_message_ids(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_ids: Iterable[UUID],
) -> list[AgentMessageChunk]:
    ids = list(message_ids)
    if not ids:
        return []
    stmt = (
        select(AgentMessageChunk)
        .where(
            and_(
                AgentMessageChunk.user_id == user_id,
                AgentMessageChunk.message_id.in_(ids),
            )
        )
        .order_by(
            AgentMessageChunk.message_id.asc(),
            AgentMessageChunk.seq.asc(),
            AgentMessageChunk.created_at.asc(),
            AgentMessageChunk.id.asc(),
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def find_chunk_by_message_and_seq(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
    seq: int,
) -> AgentMessageChunk | None:
    stmt = (
        select(AgentMessageChunk)
        .where(
            and_(
                AgentMessageChunk.user_id == user_id,
                AgentMessageChunk.message_id == message_id,
                AgentMessageChunk.seq == seq,
            )
        )
        .limit(1)
    )
    return await db.scalar(stmt)


async def find_chunk_by_message_and_event_id(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
    event_id: str,
) -> AgentMessageChunk | None:
    stmt = (
        select(AgentMessageChunk)
        .where(
            and_(
                AgentMessageChunk.user_id == user_id,
                AgentMessageChunk.message_id == message_id,
                AgentMessageChunk.event_id == event_id,
            )
        )
        .limit(1)
    )
    return await db.scalar(stmt)


async def has_chunks_for_message(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
) -> bool:
    stmt = (
        select(AgentMessageChunk.id)
        .where(
            and_(
                AgentMessageChunk.user_id == user_id,
                AgentMessageChunk.message_id == message_id,
            )
        )
        .limit(1)
    )
    return (await db.scalar(stmt)) is not None


async def create_chunk(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
    seq: int,
    block_type: str,
    content: str,
    append: bool,
    is_finished: bool,
    event_id: str | None = None,
    source: str | None = None,
) -> AgentMessageChunk:
    chunk = AgentMessageChunk(
        user_id=user_id,
        message_id=message_id,
        seq=seq,
        event_id=event_id,
        block_type=block_type,
        content=content,
        append=append,
        is_finished=is_finished,
        source=source,
    )
    db.add(chunk)
    await db.flush()
    return chunk


__all__ = [
    "create_chunk",
    "find_chunk_by_message_and_event_id",
    "find_chunk_by_message_and_seq",
    "has_chunks_for_message",
    "list_chunks_by_message_ids",
]
