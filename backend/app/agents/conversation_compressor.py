"""Implements conversation summarisation and storage helpers."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence
from uuid import UUID

from app.agents.conversation_history import ConversationMessage
from app.agents.llm import llm_client
from app.cardbox.service import cardbox_service
from app.core.config import settings
from app.core.logging import get_logger, log_exception
from app.db.models.agent_session import AgentSession
from app.utils.language_utils import describe_language
from app.utils.timezone_util import utc_now, utc_now_iso

logger = get_logger(__name__)


@dataclass
class SummaryResult:
    """Represents a generated summary message and persistence metadata."""

    message: ConversationMessage
    card_id: Optional[str]


class ConversationCompressor:
    """Generates summaries for trimmed conversation history segments."""

    def __init__(self) -> None:
        self.timeout = settings.litellm_timeout

    def _format_messages(self, messages: Sequence[ConversationMessage]) -> str:
        formatted: List[str] = []
        for msg in messages:
            role = msg.role
            if role == "tool":
                role = msg.metadata.get("tool_name") if msg.metadata else "tool"
            formatted.append(f"[{role.upper()}] {msg.content.strip()}")
        return "\n".join(formatted)

    def _build_summary_prompt(self, language: str) -> str:
        target_language = describe_language(language)
        return (
            "You are a conversation summarizer. Condense the provided dialogue into succinct bullet points, "
            "highlighting key facts, decisions, open questions, and context required for future turns. "
            f"Keep the tone neutral and present the final bullets in {target_language}."
        )

    async def generate_summary(
        self,
        *,
        messages: Sequence[ConversationMessage],
        language: str,
    ) -> Optional[str]:
        if not messages:
            return None

        prompt = self._build_summary_prompt(language)
        conversation_blob = self._format_messages(messages)
        user_instruction = (
            "Conversation snippet:\n"
            f"{conversation_blob}\n\n"
            "Return only the summary without preamble."
        )

        try:
            # Build LiteLLM parameters with authentication
            response = await llm_client.completion(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_instruction},
                ],
                max_tokens=360,
                temperature=0.2,
                timeout=self.timeout,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger,
                f"Failed to generate summary via LiteLLM: {type(exc).__name__}: {exc}",
                sys.exc_info(),
            )
            return None

        try:
            summary = response.choices[0].message.content or ""
        except Exception:  # pragma: no cover - defensive
            summary = getattr(response, "content", "") or ""
        return summary.strip() or None

    async def compress(
        self,
        *,
        session: Optional[AgentSession],
        user_id: UUID,
        language: str,
        candidates: Sequence[ConversationMessage],
    ) -> Optional[SummaryResult]:
        if session is None or not candidates:
            return None

        summary_text = await self.generate_summary(
            messages=candidates, language=language
        )
        if not summary_text:
            return None

        message_ids = [msg.message_id for msg in candidates if msg.message_id]
        metadata = {
            "type": "summary",
            "role": "system",
            "generated_at": utc_now_iso(),
            "covered_messages": message_ids,
        }

        message = ConversationMessage(
            role="system",
            content=summary_text,
            created_at=utc_now(),
            source="summary",
            message_id=None,
            metadata=metadata,
        )

        card_id = cardbox_service.record_summary(
            session=session,
            user_id=user_id,
            summary=summary_text,
            covered_message_ids=message_ids,
            language=language,
        )

        return SummaryResult(message=message, card_id=card_id)


conversation_compressor = ConversationCompressor()

__all__ = [
    "ConversationCompressor",
    "SummaryResult",
    "conversation_compressor",
]
