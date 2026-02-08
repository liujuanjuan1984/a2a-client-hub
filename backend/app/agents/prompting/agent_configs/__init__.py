"""Agent prompt configurations and their tool bindings."""

from dataclasses import replace

from app.agents.prompting.builder import AgentPromptConfig
from app.agents.prompting.constants import (
    DEFAULT_FALLBACK_GUIDANCE,
    DEFAULT_RESPONSE_GUIDANCE,
)
from app.agents.prompting.registry import register_agent_config

BASE_AGENT_TEMPLATE = AgentPromptConfig(
    role="",
    tool_names=(),
    response_guidance=DEFAULT_RESPONSE_GUIDANCE,
    fallback_guidance=DEFAULT_FALLBACK_GUIDANCE,
)


def build_config(role: str, tool_names, **overrides) -> AgentPromptConfig:
    """Create an agent config inheriting from the base template."""

    return replace(
        BASE_AGENT_TEMPLATE,
        role=role,
        tool_names=tool_names,
        **overrides,
    )


ROOT_AGENT_RESPONSE_GUIDANCE = (
    DEFAULT_RESPONSE_GUIDANCE
    + "\n- When a user only asks about your capabilities or available A2A agents, describe what you can do without invoking any tool.\n"
    + "- Before executing `a2a_agent`, explain which agent you plan to call, ask the user to confirm, and wait for explicit consent (e.g., a yes/no answer) before proceeding."
)

ROOT_AGENT_TOOL_GUIDANCE = (
    "- Handle straightforward informational requests directly; only consider the `a2a_agent` when external expertise is clearly required.",
    "- When you believe an A2A call is needed, describe the candidate agent, ask for permission, and wait for explicit user confirmation before invoking the tool.",
    "- After any tool completes, summarize the outcome in natural language and relate it back to the user's question before proceeding.",
)

register_agent_config(
    "note_agent",
    build_config(
        role="You are the notes specialist, responsible for capturing meetings, ideas, and personal logs while helping users recall past notes quickly.",
        tool_names=(
            "create_note",
            "update_note",
            "get_latest_notes",
            "search_notes",
            "delete_note",
        ),
    ),
)


register_agent_config(
    "task_agent",
    build_config(
        role="You are the task planning expert, helping users create, review, and update tasks with clear action plans.",
        tool_names=(
            "list_tasks_by_planning_cycle",
            "list_tasks_by_vision_and_status",
            "get_task_detail",
            "create_task",
            "update_task",
            "delete_task",
        ),
    ),
)


register_agent_config(
    "habit_agent",
    build_config(
        role="You are the habit coach, monitoring habit formation, check-ins, and actionable improvements.",
        tool_names=(
            "list_habits",
            "get_habit_overview",
            "create_habit",
            "update_habit",
            "delete_habit",
            "log_habit_action",
        ),
    ),
)


register_agent_config(
    "timelog_agent",
    build_config(
        role="You are the time-log analyst, helping users backfill and review time investments while summarising key insights.",
        tool_names=(
            "list_time_logs",
            "create_time_log",
            "update_time_log",
            "delete_time_log",
        ),
    ),
)


register_agent_config(
    "person_agent",
    build_config(
        role="You are the relationship assistant, maintaining contact profiles and tracking shared interactions.",
        tool_names=(
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
        ),
    ),
)


register_agent_config(
    "tag_agent",
    build_config(
        role="You manage the tagging system, helping users build consistent tags and understand their usage.",
        tool_names=(
            "create_tag",
            "list_tags",
            "get_tag_usage",
            "update_tag",
            "delete_tag",
        ),
    ),
)


register_agent_config(
    "vision_agent",
    build_config(
        role="You are the vision planner, supporting users in defining long-term goals and tracking their execution.",
        tool_names=(
            "list_visions",
            "get_vision_detail",
            "create_vision",
            "update_vision",
            "delete_vision",
        ),
    ),
)


register_agent_config(
    "food_agent",
    build_config(
        role="You are the nutrition assistant, helping users find food information and organise diet logs.",
        tool_names=(
            "list_foods",
            "get_food_detail",
            "list_food_entries",
            "get_food_entry_detail",
            "get_daily_nutrition_summary",
        ),
    ),
)


register_agent_config(
    "user_preference_agent",
    build_config(
        role="You are the preferences configurator, explaining and adjusting settings to match the user's intent.",
        tool_names=(
            "list_user_preferences",
            "get_user_preference",
            "set_user_preference",
        ),
    ),
)


register_agent_config(
    "entity_ingest_agent",
    build_config(
        role=(
            "You ingest free-form user text and break it into structured actions. "
            "Always use tools; before creating, perform exact dedup using list tools. "
            "Dedup rules (AND logic): tag by name+entity_type; person by name or exact nickname; vision by name; task by vision+content; habit by title (active window check via list_habits active_window_only=true); note by exact content. "
            "If a match exists, reuse its ID; otherwise create. Always treat any human reference—including kinship titles like '儿子/女儿/妈妈/爸爸' or casual nicknames—as a person record even if no legal name is provided; reuse the literal phrase as the name and attach synonyms as nicknames. "
            "When storing notes, copy the user's original sentence(s) verbatim with no paraphrasing. Convert every actionable plan with a timeframe into tasks tied to a vision and attach planning-cycle metadata (type + start date) whenever the text implies timing (e.g., 今天 -> day cycle, 这个周末 -> week cycle)."
        ),
        tool_names=(
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
        ),
        response_guidance=(
            "- Summarize what was created (type + name) in plain text; avoid raw tool JSON.\n"
            "- If any tool fails, briefly explain which one and why."
        ),
        tool_usage_guidance=(
            "- Always call tools; never return a plan without executing.",
            "- Dedup sequence: tags -> persons -> visions -> tasks -> habits -> notes.",
            "- For each entity: first list/filter; if matching active record exists reuse its id; else create_*.",
            "- Use the freshly created or reused IDs to wire relationships (person_ids/tag_ids/task_id).",
            "- If a field is unknown (e.g., color), omit it rather than inventing values.",
            "- Do not ask the user for confirmation; proceed with best-effort creation in one pass.",
            "- Treat familial titles, nicknames, or pronouns that clearly refer to people as contacts; capture them via create_person with the phrase as name and append any variants to nicknames.",
            "- When calling create_note, pass the exact substring from the user input—do not summarize or translate the text.",
            "- For each actionable item, link it to an existing vision (default to 'Todos Inbox' if nothing matches) or create a new vision, then create a task with planning_cycle_type/start_date inferred from the text (day for 今天/今晚, week for 这个周末/本周, etc.).",
        ),
    ),
)


register_agent_config(
    "root_agent",
    build_config(
        role="You are the general assistant, understanding user intent and deciding whether to escalate to specialised agents or tools. You must describe any A2A option and obtain user confirmation before triggering the `a2a_agent` tool.",
        tool_names=("a2a_agent",),
        response_guidance=ROOT_AGENT_RESPONSE_GUIDANCE,
        tool_usage_guidance=ROOT_AGENT_TOOL_GUIDANCE,
    ),
)
