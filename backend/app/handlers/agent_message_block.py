"""Async handlers for persisted message blocks."""

from __future__ import annotations

from typing import Iterable, cast
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message_block import AgentMessageBlock


async def list_blocks_by_message_ids(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_ids: Iterable[UUID],
) -> list[AgentMessageBlock]:
    ids = list(message_ids)
    if not ids:
        return []
    stmt = (
        select(AgentMessageBlock)
        .where(
            and_(
                AgentMessageBlock.user_id == user_id,
                AgentMessageBlock.message_id.in_(ids),
            )
        )
        .order_by(
            AgentMessageBlock.message_id.asc(),
            AgentMessageBlock.block_seq.asc(),
            AgentMessageBlock.created_at.asc(),
            AgentMessageBlock.id.asc(),
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_blocks_by_message_id(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
) -> list[AgentMessageBlock]:
    stmt = (
        select(AgentMessageBlock)
        .where(
            and_(
                AgentMessageBlock.user_id == user_id,
                AgentMessageBlock.message_id == message_id,
            )
        )
        .order_by(
            AgentMessageBlock.block_seq.asc(),
            AgentMessageBlock.created_at.asc(),
            AgentMessageBlock.id.asc(),
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def find_block_by_message_and_block_seq(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
    block_seq: int,
) -> AgentMessageBlock | None:
    stmt = (
        select(AgentMessageBlock)
        .where(
            and_(
                AgentMessageBlock.user_id == user_id,
                AgentMessageBlock.message_id == message_id,
                AgentMessageBlock.block_seq == block_seq,
            )
        )
        .limit(1)
    )
    return cast(AgentMessageBlock | None, await db.scalar(stmt))


async def find_last_block_for_message(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
) -> AgentMessageBlock | None:
    stmt = (
        select(AgentMessageBlock)
        .where(
            and_(
                AgentMessageBlock.user_id == user_id,
                AgentMessageBlock.message_id == message_id,
            )
        )
        .order_by(
            AgentMessageBlock.block_seq.desc(),
            AgentMessageBlock.created_at.desc(),
            AgentMessageBlock.id.desc(),
        )
        .limit(1)
    )
    return cast(AgentMessageBlock | None, await db.scalar(stmt))


async def create_block(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
    block_seq: int,
    block_type: str,
    content: str,
    is_finished: bool,
    source: str | None = None,
    start_event_seq: int | None = None,
    end_event_seq: int | None = None,
    start_event_id: str | None = None,
    end_event_id: str | None = None,
) -> AgentMessageBlock:
    block = AgentMessageBlock(
        user_id=user_id,
        message_id=message_id,
        block_seq=block_seq,
        block_type=block_type,
        content=content,
        is_finished=is_finished,
        source=source,
        start_event_seq=start_event_seq,
        end_event_seq=end_event_seq,
        start_event_id=start_event_id,
        end_event_id=end_event_id,
    )
    db.add(block)
    await db.flush()
    return block


async def has_blocks_for_message(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
) -> bool:
    stmt = (
        select(AgentMessageBlock.id)
        .where(
            and_(
                AgentMessageBlock.user_id == user_id,
                AgentMessageBlock.message_id == message_id,
            )
        )
        .limit(1)
    )
    return (await db.scalar(stmt)) is not None


__all__ = [
    "create_block",
    "find_block_by_message_and_block_seq",
    "find_last_block_for_message",
    "has_blocks_for_message",
    "list_blocks_by_message_id",
    "list_blocks_by_message_ids",
]
