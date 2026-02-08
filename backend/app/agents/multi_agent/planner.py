"""Planner for building task graphs from user requests."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from app.agents.multi_agent.models import AgentTask, TaskNode


class NoteTaskPlanner:
    """Heuristic planner that creates a two-step note summary task graph."""

    def create_task(
        self,
        *,
        user_id: UUID,
        request_text: str,
        limit: int = 10,
        keyword: Optional[str] = None,
    ) -> AgentTask:
        """Construct a task graph with retrieval and summarisation nodes."""

        retrieval_node = TaskNode(
            id="collect_notes",
            agent="note_retriever",
            instruction="Collect relevant notes for the user's query.",
            payload={"limit": limit, "keyword": keyword, "request_text": request_text},
        )
        summariser_node = TaskNode(
            id="summarise_notes",
            agent="note_summariser",
            instruction="Create a concise summary based on collected notes.",
            depends_on=[retrieval_node.id],
            payload={"request_text": request_text},
        )
        return AgentTask.create(
            user_id=user_id,
            original_request=request_text,
            nodes=[retrieval_node, summariser_node],
        )


__all__ = ["NoteTaskPlanner"]
