"""Common types and helpers for the unified session domain."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.features.invoke.interrupt_metadata import (
    normalize_elicitation_interrupt_details,
    normalize_permission_interrupt_details,
    normalize_permissions_interrupt_details,
    normalize_question_interrupt_details,
)
from app.features.invoke.tool_call_view import (
    build_tool_call_detail,
    build_tool_call_view,
)
from app.features.sessions import block_store
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


@dataclass(frozen=True)
class PreemptedInvokeReport:
    attempted: bool
    status: Literal["none", "accepted", "completed", "failed"]
    pending_requested: bool = False
    target_task_ids: list[str] = field(default_factory=list)
    failed_error_codes: list[str] = field(default_factory=list)


inflight_invokes_lock = asyncio.Lock()
inflight_invokes: dict[tuple[str, str], dict[str, InflightInvokeEntry]] = {}
INFLIGHT_CANCEL_TERMINAL_ERROR_CODES = {
    "task_not_found",
    "task_not_cancelable",
    "invalid_task_id",
}
PRIMARY_TEXT_SNAPSHOT_SOURCES = frozenset({"final_snapshot", "finalize_snapshot"})


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
    if not normalized:
        return "text"
    if normalized in {
        "text",
        "reasoning",
        "tool_call",
        "interrupt_event",
        "system_error",
    }:
        return normalized
    return normalized


def normalize_interrupt_lifecycle_event(
    event: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    request_id = normalize_non_empty_text(event.get("request_id"))
    interrupt_type = normalize_non_empty_text(event.get("type"))
    phase = normalize_non_empty_text(event.get("phase"))
    if not request_id or interrupt_type not in {
        "permission",
        "question",
        "permissions",
        "elicitation",
    }:
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
    if interrupt_type == "permissions":
        normalized["details"] = normalize_permissions_interrupt_details(details)
        return normalized
    if interrupt_type == "elicitation":
        normalized["details"] = normalize_elicitation_interrupt_details(details)
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
        if interrupt_type == "permissions":
            return "permissions_resolved"
        if interrupt_type == "elicitation":
            if event.get("resolution") == "rejected":
                return "elicitation_rejected"
            return "elicitation_answer_received"
        if event.get("resolution") == "rejected":
            return "question_rejected"
        return "question_answer_received"
    if interrupt_type == "permission":
        return "permission_requested"
    if interrupt_type == "permissions":
        return "permissions_requested"
    if interrupt_type == "elicitation":
        return "elicitation_requested"
    return "question_requested"


def build_interrupt_lifecycle_message_content(event: dict[str, Any]) -> str:
    message_code = build_interrupt_lifecycle_message_code(event)
    if message_code == "permission_resolved":
        return "Authorization request was handled. Agent resumed."
    if message_code == "permissions_resolved":
        return "Permissions request was handled. Agent resumed."
    if message_code == "question_rejected":
        return "Question request was rejected. Interrupt closed."
    if message_code == "question_answer_received":
        return "Question answer received. Agent resumed."
    if message_code == "elicitation_rejected":
        return "Additional input request was declined. Interrupt closed."
    if message_code == "elicitation_answer_received":
        return "Additional input was submitted. Agent resumed."

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
    if message_code == "permissions_requested":
        display_message = normalize_non_empty_text(
            details.get("display_message") or details.get("displayMessage")
        )
        permissions = details.get("permissions")
        if isinstance(permissions, dict) and permissions:
            pretty_permissions = json.dumps(
                permissions,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if display_message:
                return f"{display_message}\nRequested permissions: {pretty_permissions}"
            return f"Agent requested permissions approval: {pretty_permissions}"
        if display_message:
            return display_message
        return "Agent requested permissions approval."
    if message_code == "elicitation_requested":
        display_message = normalize_non_empty_text(
            details.get("display_message") or details.get("displayMessage")
        )
        mode = normalize_non_empty_text(details.get("mode"))
        url = normalize_non_empty_text(details.get("url"))
        server_name = normalize_non_empty_text(
            details.get("server_name") or details.get("serverName")
        )
        lines: list[str] = []
        if display_message:
            lines.append(display_message)
        else:
            lines.append("Agent requested additional structured input.")
        if mode:
            lines.append(f"Mode: {mode}")
        if server_name:
            lines.append(f"Server: {server_name}")
        if url:
            lines.append(f"URL: {url}")
        return "\n".join(lines)

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


def normalize_preempt_event(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    reason = normalize_non_empty_text(event.get("reason")) or "invoke_interrupt"
    status = normalize_non_empty_text(event.get("status"))
    if status not in {"accepted", "completed", "failed"}:
        return None
    source = normalize_non_empty_text(event.get("source")) or "user"
    if source not in {"user", "system"}:
        return None

    def _normalize_optional_message_id(field_name: str) -> str | None:
        value = normalize_non_empty_text(event.get(field_name))
        if value is None:
            return None
        try:
            return str(UUID(value))
        except ValueError:
            return None

    target_task_ids: list[str] = []
    raw_target_task_ids = event.get("target_task_ids")
    if isinstance(raw_target_task_ids, list):
        for item in raw_target_task_ids:
            normalized = normalize_non_empty_text(item)
            if normalized and normalized not in target_task_ids:
                target_task_ids.append(normalized)

    failed_error_codes: list[str] = []
    raw_failed_error_codes = event.get("failed_error_codes")
    if isinstance(raw_failed_error_codes, list):
        for item in raw_failed_error_codes:
            normalized = normalize_non_empty_text(item)
            if normalized and normalized not in failed_error_codes:
                failed_error_codes.append(normalized)

    normalized_event: dict[str, Any] = {
        "reason": reason,
        "status": status,
        "source": source,
        "target_task_ids": target_task_ids,
        "failed_error_codes": failed_error_codes,
    }
    for field_name in (
        "target_message_id",
        "replacement_user_message_id",
        "replacement_agent_message_id",
    ):
        normalized_value = _normalize_optional_message_id(field_name)
        if normalized_value is not None:
            normalized_event[field_name] = normalized_value
    return normalized_event


def build_preempt_message_id(
    *,
    conversation_id: UUID,
    replacement_user_message_id: str | None,
    replacement_agent_message_id: str | None,
    target_message_id: str | None,
    reason: str,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        "preempt-event:"
        f"{conversation_id}:"
        f"{replacement_user_message_id or 'none'}:"
        f"{replacement_agent_message_id or 'none'}:"
        f"{target_message_id or 'none'}:"
        f"{reason}",
    )


def build_preempt_message_content(event: dict[str, Any]) -> str:
    status = str(event.get("status") or "")
    if status == "completed":
        content = (
            "Interrupted the previous response before continuing with your new "
            "message."
        )
    elif status == "accepted":
        content = (
            "Accepted the interrupt request for the previous response and is "
            "continuing with your new message."
        )
    else:
        content = (
            "Failed to interrupt the previous response before continuing with "
            "your new message."
        )

    target_task_ids = event.get("target_task_ids")
    if isinstance(target_task_ids, list) and target_task_ids:
        content = (
            f"{content}\nTasks: {', '.join(str(item) for item in target_task_ids)}"
        )
    failed_error_codes = event.get("failed_error_codes")
    if isinstance(failed_error_codes, list) and failed_error_codes:
        content = (
            f"{content}\nErrors: "
            f"{', '.join(str(item) for item in failed_error_codes)}"
        )
    return content


def build_interrupt_block_view(event: dict[str, Any]) -> dict[str, Any]:
    normalized_event = normalize_interrupt_lifecycle_event(event)
    if normalized_event is None:
        raise ValueError("invalid_interrupt_event")

    item: dict[str, Any] = {
        "requestId": normalized_event["request_id"],
        "type": normalized_event["type"],
        "phase": normalized_event["phase"],
    }
    if normalized_event["phase"] == "resolved":
        item["resolution"] = normalized_event["resolution"]
        return item

    details = normalized_event.get("details")
    normalized_details = details if isinstance(details, dict) else {}
    raw_patterns = normalized_details.get("patterns")
    raw_questions = normalized_details.get("questions")
    details_item: dict[str, Any] = {
        "permission": normalize_non_empty_text(normalized_details.get("permission")),
        "patterns": (
            [pattern for pattern in raw_patterns if isinstance(pattern, str)]
            if isinstance(raw_patterns, list)
            else []
        ),
        "displayMessage": normalize_non_empty_text(
            normalized_details.get("display_message")
            or normalized_details.get("displayMessage")
        ),
        "questions": (
            [item for item in raw_questions if isinstance(item, dict)]
            if isinstance(raw_questions, list)
            else []
        ),
    }
    permissions = (
        dict(cast(dict[str, Any], normalized_details.get("permissions")))
        if isinstance(normalized_details.get("permissions"), dict)
        else None
    )
    if permissions is not None:
        details_item["permissions"] = permissions

    server_name = normalize_non_empty_text(
        normalized_details.get("server_name") or normalized_details.get("serverName")
    )
    if server_name:
        details_item["serverName"] = server_name

    mode = normalize_non_empty_text(normalized_details.get("mode"))
    if mode:
        details_item["mode"] = mode

    requested_schema = (
        normalized_details.get("requested_schema")
        if normalized_details.get("requested_schema") is not None
        else normalized_details.get("requestedSchema")
    )
    if requested_schema is not None:
        details_item["requestedSchema"] = requested_schema

    url = normalize_non_empty_text(normalized_details.get("url"))
    if url:
        details_item["url"] = url

    elicitation_id = normalize_non_empty_text(
        normalized_details.get("elicitation_id")
        or normalized_details.get("elicitationId")
    )
    if elicitation_id:
        details_item["elicitationId"] = elicitation_id

    meta = (
        dict(cast(dict[str, Any], normalized_details.get("meta")))
        if isinstance(normalized_details.get("meta"), dict)
        else None
    )
    if meta is not None:
        details_item["meta"] = meta

    item["details"] = details_item
    return item


def serialize_interrupt_event_block_content(event: dict[str, Any]) -> str:
    normalized_event = normalize_interrupt_lifecycle_event(event)
    if normalized_event is None:
        raise ValueError("invalid_interrupt_event")

    payload = {
        "kind": "interrupt_event",
        "schemaVersion": 1,
        "interrupt": normalized_event,
        "content": build_interrupt_lifecycle_message_content(normalized_event),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def deserialize_interrupt_event_block_content(
    raw_content: str | None,
) -> tuple[str, dict[str, Any] | None]:
    normalized_raw_content = raw_content or ""
    try:
        payload = json.loads(normalized_raw_content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return normalized_raw_content, None

    if not isinstance(payload, dict) or payload.get("kind") != "interrupt_event":
        return normalized_raw_content, None

    normalized_event = normalize_interrupt_lifecycle_event(
        cast(dict[str, Any] | None, payload.get("interrupt"))
    )
    if normalized_event is None:
        return normalized_raw_content, None

    content = normalize_non_empty_text(payload.get("content")) or (
        build_interrupt_lifecycle_message_content(normalized_event)
    )
    return content, build_interrupt_block_view(normalized_event)


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


def is_primary_text_snapshot_source(source: str | None) -> bool:
    return normalize_non_empty_text(source) in PRIMARY_TEXT_SNAPSHOT_SOURCES


def render_block_item(
    block: AgentMessageBlock,
    *,
    message_status: str | None = None,
) -> dict[str, Any]:
    block_content = cast(str | None, block.content)
    raw_content = block_content or ""
    block_type = normalize_block_type(cast(str | None, block.block_type))
    tool_call = None
    interrupt = None
    if block_type == "tool_call":
        tool_call = build_tool_call_view(
            raw_content,
            is_finished=bool(block.is_finished),
            message_status=message_status,
        )
    if block_type == "interrupt_event":
        raw_content, interrupt = deserialize_interrupt_event_block_content(raw_content)
    if block_type in {"reasoning", "tool_call"}:
        raw_content = ""
    block_id = normalize_non_empty_text(getattr(block, "block_id", None)) or (
        f"{block.message_id}:{block_type}:{getattr(block, 'block_seq', 0) or 0}"
    )
    lane_id = normalize_non_empty_text(getattr(block, "lane_id", None)) or (
        "primary_text" if block_type == "text" else block_type
    )
    item = {
        "id": str(block.id),
        "type": block_type,
        "content": raw_content,
        "isFinished": bool(block.is_finished),
        "blockId": block_id,
        "laneId": lane_id,
        "baseSeq": cast(int | None, block.base_seq),
    }
    if tool_call is not None:
        item["toolCall"] = tool_call
    if interrupt is not None:
        item["interrupt"] = interrupt
    return item


def render_blocks(
    blocks: list[AgentMessageBlock],
    *,
    message_status: str | None = None,
) -> list[dict[str, Any]]:
    return [render_block_item(block, message_status=message_status) for block in blocks]


def project_message_blocks(
    blocks: list[AgentMessageBlock],
    *,
    message_status: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    projected_blocks = render_blocks(blocks, message_status=message_status)
    content = "".join(
        str(block.get("content") or "")
        for block in projected_blocks
        if str(block.get("type") or "") == "text"
    )
    return projected_blocks, content


def render_block_detail_item(
    block: AgentMessageBlock,
    *,
    message_status: str | None = None,
) -> dict[str, Any]:
    block_content = cast(str | None, block.content)
    raw_content = block_content or ""
    block_type = normalize_block_type(cast(str | None, block.block_type))
    interrupt = None
    if block_type == "interrupt_event":
        raw_content, interrupt = deserialize_interrupt_event_block_content(raw_content)
    block_id = normalize_non_empty_text(getattr(block, "block_id", None)) or (
        f"{block.message_id}:{block_type}:{getattr(block, 'block_seq', 0) or 0}"
    )
    lane_id = normalize_non_empty_text(getattr(block, "lane_id", None)) or (
        "primary_text" if block_type == "text" else block_type
    )
    item = {
        "id": str(block.id),
        "messageId": str(block.message_id),
        "type": block_type,
        "content": raw_content,
        "isFinished": bool(block.is_finished),
        "blockId": block_id,
        "laneId": lane_id,
        "baseSeq": cast(int | None, block.base_seq),
    }
    if block_type == "tool_call":
        tool_call = build_tool_call_view(
            raw_content,
            is_finished=bool(block.is_finished),
            message_status=message_status,
        )
        if tool_call is not None:
            item["toolCall"] = tool_call
        tool_call_detail = build_tool_call_detail(
            raw_content,
            is_finished=bool(block.is_finished),
            message_status=message_status,
        )
        if tool_call_detail is not None:
            item["toolCallDetail"] = tool_call_detail
    if interrupt is not None:
        item["interrupt"] = interrupt
    return item


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
    block_id: str,
    lane_id: str,
    block_type: str,
    content: str,
    is_finished: bool,
    source: str | None,
    start_event_seq: int | None,
    end_event_seq: int | None,
    base_seq: int | None,
    start_event_id: str | None,
    end_event_id: str | None,
) -> AgentMessageBlock | None:
    """Insert one block with best-effort recovery for concurrent idempotent writes."""
    try:
        async with db.begin_nested():
            return await block_store.create_block(
                db,
                user_id=user_id,
                message_id=message_id,
                block_seq=block_seq,
                block_id=block_id,
                lane_id=lane_id,
                block_type=block_type,
                content=content,
                is_finished=is_finished,
                source=source,
                start_event_seq=start_event_seq,
                end_event_seq=end_event_seq,
                base_seq=base_seq,
                start_event_id=start_event_id,
                end_event_id=end_event_id,
            )
    except IntegrityError as exc:
        if is_idempotency_unique_violation(
            exc, index_name="ix_agent_message_blocks_message_id_block_seq"
        ):
            return await block_store.find_block_by_message_and_block_seq(
                db,
                user_id=user_id,
                message_id=message_id,
                block_seq=block_seq,
            )
        if is_idempotency_unique_violation(
            exc, index_name="ix_agent_message_blocks_message_id_block_id"
        ):
            return await block_store.find_block_by_message_and_block_id(
                db,
                user_id=user_id,
                message_id=message_id,
                block_id=block_id,
            )
        raise
