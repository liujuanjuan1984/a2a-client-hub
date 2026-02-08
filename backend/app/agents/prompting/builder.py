"""Core prompt-building dataclasses and helpers."""

from __future__ import annotations

import inspect
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from app.agents import tools as tools_module
from app.agents.tools.base import AbstractTool, ToolMetadata
from app.utils.json_encoder import json_dumps

PROMPT_TEMPLATE_VERSION = "2025.11.18"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolArgumentGuide:
    """Describes one argument a tool expects."""

    name: str
    type_hint: str
    required: bool
    description: str
    default: Optional[str] = None


@dataclass(frozen=True)
class IntentTrigger:
    """Maps a user intent pattern to the tool that should handle it."""

    text: str


@dataclass(frozen=True)
class ToolGuide:
    """Structured description for an agent tool."""

    name: str
    purpose: str
    arguments: Sequence[ToolArgumentGuide]
    example_arguments: Mapping[str, Any]
    triggers: Sequence[IntentTrigger] = field(default_factory=tuple)

    def example_json(self) -> str:
        payload = {"tool_name": self.name, "arguments": self.example_arguments}
        return json_dumps(payload, ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class AgentPromptConfig:
    """Prompt configuration bundle for one agent."""

    role: str
    tool_names: Sequence[str]
    response_guidance: str
    fallback_guidance: str
    extra_notes: Optional[str] = None
    tool_usage_guidance: Optional[Sequence[str]] = None


@dataclass(frozen=True)
class PromptBuildResult:
    """Prompt text paired with the template version."""

    text: str
    version: str = PROMPT_TEMPLATE_VERSION


class PromptBuilder:
    """Assembles multi-section prompts from structured configurations."""

    def __init__(
        self,
        *,
        tool_guides: Mapping[str, ToolGuide],
        agent_configs: Mapping[str, AgentPromptConfig],
    ) -> None:
        self._tool_guides = tool_guides
        self._agent_configs = agent_configs
        self._tool_metadata = self._build_tool_metadata_index()

    def build(
        self,
        agent_name: str,
        *,
        response_language: Optional[str] = None,
    ) -> PromptBuildResult:
        lines: list[str] = []
        config = self._agent_configs.get(agent_name)
        if config is None:
            raise KeyError(f"Prompt config for agent '{agent_name}' not found")
        language_instruction = self._format_language_instruction(response_language)
        if language_instruction:
            lines.append(language_instruction)
            lines.append("")
        lines.extend(self._compose_role_section(config))
        lines.extend(self._compose_tool_usage_section(config))
        for guide in self._resolve_tool_guides(config):
            lines.extend(self._compose_tool_detail_section(guide))
        lines.extend(self._compose_response_section(config))
        lines.extend(self._compose_fallback_section(config))
        text = "\n".join(lines).strip()
        return PromptBuildResult(text=text)

    def _compose_role_section(self, config: AgentPromptConfig) -> list[str]:
        lines = ["Role & Responsibilities", config.role]
        if config.extra_notes:
            lines.extend(["", config.extra_notes])
        return [""] + lines if lines else []

    def _compose_tool_usage_section(self, config: AgentPromptConfig) -> list[str]:
        lines = ["", "Tool Usage Guidelines"]
        guidance = config.tool_usage_guidance or (
            "- Prefer satisfying requests via tools; fall back to text reasoning only when no tool applies.",
            "- Before calling, optionally confirm the extracted arguments in plain language.",
            "- After the tool responds, translate raw data into user-facing insights and next steps.",
        )
        lines.extend(guidance)
        return lines

    def _compose_tool_detail_section(self, guide: ToolGuide) -> list[str]:
        lines = ["", f"Tool: {guide.name}", f"Purpose: {guide.purpose}"]
        metadata_lines = self._render_tool_metadata(guide.name)
        if metadata_lines:
            lines.extend(metadata_lines)
        if guide.triggers:
            lines.append("Trigger Intents:")
            for trigger in guide.triggers:
                lines.append(f"  - {trigger.text}")
        if guide.arguments:
            lines.append("Parameters:")
            for arg in guide.arguments:
                requirement = "Required" if arg.required else "Optional"
                lines.append(
                    f"  - {arg.name} ({arg.type_hint}, {requirement}): {arg.description}"
                )
                if arg.default is not None:
                    lines.append(f"    Default: {arg.default}")
        lines.append("Example Call:")
        example_block = guide.example_json()
        lines.append("```json")
        lines.append(example_block)
        lines.append("```")
        return lines

    def _compose_response_section(self, config: AgentPromptConfig) -> list[str]:
        return [
            "",
            "Response Format & Language",
            *self._split_lines(config.response_guidance),
        ]

    def _compose_fallback_section(self, config: AgentPromptConfig) -> list[str]:
        return [
            "",
            "Error Handling & Fallbacks",
            *self._split_lines(config.fallback_guidance),
        ]

    def _resolve_tool_guides(self, config: AgentPromptConfig) -> Sequence[ToolGuide]:
        return [self._tool_guides[name] for name in config.tool_names]

    @staticmethod
    def _split_lines(text) -> list[str]:
        if not isinstance(text, str):
            text = str(text)
        return [line for line in text.splitlines() if line.strip()]

    @staticmethod
    def _format_language_instruction(response_language: Optional[str]) -> Optional[str]:
        if not response_language:
            return None
        language = response_language.strip()
        if not language:
            return None
        if language.lower() in {"en", "english"}:
            return "Language directive: respond in English unless the user explicitly switches languages."
        return (
            "Language directive: respond to the user in "
            f"{language}. Mirror the user's language if they change mid-conversation."
        )

    def _build_tool_metadata_index(self) -> Mapping[str, ToolMetadata]:
        metadata: dict[str, ToolMetadata] = {}
        try:
            for name, tool_cls in self._discover_tool_classes().items():
                try:
                    metadata[name] = tool_cls.get_metadata()
                except Exception:  # pragma: no cover - defensive
                    logger.debug("Failed to fetch metadata for %s", name, exc_info=True)
        except Exception:  # pragma: no cover - defensive
            logger.warning("Failed to build tool metadata index", exc_info=True)
        return metadata

    def _discover_tool_classes(self) -> Mapping[str, type[AbstractTool]]:
        discovered: dict[str, type[AbstractTool]] = {}
        modules = [tools_module.__name__]
        modules.extend(
            module_name
            for _, module_name, _ in pkgutil.walk_packages(
                tools_module.__path__, tools_module.__name__ + "."
            )
        )
        for module_path in modules:
            try:
                module = __import__(module_path, fromlist=["*"])
            except Exception:  # pragma: no cover - defensive logging
                logger.debug(
                    "Failed to import tool module %s", module_path, exc_info=True
                )
                continue
            for _, attr in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(attr, AbstractTool)
                    and attr is not AbstractTool
                    and getattr(attr, "name", None)
                ):
                    discovered[attr.name] = attr
        return discovered

    def _render_tool_metadata(self, tool_name: str) -> list[str]:
        metadata = self._tool_metadata.get(tool_name)
        if not metadata:
            return []
        lines = ["Operational Constraints:"]
        lines.append(f"  - Read-only: {metadata.read_only}")
        lines.append(f"  - Requires confirmation: {metadata.requires_confirmation}")
        lines.append(f"  - Default timeout: {metadata.default_timeout}s")
        lines.append(f"  - Max retries: {metadata.max_retries}")
        lines.append(f"  - Idempotent: {metadata.idempotent}")
        if metadata.labels:
            labels = ", ".join(metadata.labels)
            lines.append(f"  - Labels: {labels}")
        return lines


__all__ = [
    "ToolArgumentGuide",
    "IntentTrigger",
    "ToolGuide",
    "AgentPromptConfig",
    "PromptBuildResult",
    "PROMPT_TEMPLATE_VERSION",
    "PromptBuilder",
]
