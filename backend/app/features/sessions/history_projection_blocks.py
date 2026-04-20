"""Block projection helpers for the unified session history domain."""

from __future__ import annotations

import re
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.features.sessions import block_store
from app.features.sessions import common as session_common
from app.utils.session_identity import normalize_non_empty_text

BLOCK_OPERATION_TYPES = frozenset({"append", "replace", "finalize"})
REASONING_OVERLAP_WORD_PATTERN = re.compile(r"[\w]+", re.UNICODE)
MIN_REASONING_OVERLAP_WORD_LENGTH = 5


def _default_lane_id(block_type: str) -> str:
    return "primary_text" if block_type == "text" else block_type


def normalize_message_block_specs(
    block_specs: list[dict[str, Any]] | None,
) -> list[dict[str, str | None]]:
    normalized_specs: list[dict[str, str | None]] = []
    for index, raw_spec in enumerate(block_specs or []):
        block_type = session_common.normalize_block_type(
            normalize_non_empty_text(raw_spec.get("block_type"))
            or normalize_non_empty_text(raw_spec.get("type"))
            or "text"
        )
        content = raw_spec.get("content")
        if not isinstance(content, str):
            continue
        source = normalize_non_empty_text(raw_spec.get("source"))
        normalized_specs.append(
            {
                "block_type": block_type,
                "content": content,
                "source": source or "finalize_snapshot",
                "block_id": (
                    normalize_non_empty_text(raw_spec.get("block_id"))
                    or f"persisted:{block_type}:{index + 1}"
                ),
                "lane_id": (
                    normalize_non_empty_text(raw_spec.get("lane_id"))
                    or _default_lane_id(block_type)
                ),
            }
        )
    return normalized_specs


async def apply_message_block_specs(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
    block_specs: list[dict[str, str | None]],
    idempotency_key: str | None,
) -> None:
    if not block_specs:
        return
    existing_blocks = await block_store.list_blocks_by_message_id(
        db,
        user_id=user_id,
        message_id=message_id,
    )
    if existing_blocks:
        if len(existing_blocks) != len(block_specs):
            raise ValueError("idempotency_conflict")
        for existing_block, expected_spec in zip(
            existing_blocks, block_specs, strict=True
        ):
            if (
                session_common.normalize_block_type(
                    cast(str | None, existing_block.block_type)
                )
                != expected_spec["block_type"]
                or (cast(str | None, existing_block.content) or "")
                != (expected_spec["content"] or "")
                or normalize_non_empty_text(cast(str | None, existing_block.source))
                != normalize_non_empty_text(expected_spec["source"])
            ):
                raise ValueError("idempotency_conflict")
        return

    for index, block_spec in enumerate(block_specs, start=1):
        persisted_block = await session_common.create_block_with_conflict_recovery(
            db,
            user_id=user_id,
            message_id=message_id,
            block_seq=index,
            block_id=cast(str, block_spec["block_id"]),
            lane_id=cast(str, block_spec["lane_id"]),
            block_type=cast(str, block_spec["block_type"]),
            content=cast(str, block_spec["content"]),
            is_finished=True,
            source=block_spec["source"],
            start_event_seq=None,
            end_event_seq=None,
            base_seq=None,
            start_event_id=None,
            end_event_id=None,
        )
        if persisted_block is None and idempotency_key:
            raise ValueError("idempotency_conflict")


def _should_preserve_existing_interrupt_content(
    *,
    block_type: str,
    operation: str,
    incoming_content: str,
) -> bool:
    if block_type != "interrupt_event" or operation != "replace":
        return False
    _, interrupt = session_common.deserialize_interrupt_event_block_content(
        incoming_content
    )
    return bool(interrupt and interrupt.get("phase") == "resolved")


def _normalize_block_operation(
    operation: str | None,
    *,
    append: bool,
    source: str | None,
) -> str:
    normalized = normalize_non_empty_text(operation)
    if normalized in BLOCK_OPERATION_TYPES:
        return normalized
    if session_common.is_primary_text_snapshot_source(source):
        return "replace"
    return "append" if append else "replace"


def _is_word_char(value: str | None) -> bool:
    return bool(value and REASONING_OVERLAP_WORD_PATTERN.fullmatch(value))


def _is_boundary_aligned_reasoning_overlap(
    reasoning_content: str,
    text: str,
    overlap: int,
) -> bool:
    overlap_start = len(reasoning_content) - overlap
    before_overlap = reasoning_content[overlap_start - 1] if overlap_start > 0 else None
    after_overlap = text[overlap] if overlap < len(text) else None
    return not _is_word_char(before_overlap) and not _is_word_char(after_overlap)


def _is_substantial_reasoning_overlap(candidate: str) -> bool:
    tokens = REASONING_OVERLAP_WORD_PATTERN.findall(candidate)
    return len(tokens) >= 2 or any(
        len(token) >= MIN_REASONING_OVERLAP_WORD_LENGTH for token in tokens
    )


def _trim_overlapping_reasoning_prefix(
    reasoning_content: str,
    text: str,
) -> str:
    if not reasoning_content or not text:
        return text
    for overlap in range(min(len(reasoning_content), len(text)), 0, -1):
        candidate = reasoning_content[-overlap:]
        if (
            text.startswith(candidate)
            and _is_boundary_aligned_reasoning_overlap(reasoning_content, text, overlap)
            and _is_substantial_reasoning_overlap(candidate)
        ):
            return re.sub(r"^\s+", "", text[overlap:])
    return text


def _update_block_event_metadata(
    block: AgentMessageBlock,
    *,
    seq: int,
    event_id: str | None,
    source: str | None,
    base_seq: int | None,
) -> None:
    if source:
        setattr(block, "source", source)
    start_event_seq = cast(int | None, block.start_event_seq)
    if start_event_seq is None:
        setattr(block, "start_event_seq", seq)
    end_event_seq = cast(int | None, block.end_event_seq)
    if end_event_seq is None or seq >= end_event_seq:
        setattr(block, "end_event_seq", seq)
    if base_seq is not None:
        setattr(block, "base_seq", base_seq)
    normalized_event_id = normalize_non_empty_text(event_id)
    start_event_id = cast(str | None, block.start_event_id)
    if normalized_event_id and not start_event_id:
        setattr(block, "start_event_id", normalized_event_id)
    if normalized_event_id:
        setattr(block, "end_event_id", normalized_event_id)


class SessionHistoryBlockProjectionService:
    """Applies streaming or snapshot block updates to persisted agent messages."""

    async def append_agent_message_block_update(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_message_id: UUID,
        seq: int,
        block_type: str,
        content: str,
        append: bool,
        is_finished: bool,
        block_id: str | None = None,
        lane_id: str | None = None,
        operation: str | None = None,
        base_seq: int | None = None,
        event_id: str | None = None,
        source: str | None = None,
        agent_message: AgentMessage | None = None,
    ) -> AgentMessageBlock | None:
        if seq <= 0:
            return None
        message = agent_message
        if message is None:
            message = cast(
                AgentMessage | None,
                await db.scalar(
                    select(AgentMessage).where(
                        and_(
                            AgentMessage.id == agent_message_id,
                            AgentMessage.user_id == user_id,
                            AgentMessage.sender == "agent",
                        )
                    )
                ),
            )
        if message is None:
            return None

        message_metadata = dict(getattr(message, "message_metadata", None) or {})
        cursor_state = session_common.read_block_cursor_state(message_metadata)
        if seq <= cursor_state["last_event_seq"]:
            return None

        normalized_type = session_common.normalize_block_type(block_type)
        normalized_source = normalize_non_empty_text(source)
        normalized_lane_id = normalize_non_empty_text(lane_id) or _default_lane_id(
            normalized_type
        )
        normalized_operation = _normalize_block_operation(
            operation,
            append=append,
            source=normalized_source,
        )
        normalized_base_seq = (
            int(base_seq) if isinstance(base_seq, int) and base_seq > 0 else None
        )
        if normalized_base_seq is None and normalized_operation in {
            "replace",
            "finalize",
        }:
            normalized_base_seq = seq

        active_block_seq = cursor_state["active_block_seq"]
        active_block: AgentMessageBlock | None = None
        if active_block_seq > 0:
            active_block = await block_store.find_block_by_message_and_block_seq(
                db,
                user_id=user_id,
                message_id=agent_message_id,
                block_seq=active_block_seq,
            )
        if active_block is None:
            active_block = await block_store.find_last_block_for_message(
                db,
                user_id=user_id,
                message_id=agent_message_id,
            )

        latest_text_block: AgentMessageBlock | None = None
        if normalized_type == "text":
            latest_text_block = await block_store.find_last_block_for_message_and_type(
                db,
                user_id=user_id,
                message_id=agent_message_id,
                block_type="text",
            )
        normalized_block_id = normalize_non_empty_text(block_id)
        if not normalized_block_id:
            if (
                normalized_type == "text"
                and session_common.is_primary_text_snapshot_source(normalized_source)
                and latest_text_block is not None
            ):
                normalized_block_id = str(latest_text_block.block_id)
            elif (
                active_block is not None
                and str(active_block.lane_id or "") == normalized_lane_id
                and not bool(active_block.is_finished)
            ):
                normalized_block_id = str(active_block.block_id)
            else:
                normalized_block_id = f"{agent_message_id}:{normalized_lane_id}:{seq}"

        target_block = await block_store.find_block_by_message_and_block_id(
            db,
            user_id=user_id,
            message_id=agent_message_id,
            block_id=normalized_block_id,
        )

        normalized_content = str(content or "")
        if (
            normalized_operation == "replace"
            and normalized_type == "text"
            and session_common.is_primary_text_snapshot_source(normalized_source)
        ):
            latest_reasoning_block = (
                await block_store.find_last_block_for_message_and_type(
                    db,
                    user_id=user_id,
                    message_id=agent_message_id,
                    block_type="reasoning",
                )
            )
            normalized_content = _trim_overlapping_reasoning_prefix(
                cast(str | None, getattr(latest_reasoning_block, "content", None))
                or "",
                normalized_content,
            )
        if not normalized_content and normalized_operation != "finalize":
            return None

        persisted_block: AgentMessageBlock | None = None
        current_base_seq = (
            int(getattr(target_block, "base_seq", 0) or 0)
            if target_block is not None
            else 0
        )
        if (
            target_block is not None
            and normalized_base_seq is not None
            and current_base_seq > 0
            and normalized_base_seq < current_base_seq
        ):
            return None

        if (
            active_block is not None
            and target_block is not None
            and active_block is not target_block
            and not bool(active_block.is_finished)
        ):
            setattr(active_block, "is_finished", True)

        if normalized_operation == "finalize":
            if target_block is None:
                return None
            setattr(target_block, "is_finished", True)
            setattr(target_block, "block_type", normalized_type)
            setattr(target_block, "lane_id", normalized_lane_id)
            _update_block_event_metadata(
                target_block,
                seq=seq,
                event_id=event_id,
                source=normalized_source,
                base_seq=normalized_base_seq,
            )
            persisted_block = target_block
        elif target_block is not None:
            should_preserve_interrupt_content = (
                _should_preserve_existing_interrupt_content(
                    block_type=normalized_type,
                    operation=normalized_operation,
                    incoming_content=normalized_content,
                )
            )
            if normalized_operation == "append":
                current_content = cast(str | None, target_block.content) or ""
                setattr(
                    target_block, "content", f"{current_content}{normalized_content}"
                )
            elif not should_preserve_interrupt_content:
                setattr(target_block, "content", normalized_content)
            setattr(target_block, "block_type", normalized_type)
            setattr(target_block, "lane_id", normalized_lane_id)
            setattr(target_block, "is_finished", bool(is_finished))
            _update_block_event_metadata(
                target_block,
                seq=seq,
                event_id=event_id,
                source=normalized_source,
                base_seq=normalized_base_seq,
            )
            persisted_block = target_block
        else:
            if active_block is not None and not bool(active_block.is_finished):
                setattr(active_block, "is_finished", True)
            next_block_seq = (
                max(
                    cursor_state["last_block_seq"],
                    int(getattr(active_block, "block_seq", 0) or 0),
                )
                + 1
            )
            normalized_event_id = normalize_non_empty_text(event_id)
            persisted_block = await session_common.create_block_with_conflict_recovery(
                db,
                user_id=user_id,
                message_id=agent_message_id,
                block_seq=next_block_seq,
                block_id=normalized_block_id,
                lane_id=normalized_lane_id,
                block_type=normalized_type,
                content=normalized_content,
                is_finished=bool(is_finished) or normalized_operation == "finalize",
                source=normalized_source,
                start_event_seq=seq,
                end_event_seq=seq,
                base_seq=normalized_base_seq,
                start_event_id=normalized_event_id,
                end_event_id=normalized_event_id,
            )

        if persisted_block is None:
            return None
        cursor_state["last_event_seq"] = seq
        cursor_state["last_block_seq"] = max(
            cursor_state["last_block_seq"],
            int(getattr(persisted_block, "block_seq", 0) or 0),
        )
        next_active_block: AgentMessageBlock | None = None
        if (
            active_block is not None
            and active_block is not persisted_block
            and not bool(active_block.is_finished)
        ):
            next_active_block = active_block
        elif not bool(getattr(persisted_block, "is_finished", False)):
            next_active_block = persisted_block
        if next_active_block is None:
            cursor_state["active_block_seq"] = 0
        else:
            cursor_state["active_block_seq"] = int(
                getattr(next_active_block, "block_seq", 0) or 0
            )
        session_common.write_block_cursor_state(message_metadata, cursor_state)
        setattr(message, "message_metadata", message_metadata)
        await db.flush()
        return persisted_block

    async def append_agent_message_block_updates(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_message_id: UUID,
        updates: list[dict[str, Any]],
        agent_message: AgentMessage | None = None,
    ) -> list[AgentMessageBlock]:
        if not updates:
            return []
        message = agent_message
        if message is None:
            message = cast(
                AgentMessage | None,
                await db.scalar(
                    select(AgentMessage).where(
                        and_(
                            AgentMessage.id == agent_message_id,
                            AgentMessage.user_id == user_id,
                            AgentMessage.sender == "agent",
                        )
                    )
                ),
            )
        if message is None:
            return []

        persisted_blocks: list[AgentMessageBlock] = []
        for update in updates:
            persisted = await self.append_agent_message_block_update(
                db,
                user_id=user_id,
                agent_message_id=agent_message_id,
                seq=update["seq"],
                block_type=update["block_type"],
                content=update["content"],
                append=update.get("append", True),
                is_finished=update.get("is_finished", False),
                block_id=update.get("block_id"),
                lane_id=update.get("lane_id"),
                operation=update.get("op"),
                base_seq=update.get("base_seq"),
                event_id=update.get("event_id"),
                source=update.get("source"),
                agent_message=message,
            )
            if persisted:
                persisted_blocks.append(persisted)
        return persisted_blocks

    async def has_agent_message_blocks(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_message_id: UUID,
    ) -> bool:
        return await block_store.has_blocks_for_message(
            db,
            user_id=user_id,
            message_id=agent_message_id,
        )
