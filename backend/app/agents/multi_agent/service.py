"""High-level service combining planner, orchestrator, and runtimes."""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent_registry import ROOT_AGENT_NAME, agent_registry
from app.agents.multi_agent.models import AgentTask, TaskNode
from app.agents.multi_agent.orchestrator import AgentTaskOrchestrator
from app.agents.multi_agent.planner import NoteTaskPlanner
from app.agents.multi_agent.runtime import build_default_runtime_manager


class MultiAgentService:
    """Entry point for multi-agent workflows."""

    def __init__(self) -> None:
        runtime_manager = build_default_runtime_manager()
        self._orchestrator = AgentTaskOrchestrator(runtime_manager)
        self._note_planner = NoteTaskPlanner()

    async def summarise_notes(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        request_text: str,
        limit: int = 10,
        keyword: Optional[str] = None,
    ) -> AgentTask:
        task = self._note_planner.create_task(
            user_id=user_id,
            request_text=request_text,
            limit=limit,
            keyword=keyword,
        )
        return await self._orchestrator.run(db=db, task=task)

    async def invoke_agent(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        agent_name: str,
        instruction: Optional[str] = None,
        tool_name: Optional[str] = None,
        tool_args: Optional[Dict[str, Any]] = None,
    ) -> AgentTask:
        if agent_name == ROOT_AGENT_NAME:
            raise ValueError("Root agent cannot be invoked via multi-agent service")

        profile = agent_registry.get_profile(agent_name)
        if profile.name != agent_name:
            raise ValueError(f"Unknown agent '{agent_name}'")

        payload: Dict[str, Any] = {}
        if tool_name:
            payload["tool_name"] = tool_name
        if tool_args:
            payload["tool_args"] = tool_args

        node = TaskNode(
            id=f"{agent_name}_invoke",
            agent=agent_name,
            instruction=instruction or f"Invoke {agent_name}",
            payload=payload,
        )
        task = AgentTask.create(
            user_id=user_id,
            original_request=instruction or tool_name or agent_name,
            nodes=[node],
        )
        return await self._orchestrator.run(db=db, task=task)


multi_agent_service = MultiAgentService()

__all__ = ["multi_agent_service", "MultiAgentService"]
