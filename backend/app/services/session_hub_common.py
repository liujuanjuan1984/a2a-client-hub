"""Common types and helpers for the unified session domain."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.handlers import agent_message_block as agent_message_block_handler
from app.services.interrupt_metadata_normalization import (
    normalize_permission_interrupt_details,
    normalize_question_interrupt_details,
)
from app.utils.session_identity import normalize_non_empty_text
from app.utils.timezone_util import ensure_utc

SessionSource = Literal["manual", "scheduled"]
ResolvedSource = Literal["manual", "scheduled"]


@dataclass(frozen=True)
class ResolvedConversationTarget:
    source: ResolvedSource
    thread: ConversationThread


@dataclass(frozen=True)
class MessagesBeforeCursor:
    created_at: datetime
    sender_priority: int
    message_id: UUID


@dataclass
class InflightInvokeEntry:
    token: str
    task_id: str | None = None
    gateway: Any | None = None
    resolved: Any | None = None
    cancel_requested: bool = False
    cancel_reason: str | None = None


inflight_invokes_lock = asyncio.Lock()
inflight_invokes: dict[tuple[str, str], dict[str, InflightInvokeEntry]] = {}
INFLIGHT_CANCEL_TERMINAL_ERROR_CODES = {
    "task_not_found",
    "task_not_cancelable",
    "invalid_task_id",
}


def parse_conversation_id(value: str) -> UUID:
    trimmed = (value or "").strip()
    if not trimmed:
        raise ValueError("conversation_id is required")
    try:
        return UUID(trimmed)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_conversation_id") from exc


def encode_messages_before_cursor(
    *,
    created_at: datetime,
    sender_priority: int,
    message_id: UUID,
) -> str:
    payload = {
        "created_at": ensure_utc(created_at).isoformat(),
        "sender_priority": 0 if sender_priority <= 0 else 1,
        "message_id": str(message_id),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("utf-8")
    return encoded.rstrip("=")


def parse_messages_before_cursor(raw: str) -> MessagesBeforeCursor:
    trimmed = (raw or "").strip()
    if not trimmed:
        raise ValueError("invalid_before_cursor")
    padding = "=" * (-len(trimmed) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{trimmed}{padding}".encode("utf-8"))
        payload = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_before_cursor") from exc

    if not isinstance(payload, dict):
        raise ValueError("invalid_before_cursor")
    created_at_raw = payload.get("created_at")
    sender_priority_raw = payload.get("sender_priority")
    message_id_raw = payload.get("message_id")
    if not isinstance(created_at_raw, str) or not isinstance(message_id_raw, str):
        raise ValueError("invalid_before_cursor")
    try:
        created_at = ensure_utc(
            datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        )
        message_id = UUID(message_id_raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_before_cursor") from exc

    try:
        sender_priority = int(cast(int | str, sender_priority_raw))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_before_cursor") from exc
    if sender_priority not in {0, 1}:
        raise ValueError("invalid_before_cursor")
    return MessagesBeforeCursor(
        created_at=created_at,
        sender_priority=sender_priority,
        message_id=message_id,
    )


def build_continue_response(
    *,
    conversation_id: UUID,
    source: ResolvedSource,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "conversationId": str(conversation_id),
        "source": source,
        "metadata": metadata,
    }


def resolve_session_source(
    *,
    thread_source: str | None,
    fallback_source: ResolvedSource | None,
) -> ResolvedSource:
    if thread_source == ConversationThread.SOURCE_SCHEDULED:
        return "scheduled"
    if thread_source == ConversationThread.SOURCE_MANUAL:
        return "manual"
    if fallback_source in {"manual", "scheduled"}:
        return fallback_source
    return "manual"


def sender_to_role(sender: str) -> str:
    normalized = (sender or "").strip().lower()
    if normalized in {"user", "automation"}:
        return "user"
    if normalized == "agent":
        return "agent"
    return "system"


def sender_priority_for_role(role: str) -> int:
    return 0 if role == "user" else 1


def derive_session_title_from_query(query: str) -> str | None:
    trimmed_query = query.strip() if isinstance(query, str) else ""
    if not trimmed_query:
        return None
    return trimmed_query[: ConversationThread.TITLE_MAX_LENGTH]


def normalize_block_type(raw_type: str | None) -> str:
    normalized = (raw_type or "").strip().lower()
    if normalized in {
        "text",
        "reasoning",
        "tool_call",
        "interrupt_event",
        "system_error",
    }:
        return normalized
    return "text"


def normalize_interrupt_lifecycle_event(
    event: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    request_id = normalize_non_empty_text(event.get("request_id"))
    interrupt_type = normalize_non_empty_text(event.get("type"))
    phase = normalize_non_empty_text(event.get("phase"))
    if not request_id or interrupt_type not in {"permission", "question"}:
        return None
    if phase not in {"asked", "resolved"}:
        return None

    normalized: dict[str, Any] = {
        "request_id": request_id,
        "type": interrupt_type,
        "phase": phase,
    }
    if phase == "resolved":
        resolution = normalize_non_empty_text(event.get("resolution"))
        if resolution not in {"replied", "rejected"}:
            return None
        normalized["resolution"] = resolution
        return normalized

    details = event.get("details")
    if not isinstance(details, dict):
        details = {}
    if interrupt_type == "permission":
        normalized["details"] = normalize_permission_interrupt_details(details)
        return normalized

    normalized["details"] = normalize_question_interrupt_details(details)
    return normalized


def build_interrupt_lifecycle_message_id(
    *,
    conversation_id: UUID,
    request_id: str,
    phase: str,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"interrupt-lifecycle:{conversation_id}:{request_id}:{phase}",
    )


def build_interrupt_lifecycle_message_code(event: dict[str, Any]) -> str:
    interrupt_type = str(event.get("type") or "")
    phase = str(event.get("phase") or "")
    if phase == "resolved":
        if interrupt_type == "permission":
            return "permission_resolved"
        if event.get("resolution") == "rejected":
            return "question_rejected"
        return "question_answer_received"
    if interrupt_type == "permission":
        return "permission_requested"
    return "question_requested"


def build_interrupt_lifecycle_message_content(event: dict[str, Any]) -> str:
    message_code = build_interrupt_lifecycle_message_code(event)
    if message_code == "permission_resolved":
        return "Authorization request was handled. Agent resumed."
    if message_code == "question_rejected":
        return "Question request was rejected. Interrupt closed."
    if message_code == "question_answer_received":
        return "Question answer received. Agent resumed."

    details = event.get("details")
    if not isinstance(details, dict):
        details = {}
    if message_code == "permission_requested":
        display_message = normalize_non_empty_text(
            details.get("display_message") or details.get("displayMessage")
        )
        permission = normalize_non_empty_text(details.get("permission")) or "unknown"
        patterns = details.get("patterns")
        normalized_patterns = (
            [item for item in patterns if isinstance(item, str)]
            if isinstance(patterns, list)
            else []
        )
        base_message = (
            display_message or f"Agent requested authorization: {permission}."
        )
        if normalized_patterns:
            return f"{base_message}\nTargets: {', '.join(normalized_patterns)}"
        return base_message

    questions = details.get("questions")
    normalized_questions = (
        [item for item in questions if isinstance(item, dict)]
        if isinstance(questions, list)
        else []
    )
    display_message = normalize_non_empty_text(
        details.get("display_message") or details.get("displayMessage")
    )
    question_entries: list[tuple[str, str | None]] = []
    for item in normalized_questions:
        question = normalize_non_empty_text(item.get("question"))
        if not question:
            continue
        question_entries.append(
            (question, normalize_non_empty_text(item.get("description")))
        )
    if len(question_entries) == 1:
        question, description = question_entries[0]
        if display_message:
            lines = [display_message, f"Question: {question}"]
            if description:
                lines.append(f"Details: {description}")
            return "\n".join(lines)
        if description:
            return (
                f"Agent requested additional input: {question}\n"
                f"Details: {description}"
            )
        return f"Agent requested additional input: {question}"
    if len(question_entries) > 1:
        lines = [
            f"- {question}{f' ({description})' if description else ''}"
            for question, description in question_entries
        ]
        if display_message:
            return f"{display_message}\n" + "\n".join(lines)
        return "Agent requested additional input:\n" + "\n".join(lines)
    if display_message:
        return display_message
    return "Agent requested additional input."


def read_block_cursor_state(metadata: dict[str, Any]) -> dict[str, int]:
    raw_cursor = metadata.get("_block_cursor")
    cursor = raw_cursor if isinstance(raw_cursor, dict) else {}

    def _int_or_zero(value: Any) -> int:
        if isinstance(value, int):
            return max(value, 0)
        if isinstance(value, str) and value.strip().isdigit():
            return max(int(value.strip()), 0)
        return 0

    return {
        "last_event_seq": _int_or_zero(cursor.get("last_event_seq")),
        "last_block_seq": _int_or_zero(cursor.get("last_block_seq")),
        "active_block_seq": _int_or_zero(cursor.get("active_block_seq")),
    }


def write_block_cursor_state(metadata: dict[str, Any], cursor: dict[str, int]) -> None:
    metadata["_block_cursor"] = {
        "last_event_seq": int(max(cursor.get("last_event_seq", 0), 0)),
        "last_block_seq": int(max(cursor.get("last_block_seq", 0), 0)),
        "active_block_seq": int(max(cursor.get("active_block_seq", 0), 0)),
    }


def render_block_item(
    block: AgentMessageBlock,
) -> dict[str, Any]:
    block_content = cast(str | None, block.content)
    raw_content = block_content or ""
    block_type = normalize_block_type(cast(str | None, block.block_type))
    if block_type in {"reasoning", "tool_call"}:
        raw_content = ""
    return {
        "id": str(block.id),
        "type": block_type,
        "content": raw_content,
        "isFinished": bool(block.is_finished),
    }


def render_blocks(blocks: list[AgentMessageBlock]) -> list[dict[str, Any]]:
    return [render_block_item(block) for block in blocks]


def render_block_detail_item(
    block: AgentMessageBlock,
) -> dict[str, Any]:
    block_content = cast(str | None, block.content)
    raw_content = block_content or ""
    return {
        "id": str(block.id),
        "messageId": str(block.message_id),
        "type": normalize_block_type(cast(str | None, block.block_type)),
        "content": raw_content,
        "isFinished": bool(block.is_finished),
    }


def dedupe_uuid_list_keep_order(values: list[UUID]) -> list[UUID]:
    deduped: list[UUID] = []
    seen: set[UUID] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def derive_session_title_from_invoke_metadata(
    metadata: dict[str, Any] | None,
) -> str | None:
    if not isinstance(metadata, dict):
        return None
    root_title = normalize_non_empty_text(metadata.get("title"))
    if root_title:
        return root_title[: ConversationThread.TITLE_MAX_LENGTH]
    return None


def build_query_hash(query: str) -> str:
    return hashlib.sha256(str(query or "").encode("utf-8")).hexdigest()


def is_idempotency_unique_violation(exc: BaseException, *, index_name: str) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, IntegrityError):
            if index_name in str(current):
                return True
            original = getattr(current, "orig", None)
            if original is not None and index_name in str(original):
                return True
        current = current.__cause__ or current.__context__
    return False


def is_agent_message_pk_violation(exc: BaseException) -> bool:
    return is_idempotency_unique_violation(exc, index_name="agent_messages_pkey")


async def create_block_with_conflict_recovery(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
    block_seq: int,
    block_type: str,
    content: str,
    is_finished: bool,
    source: str | None,
    start_event_seq: int | None,
    end_event_seq: int | None,
    start_event_id: str | None,
    end_event_id: str | None,
) -> AgentMessageBlock | None:
    """Insert one block with best-effort recovery for concurrent same-seq writes."""
    try:
        async with db.begin_nested():
            return await agent_message_block_handler.create_block(
                db,
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
    except IntegrityError as exc:
        if not is_idempotency_unique_violation(
            exc, index_name="ix_agent_message_blocks_message_id_block_seq"
        ):
            raise
        return await agent_message_block_handler.find_block_by_message_and_block_seq(
            db,
            user_id=user_id,
            message_id=message_id,
            block_seq=block_seq,
        )
