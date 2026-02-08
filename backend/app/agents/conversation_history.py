"""Unified helpers for retrieving structured conversation history."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.cardbox.service import cardbox_service
from app.core.logging import get_logger, log_exception
from app.handlers import agent_message as agent_message_handler
from app.utils.timezone_util import utc_now

logger = get_logger(__name__)


@dataclass
class ConversationMessage:
    """Normalized conversation record used for context building."""

    role: str
    content: str
    created_at: datetime
    source: str
    message_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return utc_now()


class ConversationHistoryService:
    """Service that merges Cardbox history with database records."""

    def __init__(self) -> None:
        self._cardbox_limit_multiplier = 4

    def _deduplicate(
        self, messages: Iterable[ConversationMessage]
    ) -> List[ConversationMessage]:
        seen: Dict[str, ConversationMessage] = {}
        ordered: List[ConversationMessage] = []
        for message in sorted(
            messages, key=lambda m: (m.created_at, m.message_id or "")
        ):
            key = (
                message.message_id or f"{message.role}:{message.created_at.timestamp()}"
            )
            if key in seen:
                continue
            seen[key] = message
            ordered.append(message)
        return ordered

    def _apply_summary_filter(
        self,
        messages: List[ConversationMessage],
        *,
        enabled: bool = True,
    ) -> List[ConversationMessage]:
        if not enabled:
            return messages
        if not messages:
            return messages

        covered_ids = set()
        for message in messages:
            if message.metadata and message.metadata.get("type") == "summary":
                covered = message.metadata.get("covered_messages") or []
                for mid in covered:
                    if mid:
                        covered_ids.add(str(mid))

        if not covered_ids:
            return messages

        filtered: List[ConversationMessage] = []
        for message in messages:
            if message.message_id and message.message_id in covered_ids:
                continue
            filtered.append(message)
        return filtered

    def _load_from_cardbox(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        limit: Optional[int],
    ) -> List[ConversationMessage]:
        try:
            fetch_limit = (
                None
                if limit is None
                else max(limit * self._cardbox_limit_multiplier, limit)
            )
            raw_messages = cardbox_service.list_session_messages(
                user_id=user_id,
                session_id=session_id,
                limit=fetch_limit,
            )
        except Exception:  # pragma: no cover - defensive logging
            log_exception(
                logger,
                f"Failed to read cardbox history for session {session_id}",
                sys.exc_info(),
            )
            return []

        results: List[ConversationMessage] = []
        for item in raw_messages:
            metadata = item.get("metadata") or {}
            role = metadata.get("role") or item.get("role") or "assistant"
            message_type = metadata.get("type") or item.get("type")

            # Skip internal usage logs such as session context tracking cards
            if isinstance(message_type, str) and message_type == "context_usage":
                continue

            content = item.get("content") or ""
            message_id = metadata.get("message_id") or item.get("card_id")
            tool_call_id = metadata.get("tool_call_id") or metadata.get("tool_call")
            created_at = _parse_datetime(metadata.get("created_at"))
            name = metadata.get("name")
            tool_calls_raw = metadata.get("tool_calls")
            tool_calls: Optional[List[Dict[str, Any]]] = None
            if isinstance(tool_calls_raw, list):
                tool_calls = []
                for entry in tool_calls_raw:
                    if isinstance(entry, dict):
                        tool_calls.append(entry)

            results.append(
                ConversationMessage(
                    role=role,
                    content=content,
                    created_at=created_at,
                    source="cardbox",
                    message_id=str(message_id) if message_id else None,
                    metadata=metadata,
                    tool_call_id=tool_call_id,
                    name=name,
                    tool_calls=tool_calls,
                )
            )

        return results

    async def _load_from_database(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        session_id: Optional[UUID],
        limit: int,
    ) -> List[ConversationMessage]:
        query_limit = limit * 2 if limit else 50
        rows = await agent_message_handler.list_recent_agent_messages(
            db,
            user_id=user_id,
            session_id=session_id,
            limit=query_limit,
        )

        messages: List[ConversationMessage] = []
        for row in rows:
            # Normalize sender to role, ensuring only valid role names
            if row.sender in {"user", "automation"}:
                role = "user"
            elif row.sender == "agent":
                role = "assistant"
            else:
                role = "assistant"

            metadata = {
                "message_id": str(row.id),
                "session_id": str(row.session_id) if row.session_id else None,
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "total_tokens": row.total_tokens,
                "model_name": row.model_name,
            }
            messages.append(
                ConversationMessage(
                    role=role,
                    content=row.content or "",
                    created_at=row.created_at or utc_now(),
                    source="database",
                    message_id=str(row.id),
                    metadata=metadata,
                )
            )

        return list(reversed(messages))

    async def get_recent_history(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        session_id: Optional[UUID],
        limit: int = 20,
        prefer_cardbox: bool = True,
        apply_summary_filter: bool = True,
    ) -> Tuple[List[ConversationMessage], str]:
        if session_id is None:
            db_history = await agent_message_handler.get_conversation_history(
                db,
                user_id=user_id,
                limit=limit,
                session_id=None,
            )
            results = []
            for msg in db_history:
                # Normalize sender to role
                if msg.sender in {"user", "automation"}:
                    role = "user"
                elif msg.sender == "agent":
                    role = "assistant"
                else:
                    role = "assistant"

                results.append(
                    ConversationMessage(
                        role=role,
                        content=msg.content or "",
                        created_at=msg.created_at or utc_now(),
                        source="database",
                        message_id=str(msg.id),
                        metadata={
                            "message_id": str(msg.id),
                            "session_id": (
                                str(msg.session_id) if msg.session_id else None
                            ),
                        },
                    )
                )
            return results, "database"

        if prefer_cardbox:
            cardbox_history = self._load_from_cardbox(
                user_id=user_id, session_id=session_id, limit=limit
            )
            if cardbox_history:
                trimmed = self._deduplicate(cardbox_history)
                trimmed = self._apply_summary_filter(
                    trimmed, enabled=apply_summary_filter
                )
                trimmed = trimmed[-limit:]
                return trimmed, "cardbox"

        db_history = await self._load_from_database(
            db, user_id=user_id, session_id=session_id, limit=limit
        )
        filtered = self._apply_summary_filter(db_history, enabled=apply_summary_filter)
        return filtered[-limit:], "database"


conversation_history_service = ConversationHistoryService()

__all__ = [
    "ConversationHistoryService",
    "ConversationMessage",
    "conversation_history_service",
]
