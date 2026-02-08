"""Prompt/language helpers for AgentService."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent_registry import ROOT_AGENT_NAME, AgentProfile, agent_registry
from app.core.config import settings
from app.handlers import user_preferences as user_preferences_service
from app.integrations.a2a_client import get_a2a_service
from app.utils.language_utils import describe_language


@dataclass(frozen=True)
class PromptBundle:
    """Represents the rendered prompt plus its metadata."""

    prompt: str
    version: str
    language_directive: Optional[str] = None

    def render(self) -> str:
        if self.language_directive:
            return f"{self.language_directive}\n\n{self.prompt}"
        return self.prompt


class PromptingService:
    """Resolves user language preferences and builds system prompts."""

    def __init__(self) -> None:
        self._default_prompt = (
            "You are a personal productivity assistant specialized in time management, scheduling, "
            "goal breakdown, and personal planning. Respond in a friendly, professional, concise, and "
            "action-oriented style, offering step-by-step guidance and checklists when helpful. If "
            "clarification is needed, ask up to three brief clarifying questions first."
        )

    async def get_user_language(self, db: AsyncSession, user_id: UUID) -> str:
        return await user_preferences_service.resolve_language_preference(
            db, user_id=user_id, default="en"
        )

    def build_system_prompt(
        self, language: str, profile: Optional[AgentProfile]
    ) -> PromptBundle:
        base_profile = profile or agent_registry.get_profile(ROOT_AGENT_NAME)
        prompt_text = base_profile.system_prompt_en or self._default_prompt
        prompt_version = base_profile.prompt_version

        if settings.a2a_enabled:
            try:
                a2a_service = get_a2a_service()
                prompt_section = a2a_service.build_prompt_section(language=language)
            except Exception:  # pragma: no cover - defensive logging
                prompt_section = ""
            if prompt_section:
                prompt_text = f"{prompt_text}\n\n{prompt_section}"

        language_directive = self._build_language_directive(language)
        return PromptBundle(
            prompt=prompt_text,
            version=prompt_version or "unknown",
            language_directive=language_directive,
        )

    @staticmethod
    def _build_language_directive(language: str) -> str:
        normalized = (language or "en").strip().lower()
        readable = (
            describe_language(normalized)
            if normalized not in {"", "en", "english"}
            else "English"
        )
        return (
            "Language directive: respond to the user in "
            f"{readable}. Mirror the user's language if they change mid-conversation."
        )

    @staticmethod
    def inject_auxiliary_system_message(
        messages: List[dict], content: Optional[str]
    ) -> List[dict]:
        if not content:
            return messages

        inserted = False
        for index, message in enumerate(messages):
            if message.get("role") == "system":
                messages.insert(index + 1, {"role": "system", "content": content})
                inserted = True
                break

        if not inserted:
            messages.insert(0, {"role": "system", "content": content})

        return messages


__all__ = ["PromptingService", "PromptBundle"]
