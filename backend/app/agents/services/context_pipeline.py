"""Conversation context assembly helpers for AgentService."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from card_box_core.structures import Card, TextContent
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context_builder import ContextBuildResult
from app.agents.conversation_history import (
    ConversationMessage,
    conversation_history_service,
)
from app.cardbox.context_service import context_box_manager
from app.cardbox.service import cardbox_service
from app.core.logging import get_logger, log_exception
from app.services.session_context_service import session_context_service
from app.utils.json_encoder import json_dumps
from app.utils.timezone_util import utc_now, utc_now_iso

logger = get_logger(__name__)

MAX_CONTEXT_CARDS_PER_BOX = 20


class ContextPipeline:
    """Loads historical context and records usage metadata."""

    def __init__(
        self,
        *,
        context_source=session_context_service,
        box_manager=context_box_manager,
        history_service=conversation_history_service,
    ) -> None:
        self._context_source = context_source
        self._box_manager = box_manager
        self._history_service = history_service

    async def get_conversation_history(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        session_id: Optional[UUID],
        limit: int,
    ) -> Tuple[List[ConversationMessage], str]:
        try:
            history, source = await self._history_service.get_recent_history(
                db,
                user_id=user_id,
                session_id=session_id,
                limit=limit,
            )
            return history, source
        except Exception as exc:
            log_exception(
                logger,
                f"Error retrieving normalized conversation history: {exc}",
                None,
            )
            return [], "error"

    async def load_session_context_messages(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        session_id: Optional[UUID],
    ) -> Tuple[List[ConversationMessage], List[Dict[str, Any]]]:
        if session_id is None:
            return [], []
        selection = await self._context_source.load_selection(
            db, user_id=user_id, session_id=session_id
        )
        if not selection:
            return [], []

        ordered_records: List[Tuple[int, Any]] = []
        for entry in selection:
            box_id = entry.get("box_id")
            if not isinstance(box_id, int):
                continue
            record = self._box_manager.get_record_by_id(user_id=user_id, box_id=box_id)
            if record is None:
                continue
            ordered_records.append((int(entry.get("order", 0)), record))

        if not ordered_records:
            return [], []

        ordered_records.sort(key=lambda item: item[0])
        messages: List[ConversationMessage] = []
        summaries: List[Dict[str, Any]] = []

        for order, record in ordered_records:
            summaries.append(
                {
                    "box_id": record.box_id,
                    "name": record.name,
                    "module": record.module,
                    "order": order,
                }
            )
            skip_manifest = record.module != "unknown"
            cards = self._box_manager.load_box_cards(
                user_id=user_id,
                box_name=record.name,
                skip_manifest=skip_manifest,
                limit=MAX_CONTEXT_CARDS_PER_BOX,
            )
            for card in cards:
                message = self._card_to_message(card, source="context_box")
                if message:
                    messages.append(message)

        return messages, summaries

    def append_context_usage_log(
        self,
        *,
        session,
        tenant_id: str,
        user_id: UUID,
        summaries: List[Dict[str, Any]],
    ) -> None:
        if session is None or not summaries:
            return
        try:
            box_name = cardbox_service.ensure_session_box(session)
            payload = {
                "boxes": summaries,
                "logged_at": utc_now_iso(),
            }
            card = Card(
                content=TextContent(
                    text=json_dumps(payload, ensure_ascii=False, indent=2)
                ),
                metadata={
                    "role": "system",
                    "type": "context_usage",
                    "module": "session_context",
                    "indexable": False,
                    "boxes": summaries,
                    "logged_at": payload["logged_at"],
                },
            )
            cardbox_service.add_cards(tenant_id, box_name, [card])
        except Exception:  # pragma: no cover - defensive logging
            logger.warning(
                "Failed to append session context usage log",
                exc_info=True,
            )

    def log_context_truncation(
        self,
        *,
        user_id: UUID,
        session_id: Optional[UUID],
        context_result: ContextBuildResult,
    ) -> None:
        if not context_result.dropped_history:
            return

        dropped_context_cards = [
            message
            for message in context_result.dropped_history
            if getattr(message, "source", None) == "context_box"
        ]
        if not dropped_context_cards:
            return

        card_ids: List[str] = []
        for message in dropped_context_cards:
            metadata = message.metadata or {}
            card_id = metadata.get("card_id") or message.message_id or ""
            if card_id:
                card_ids.append(str(card_id))

        token_usage = context_result.token_usage or {}
        logger.warning(
            "Session %s (user=%s) context trimming dropped %d CardBox messages."
            " context_tokens=%s card_ids=%s",
            session_id,
            user_id,
            len(dropped_context_cards),
            token_usage.get("history_tokens"),
            card_ids[:20],
        )

    @staticmethod
    def _card_to_message(card: Card, *, source: str) -> Optional[ConversationMessage]:
        metadata = getattr(card, "metadata", {}) or {}
        role = metadata.get("role") or "system"
        text = ""
        try:
            text = card.text()
        except Exception:
            raw_content = getattr(card, "content", None)
            if isinstance(raw_content, str):
                text = raw_content
            elif getattr(raw_content, "text", None):
                text = raw_content.text
        if not text or not text.strip():
            return None

        created_at = ContextPipeline._parse_iso_datetime(metadata.get("created_at"))
        return ConversationMessage(
            role=role,
            content=text,
            created_at=created_at,
            source=source,
            message_id=str(getattr(card, "card_id", "")),
            metadata=metadata,
        )

    @staticmethod
    def _parse_iso_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return utc_now()
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        return utc_now()


__all__ = ["ContextPipeline", "MAX_CONTEXT_CARDS_PER_BOX"]
