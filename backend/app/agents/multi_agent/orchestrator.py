"""Task graph orchestration for multi-agent execution."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.multi_agent.models import AgentTask, TaskNode, TaskNodeStatus
from app.agents.multi_agent.runtime import AgentRuntimeError, RuntimeManager
from app.core.logging import get_logger

logger = get_logger(__name__)


class TaskStalledError(RuntimeError):
    """Raised when no nodes can be scheduled but task still has active nodes."""


class AgentTaskOrchestrator:
    """Sequential orchestrator executing ready nodes until completion."""

    def __init__(self, runtime_manager: RuntimeManager) -> None:
        self.runtime_manager = runtime_manager

    async def run(self, db: AsyncSession, task: AgentTask) -> AgentTask:
        """Execute the task graph in-place and return the updated task."""

        logger.info("Starting task orchestration", extra={"task_id": str(task.id)})

        while task.has_active_nodes():
            ready_nodes = task.ready_nodes()
            if not ready_nodes:
                logger.error(
                    "No executable nodes found while task still active",
                    extra={"task_id": str(task.id)},
                )
                raise TaskStalledError(
                    "Task stalled: pending nodes without satisfied dependencies"
                )

            for node in ready_nodes:
                await self._run_node(db=db, task=task, node=node)

        task.final_result = self._compute_final_result(task)
        logger.info(
            "Task orchestration completed",
            extra={"task_id": str(task.id)},
        )
        return task

    async def _run_node(
        self, *, db: AsyncSession, task: AgentTask, node: TaskNode
    ) -> None:
        runtime = self.runtime_manager.get(node.agent)
        node.status = TaskNodeStatus.RUNNING
        try:
            result = await runtime.run(
                db=db, user_id=task.user_id, task=task, node=node
            )
        except AgentRuntimeError as exc:
            logger.error(
                "Runtime error",
                extra={"task_id": str(task.id), "node_id": node.id, "error": str(exc)},
            )
            task.mark_failed(node, str(exc))
            raise
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception(
                "Unexpected runtime failure",
                extra={"task_id": str(task.id), "node_id": node.id},
            )
            task.mark_failed(node, str(exc))
            raise AgentRuntimeError(str(exc)) from exc
        else:
            node.result = result
            node.status = TaskNodeStatus.COMPLETED
            logger.info(
                "Node completed",
                extra={"task_id": str(task.id), "node_id": node.id},
            )

    def _compute_final_result(self, task: AgentTask) -> Optional[dict]:
        """Return the latest completed node result as final output."""

        completed_nodes = [
            node
            for node in task.nodes.values()
            if node.status == TaskNodeStatus.COMPLETED and node.result is not None
        ]
        if not completed_nodes:
            return None
        # Assume the node with the greatest dependency depth finished last.
        # The simple heuristic is to prefer nodes without dependants, falling back to ordering.
        leaf_nodes = [
            node
            for node in completed_nodes
            if not any(node.id in other.depends_on for other in task.nodes.values())
        ]
        target_node = leaf_nodes[0] if leaf_nodes else completed_nodes[-1]
        return target_node.result


__all__ = ["AgentTaskOrchestrator", "TaskStalledError"]
