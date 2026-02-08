from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set

from app.agents.prompt_templates import (
    AGENT_PROMPT_CONFIGS,
    TOOL_GUIDES,
    AgentPromptConfig,
    PromptBuilder,
    ToolGuide,
)
from app.core.config import settings

ROOT_AGENT_NAME = "root_agent"
NOTE_AGENT_NAME = "note_agent"
TASK_AGENT_NAME = "task_agent"
HABIT_AGENT_NAME = "habit_agent"
TIMELOG_AGENT_NAME = "timelog_agent"
PERSON_AGENT_NAME = "person_agent"
TAG_AGENT_NAME = "tag_agent"
VISION_AGENT_NAME = "vision_agent"
FOOD_AGENT_NAME = "food_agent"
USER_PREFERENCE_AGENT_NAME = "user_preference_agent"
ENTITY_INGEST_AGENT_NAME = "entity_ingest_agent"

NOTE_TOOL_NAMES: Set[str] = {
    "create_note",
    "update_note",
    "get_latest_notes",
    "search_notes",
    "list_notes_by_content",
    "delete_note",
}

TASK_TOOL_NAMES: Set[str] = {
    "list_tasks_by_planning_cycle",
    "list_tasks_by_vision_and_status",
    "get_task_detail",
    "create_task",
    "update_task",
    "delete_task",
}

HABIT_TOOL_NAMES: Set[str] = {
    "list_habits",
    "create_habit",
    "update_habit",
    "delete_habit",
    "get_habit_overview",
    "log_habit_action",
}

TIMELOG_TOOL_NAMES: Set[str] = {
    "list_time_logs",
    "create_time_log",
    "update_time_log",
    "delete_time_log",
}

PERSON_TOOL_NAMES: Set[str] = {
    "list_persons",
    "get_person_activities",
    "create_person",
    "update_person",
    "delete_person",
    "get_person_detail",
    "create_anniversary",
    "list_anniversaries",
    "delete_anniversary",
    "update_anniversary",
}

TAG_TOOL_NAMES: Set[str] = {
    "create_tag",
    "list_tags",
    "get_tag_usage",
    "update_tag",
    "delete_tag",
}

VISION_TOOL_NAMES: Set[str] = {
    "list_visions",
    "get_vision_detail",
    "create_vision",
    "update_vision",
    "delete_vision",
}

FOOD_TOOL_NAMES: Set[str] = {
    "list_foods",
    "get_food_detail",
    "list_food_entries",
    "get_food_entry_detail",
    "get_daily_nutrition_summary",
}

USER_PREFERENCE_TOOL_NAMES: Set[str] = {
    "list_user_preferences",
    "get_user_preference",
    "set_user_preference",
}

ENTITY_INGEST_TOOL_NAMES: Set[str] = {
    "list_tags",
    "list_persons",
    "list_visions",
    "list_tasks_by_vision_and_status",
    "list_habits",
    "list_notes_by_content",
    "create_tag",
    "create_person",
    "create_vision",
    "create_task",
    "create_habit",
    "create_note",
}

AGENT_DESCRIPTIONS: Dict[str, str] = {
    ROOT_AGENT_NAME: "Root agent handling general-purpose interactions.",
    NOTE_AGENT_NAME: "Agent specialising in note management workflows.",
    TASK_AGENT_NAME: "Agent specialising in task planning and tracking.",
    HABIT_AGENT_NAME: "Agent specialising in habit tracking workflows.",
    TIMELOG_AGENT_NAME: "Agent specialising in time log review and capture.",
    PERSON_AGENT_NAME: "Agent specialising in personal relationship management.",
    TAG_AGENT_NAME: "Agent specialising in tag creation and analytics.",
    VISION_AGENT_NAME: "Agent specialising in vision planning and review.",
    FOOD_AGENT_NAME: "Agent specialising in nutrition logging and lookup.",
    USER_PREFERENCE_AGENT_NAME: "Agent specialising in user preference configuration.",
    ENTITY_INGEST_AGENT_NAME: "Agent that converts free-form text into new entities using tools only.",
}

AGENT_TOOL_MAP: Dict[str, Set[str]] = {
    NOTE_AGENT_NAME: NOTE_TOOL_NAMES,
    TASK_AGENT_NAME: TASK_TOOL_NAMES,
    HABIT_AGENT_NAME: HABIT_TOOL_NAMES,
    TIMELOG_AGENT_NAME: TIMELOG_TOOL_NAMES,
    PERSON_AGENT_NAME: PERSON_TOOL_NAMES,
    TAG_AGENT_NAME: TAG_TOOL_NAMES,
    VISION_AGENT_NAME: VISION_TOOL_NAMES,
    FOOD_AGENT_NAME: FOOD_TOOL_NAMES,
    USER_PREFERENCE_AGENT_NAME: USER_PREFERENCE_TOOL_NAMES,
    ENTITY_INGEST_AGENT_NAME: ENTITY_INGEST_TOOL_NAMES,
}


@dataclass(frozen=True)
class AgentProfile:
    name: str
    description: str
    explicit_tools: Set[str] = field(default_factory=set)
    allow_unassigned_tools: bool = False
    fallback_tools: Set[str] = field(default_factory=set)
    system_prompt_en: Optional[str] = None
    prompt_version: str = "unknown"
    tool_guides: Dict[str, ToolGuide] = field(default_factory=dict)
    tool_sequence: List[str] = field(default_factory=list)


class AgentRegistry:
    _instance: "AgentRegistry" | None = None

    def __new__(cls) -> "AgentRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_profiles()
        return cls._instance

    def _init_profiles(self) -> None:
        tool_guides: Dict[str, ToolGuide] = dict(TOOL_GUIDES)
        agent_configs: Dict[str, AgentPromptConfig] = dict(AGENT_PROMPT_CONFIGS)
        if not settings.a2a_enabled:
            tool_guides.pop("a2a_agent", None)
            root_config = agent_configs.get(ROOT_AGENT_NAME)
            if root_config and "a2a_agent" in root_config.tool_names:
                filtered_names = tuple(
                    name for name in root_config.tool_names if name != "a2a_agent"
                )
                agent_configs[ROOT_AGENT_NAME] = AgentPromptConfig(
                    role=root_config.role,
                    tool_names=filtered_names,
                    response_guidance=root_config.response_guidance,
                    fallback_guidance=root_config.fallback_guidance,
                    extra_notes=root_config.extra_notes,
                )

        prompt_builder = PromptBuilder(
            tool_guides=tool_guides,
            agent_configs=agent_configs,
        )
        self._profiles: Dict[str, AgentProfile] = {}

        all_agent_names = [ROOT_AGENT_NAME, *AGENT_TOOL_MAP.keys()]
        for agent_name in all_agent_names:
            tools = AGENT_TOOL_MAP.get(agent_name, set())
            description = AGENT_DESCRIPTIONS.get(
                agent_name, f"Agent specialising in {agent_name}."
            )
            allow_unassigned = agent_name == ROOT_AGENT_NAME

            config = AGENT_PROMPT_CONFIGS.get(agent_name)
            if config:
                tool_sequence = [
                    name
                    for name in config.tool_names
                    if settings.a2a_enabled or name != "a2a_agent"
                ]
            else:
                tool_sequence = sorted(tools)
            guides = {
                name: TOOL_GUIDES[name] for name in tool_sequence if name in TOOL_GUIDES
            }

            prompt_result = prompt_builder.build(agent_name) if config else None
            system_prompt = prompt_result.text if prompt_result else None
            prompt_version = prompt_result.version if prompt_result else "unknown"

            self._profiles[agent_name] = AgentProfile(
                name=agent_name,
                description=description,
                explicit_tools=set(tools),
                allow_unassigned_tools=allow_unassigned,
                system_prompt_en=system_prompt,
                prompt_version=prompt_version,
                tool_guides=guides,
                tool_sequence=tool_sequence,
            )

        self._tool_owners: Dict[str, str] = {}
        for agent_name, tools in AGENT_TOOL_MAP.items():
            for tool_name in tools:
                self._tool_owners[tool_name] = agent_name

    def list_agent_names(self) -> List[str]:
        return sorted(self._profiles.keys())

    def list_profiles(self) -> List[AgentProfile]:
        return [self._profiles[name] for name in self.list_agent_names()]

    def get_profile(self, agent_name: str) -> AgentProfile:
        return self._profiles.get(agent_name, self._profiles[ROOT_AGENT_NAME])

    def resolve_allowed_tools(
        self, agent_name: str, available_tools: Iterable[str]
    ) -> Set[str]:
        profile = self.get_profile(agent_name)
        allowed: Set[str] = set(profile.explicit_tools)

        for tool_name in available_tools:
            owner = self._tool_owners.get(tool_name)
            if owner is None:
                if profile.allow_unassigned_tools:
                    allowed.add(tool_name)
                continue
            if owner == profile.name or tool_name in profile.fallback_tools:
                allowed.add(tool_name)

        return allowed


agent_registry = AgentRegistry()

__all__ = [
    "AgentRegistry",
    "AgentProfile",
    "agent_registry",
    "ROOT_AGENT_NAME",
    "NOTE_AGENT_NAME",
    "TASK_AGENT_NAME",
    "HABIT_AGENT_NAME",
    "TIMELOG_AGENT_NAME",
    "PERSON_AGENT_NAME",
    "TAG_AGENT_NAME",
    "VISION_AGENT_NAME",
    "FOOD_AGENT_NAME",
    "USER_PREFERENCE_AGENT_NAME",
    "NOTE_TOOL_NAMES",
    "TASK_TOOL_NAMES",
    "HABIT_TOOL_NAMES",
    "TIMELOG_TOOL_NAMES",
    "PERSON_TOOL_NAMES",
    "TAG_TOOL_NAMES",
    "VISION_TOOL_NAMES",
    "FOOD_TOOL_NAMES",
    "USER_PREFERENCE_TOOL_NAMES",
]
