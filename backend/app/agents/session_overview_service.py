"""Service for generating user-facing session titles and summaries."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.conversation_history import (
    ConversationMessage,
    conversation_history_service,
)
from app.agents.llm import llm_client
from app.cardbox.service import cardbox_service
from app.core.config import settings
from app.core.logging import get_logger, log_exception
from app.db.models.agent_session import AgentSession
from app.handlers import agent_message as agent_message_handler
from app.handlers import agent_session as session_handler
from app.handlers import user_preferences as user_preferences_service
from app.utils.language_utils import describe_language
from app.utils.timezone_util import utc_now

logger = get_logger(__name__)


@dataclass
class OverviewResult:
    """Structured output from the overview generation call."""

    title: str
    description: str
    confidence: Optional[float]
    model_name: Optional[str]


@dataclass
class OverviewUpdateResult:
    """Metadata describing how an overview update was handled."""

    overview: OverviewResult
    applied_to_session: bool


class SessionOverviewService:
    """Generates and persists user-facing session overviews."""

    def __init__(self) -> None:
        self.timeout = settings.litellm_timeout
        self.history_limit = settings.session_overview_history_limit
        self.min_messages = settings.session_overview_min_messages
        self.cooldown_seconds = settings.session_overview_refresh_seconds

        logger.info(
            f"SessionOverviewService initialized: min_messages={self.min_messages}, cooldown_seconds={self.cooldown_seconds}, history_limit={self.history_limit}"
        )

    def _should_update_field(
        self,
        current: Optional[str],
        previous_auto: Optional[str],
    ) -> bool:
        if current is None or current.strip() == "":
            return True
        if previous_auto and current.strip() == previous_auto.strip():
            return True
        return False

    def _format_messages_for_prompt(
        self, history: Sequence[ConversationMessage]
    ) -> str:
        lines: List[str] = []
        for msg in history:
            role = msg.role
            if role == "tool":
                role = msg.metadata.get("tool_name") if msg.metadata else "tool"
                prefix = f"[TOOL:{role}]"
            elif role == "assistant":
                prefix = "[ASSISTANT]"
            elif role == "system":
                prefix = "[SYSTEM]"
            else:
                prefix = "[USER]"
            snippet = msg.content.strip().replace("\n", " ")
            if len(snippet) > 280:
                snippet = snippet[:277] + "..."
            lines.append(f"{prefix} {snippet}")
        return "\n".join(lines)

    def _build_prompts(
        self, language: str, formatted_history: str
    ) -> List[Dict[str, str]]:
        target_language = describe_language(language)
        system_prompt = (
            "You are a conversation insight assistant. Produce a concise session title (max 8 words) "
            "and a short description (up to two sentences) that highlight the user's objectives, ongoing work, "
            "and any open questions. "
            f"Write the title and description in {target_language}. "
            "Always return JSON with fields title, description, and confidence (0-1). "
            "When uncertain, provide your best guess and lower the confidence value."
        )
        user_instruction = (
            "Recent conversation excerpt:\n"
            f"{formatted_history}\n\n"
            'Example output (structure only): {"title": "Weekly planning sync", '
            '"description": "Reviewing goals, upcoming deadlines, and prioritising next actions with the assistant.", '
            '"confidence": 0.65}'
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_instruction},
        ]

    def _parse_response(self, raw: Any) -> Optional[OverviewResult]:
        try:
            content = raw.choices[0].message.content if raw.choices else ""
        except Exception:  # pragma: no cover - defensive
            content = getattr(raw, "content", "")

        logger.debug(f"LLM response content: {repr(content)}")

        if not content:
            logger.warning("LLM returned empty content")
            return None

        try:
            data = json.loads(content)
            logger.debug(f"Successfully parsed JSON: {data}")
        except json.JSONDecodeError as e:
            logger.warning(
                f"JSON decode error: {e}, attempting to extract JSON from content"
            )
            try:
                start = content.find("{")
                end = content.rfind("}")
                if start != -1 and end != -1:
                    json_str = content[start : end + 1]
                    logger.debug(f"Extracted JSON string: {repr(json_str)}")
                    data = json.loads(json_str)
                    logger.debug(f"Successfully parsed extracted JSON: {data}")
                else:
                    logger.error(f"No JSON object found in content: {repr(content)}")
                    return None
            except Exception as e:
                logger.error(
                    f"Failed to extract and parse JSON: {e}, content: {repr(content)}"
                )
                return None

        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        logger.debug(f"Extracted title: '{title}', description: '{description}'")

        if not title or not description:
            logger.warning(
                f"Missing required fields - title: '{title}', description: '{description}'"
            )
            return None

        confidence = data.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else None
        except (ValueError, TypeError):
            logger.warning(f"Invalid confidence value: {confidence}")
            confidence = None

        model_name = getattr(raw, "model", None)
        result = OverviewResult(
            title=title,
            description=description,
            confidence=confidence,
            model_name=model_name,
        )
        logger.debug(f"Created OverviewResult: {result}")
        return result

    async def _enough_history(
        self, db: AsyncSession, user_id: UUID, session_id: UUID
    ) -> bool:
        count = await agent_message_handler.count_agent_messages(
            db, user_id=user_id, session_id=session_id
        )
        result = count >= self.min_messages
        logger.info(
            f"Session {session_id} has {count} messages, threshold: {self.min_messages}, enough_history: {result}"
        )
        return result

    def _within_cooldown(self, previous: Optional[Dict[str, Any]]) -> bool:
        if not previous:
            logger.info("No previous overview found, skipping cooldown check")
            return False
        generated_at = previous.get("generated_at")
        if not generated_at:
            logger.info(
                "Previous overview has no generated_at timestamp, skipping cooldown"
            )
            return False
        try:
            ts = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError:
            logger.info(
                f"Invalid generated_at timestamp: {generated_at}, skipping cooldown"
            )
            return False
        delta = utc_now() - ts
        within_cooldown = delta.total_seconds() < self.cooldown_seconds
        logger.info(
            f"Cooldown check: delta={delta.total_seconds():.1f}s, threshold={self.cooldown_seconds}s, within_cooldown={within_cooldown}"
        )
        return within_cooldown

    async def maybe_update_overview(
        self,
        *,
        db: AsyncSession,
        session: AgentSession,
        user_id: UUID,
    ) -> Optional[OverviewUpdateResult]:
        """Generate and optionally apply a new overview.

        Returns:
            OverviewUpdateResult if a fresh overview was generated, otherwise None.
        """
        if session.id is None:
            logger.warning("Session has no ID, skipping overview update")
            return None

        logger.info(f"Starting overview update for session {session.id}")

        enough_history = await self._enough_history(
            db, user_id=user_id, session_id=session.id
        )
        if not enough_history:
            logger.info(
                f"Skipping overview update for session {session.id}: not enough message history"
            )
            return None

        previous = cardbox_service.get_latest_session_overview(
            user_id=user_id,
            session_id=session.id,
        )
        if self._within_cooldown(previous):
            logger.info(
                f"Skipping overview update for session {session.id}: within cooldown period"
            )
            return None

        language = await user_preferences_service.resolve_language_preference(
            db, user_id=user_id
        )

        logger.info(
            f"Generating overview for session {session.id} in language '{language}'"
        )

        history, _source = await conversation_history_service.get_recent_history(
            db,
            user_id=user_id,
            session_id=session.id,
            limit=self.history_limit,
        )

        if not history:
            logger.info(
                f"Skipping overview update for session {session.id}: no conversation history found"
            )
            return None

        formatted_history = self._format_messages_for_prompt(history)
        prompts = self._build_prompts(language, formatted_history)

        try:
            # Build LiteLLM parameters with authentication
            response = await llm_client.completion(
                messages=prompts,
                max_tokens=2048,
                temperature=0.3,
                timeout=self.timeout,
            )
        except Exception as exc:  # pragma: no cover - defensive
            log_exception(
                logger,
                f"Failed to generate session overview: {type(exc).__name__}: {exc}",
                sys.exc_info(),
            )
            return None

        overview = self._parse_response(response)
        if overview is None:
            logger.error(
                f"Session {session.id} overview LLM returned unparsable payload"
            )
            logger.debug(f"Raw LLM response object: {response}")
            return None

        logger.info(
            f"Generated overview for session {session.id}: title='{overview.title}', description='{overview.description[:100]}...', confidence={overview.confidence}"
        )

        cardbox_service.record_session_overview(
            session=session,
            user_id=user_id,
            title=overview.title,
            description=overview.description,
            confidence=overview.confidence,
            language=language,
            model_name=overview.model_name,
        )

        previous_title = previous.get("title") if previous else None
        previous_summary = previous.get("description") if previous else None

        should_update_name = self._should_update_field(session.name, previous_title)
        should_update_summary = self._should_update_field(
            session.summary, previous_summary
        )

        # 如果任一字段需要更新，则同时更新两个字段
        should_update = should_update_name or should_update_summary

        logger.info(
            f"Session {session.id} overview application: update_name={should_update_name}, update_summary={should_update_summary}, will_update_both={should_update}"
        )

        applied = False
        if should_update:
            await session_handler.apply_session_overview(
                db,
                session=session,
                title=overview.title,
                summary=overview.description,
            )
            applied = True

        logger.info(f"Successfully completed overview update for session {session.id}")

        return OverviewUpdateResult(overview=overview, applied_to_session=applied)


session_overview_service = SessionOverviewService()

__all__ = [
    "session_overview_service",
    "SessionOverviewService",
]
