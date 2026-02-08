"""Runtime abstractions for executing task nodes."""

from __future__ import annotations

from typing import Any, Dict, MutableMapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent_registry import (
    FOOD_AGENT_NAME,
    HABIT_AGENT_NAME,
    NOTE_AGENT_NAME,
    PERSON_AGENT_NAME,
    TAG_AGENT_NAME,
    TASK_AGENT_NAME,
    TIMELOG_AGENT_NAME,
    USER_PREFERENCE_AGENT_NAME,
    VISION_AGENT_NAME,
)
from app.agents.llm import llm_client
from app.agents.multi_agent.models import AgentTask, TaskNode
from app.agents.registry import ToolAccessRegistry
from app.agents.tool_policy import tool_policy
from app.agents.tools.responses import create_tool_error
from app.core.logging import get_logger
from app.handlers import notes as note_service
from app.serialization.entities import build_note_response
from app.utils.timezone_util import utc_today

logger = get_logger(__name__)


class AgentRuntimeError(RuntimeError):
    """Execution failure surfaced by a specific runtime."""


class AgentRuntime:
    """Base runtime definition."""

    name: str

    async def run(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        task: AgentTask,
        node: TaskNode,
    ) -> Dict[str, Any]:
        raise NotImplementedError


class RuntimeManager:
    """Registry mapping agent names to runtimes."""

    def __init__(self) -> None:
        self._runtimes: MutableMapping[str, AgentRuntime] = {}

    def register(self, runtime: AgentRuntime) -> None:
        if runtime.name in self._runtimes:
            raise ValueError(f"Runtime '{runtime.name}' already registered")
        self._runtimes[runtime.name] = runtime

    def get(self, name: str) -> AgentRuntime:
        runtime = self._runtimes.get(name)
        if runtime is None:
            raise KeyError(f"Runtime '{name}' not found")
        return runtime


class NoteRetrieverRuntime(AgentRuntime):
    """Fetch raw notes for downstream summarisation."""

    name = "note_retriever"

    async def run(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        task: AgentTask,
        node: TaskNode,
    ) -> Dict[str, Any]:
        limit = int(node.payload.get("limit", 10))
        keyword = node.payload.get("keyword")
        request_text = node.payload.get("request_text")

        logger.info(
            "NoteRetrieverRuntime executing",
            extra={
                "task_id": str(task.id),
                "user_id": str(user_id),
                "limit": limit,
                "keyword": keyword,
            },
        )

        notes = await note_service.list_notes(
            db=db,
            user_id=user_id,
            limit=limit,
            keyword=keyword or request_text,
        )
        associations = await note_service.get_notes_with_associations(
            db,
            user_id=user_id,
            notes=notes,
        )
        serialised_notes = []
        for note in notes:
            assoc = associations.get(note.id, {}) if associations else {}
            response = build_note_response(
                note,
                persons=assoc.get("persons"),
                task=assoc.get("task"),
                timelogs=assoc.get("timelogs"),
                include_timelogs=True,
            )
            serialised_notes.append(response.model_dump(mode="json"))
        return {
            "notes": serialised_notes,
            "note_count": len(serialised_notes),
            "keyword": keyword or request_text,
        }


class NoteSummariserRuntime(AgentRuntime):
    """Summarise collected notes with LLM support."""

    name = "note_summariser"

    summary_system_prompt = (
        "You are an assistant that organises and summarises user notes. "
        "Extract the most important insights, keep the structure tidy with short sections, "
        "and mirror the language used in the notes or the user's request."
    )

    async def run(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        task: AgentTask,
        node: TaskNode,
    ) -> Dict[str, Any]:
        dependency_id = node.depends_on[0] if node.depends_on else None
        dependency = task.nodes.get(dependency_id) if dependency_id else None
        notes_payload = dependency.result if dependency else None
        notes = notes_payload.get("notes") if notes_payload else []

        if not notes:
            logger.info(
                "NoteSummariserRuntime: no notes found, returning fallback",
                extra={"task_id": str(task.id)},
            )
            return {
                "summary": "未找到相关笔记，无法生成总结。",
                "note_count": 0,
                "notes": [],
            }

        request_text = node.payload.get("request_text", task.original_request)

        note_lines = []
        for idx, note in enumerate(notes, start=1):
            content = note.get("content") or note.get("text") or ""
            created_at = note.get("created_at")
            note_lines.append(f"[{idx}] {content}\nTime: {created_at}")

        user_prompt = (
            "User request:\n{request}\n\n"
            "Relevant notes:\n{notes}\n\n"
            "Please deliver a concise summary that covers:\n"
            "1. Key takeaways\n"
            "2. Actionable suggestions or follow-ups (if any)\n"
            "3. Additional questions or recommendations when information is missing.\n"
            "Keep the tone practical and mirror the language used in the notes or request."
        ).format(request=request_text, notes="\n\n".join(note_lines))

        response = await llm_client.completion(
            messages=[
                {"role": "system", "content": self.summary_system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=800,
        )

        content = response.choices[0].message.content if response.choices else ""
        summary = (content or "总结生成失败，请稍后重试。").strip()
        return {
            "summary": summary,
            "note_count": len(notes),
            "notes": notes,
        }


class ToolInvocationRuntime(AgentRuntime):
    """Runtime that executes a single tool via ToolAccessRegistry."""

    default_tool: str = ""
    default_arguments: Dict[str, Any] = {}

    def get_default_arguments(self, node: TaskNode) -> Dict[str, Any]:
        return dict(self.default_arguments)

    async def run(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        task: AgentTask,
        node: TaskNode,
    ) -> Dict[str, Any]:
        payload = node.payload or {}
        tool_name = payload.get("tool_name") or self.default_tool
        if not tool_name:
            raise AgentRuntimeError(
                f"No tool specified for agent '{self.name}'. Payload: {payload}"
            )

        tool_args = payload.get("tool_args") or self.get_default_arguments(node)
        registry = ToolAccessRegistry(
            db=db,
            user_id=user_id,
            agent_name=self.name,
        )
        metadata = registry.get_tool_metadata(tool_name)
        allowed, reason = tool_policy.should_execute(tool_name, 1, metadata)
        if not allowed:
            blocked = create_tool_error(
                message=f"Tool '{tool_name}' call blocked by policy",
                kind=reason or "policy_blocked",
            )
            return {
                "agent": self.name,
                "tool_name": tool_name,
                "tool_args": tool_args,
                "result": blocked.to_payload(),
            }

        tool_policy.register_start(tool_name)
        try:
            tool_result = await registry.execute_tool(
                tool_name,
                metadata_override=metadata,
                **tool_args,
            )
        finally:
            tool_policy.register_finish(
                tool_name,
                success=tool_result.is_success if "tool_result" in locals() else False,
            )

        parsed_result = tool_result.to_payload()
        return {
            "agent": self.name,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "result": parsed_result,
        }


class NoteAgentRuntime(ToolInvocationRuntime):
    name = NOTE_AGENT_NAME
    default_tool = "get_latest_notes"
    default_arguments = {"limit": 10}


class TaskAgentRuntime(ToolInvocationRuntime):
    name = TASK_AGENT_NAME
    default_tool = "list_tasks_by_planning_cycle"

    def get_default_arguments(self, node: TaskNode) -> Dict[str, Any]:
        today = utc_today().isoformat()
        return {
            "planning_cycle_type": "week",
            "planning_cycle_start_date": today,
            "skip": 0,
            "limit": 20,
        }


class HabitAgentRuntime(ToolInvocationRuntime):
    name = HABIT_AGENT_NAME
    default_tool = "list_habits"
    default_arguments = {"skip": 0, "limit": 20}


class TimeLogAgentRuntime(ToolInvocationRuntime):
    name = TIMELOG_AGENT_NAME
    default_tool = "list_time_logs"
    default_arguments = {"skip": 0, "limit": 20}


class PersonAgentRuntime(ToolInvocationRuntime):
    name = PERSON_AGENT_NAME
    default_tool = "list_persons"
    default_arguments = {"skip": 0, "limit": 20}


class TagAgentRuntime(ToolInvocationRuntime):
    name = TAG_AGENT_NAME
    default_tool = "list_tags"
    default_arguments = {"skip": 0, "limit": 20}


class VisionAgentRuntime(ToolInvocationRuntime):
    name = VISION_AGENT_NAME
    default_tool = "list_visions"
    default_arguments = {"skip": 0, "limit": 20}


class FoodAgentRuntime(ToolInvocationRuntime):
    name = FOOD_AGENT_NAME
    default_tool = "list_foods"
    default_arguments = {"limit": 20, "offset": 0}


class UserPreferenceAgentRuntime(ToolInvocationRuntime):
    name = USER_PREFERENCE_AGENT_NAME
    default_tool = "list_user_preferences"
    default_arguments = {"skip": 0, "limit": 20}


def build_default_runtime_manager() -> RuntimeManager:
    """Factory creating a runtime manager with built-in note agents."""

    manager = RuntimeManager()
    manager.register(NoteRetrieverRuntime())
    manager.register(NoteSummariserRuntime())
    manager.register(NoteAgentRuntime())
    manager.register(TaskAgentRuntime())
    manager.register(HabitAgentRuntime())
    manager.register(TimeLogAgentRuntime())
    manager.register(PersonAgentRuntime())
    manager.register(TagAgentRuntime())
    manager.register(VisionAgentRuntime())
    manager.register(FoodAgentRuntime())
    manager.register(UserPreferenceAgentRuntime())
    return manager


__all__ = [
    "AgentRuntime",
    "AgentRuntimeError",
    "RuntimeManager",
    "NoteRetrieverRuntime",
    "NoteSummariserRuntime",
    "NoteAgentRuntime",
    "ToolInvocationRuntime",
    "TaskAgentRuntime",
    "HabitAgentRuntime",
    "TimeLogAgentRuntime",
    "PersonAgentRuntime",
    "TagAgentRuntime",
    "VisionAgentRuntime",
    "FoodAgentRuntime",
    "UserPreferenceAgentRuntime",
    "build_default_runtime_manager",
]
