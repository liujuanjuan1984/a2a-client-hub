"""Dataclasses and enums describing multi-agent tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID, uuid4

from app.utils.timezone_util import utc_now


class TaskNodeStatus(str, Enum):
    """Execution status for a single task node."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskNode:
    """Single node in a task graph."""

    id: str
    agent: str
    instruction: str
    depends_on: List[str] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)
    status: TaskNodeStatus = TaskNodeStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def is_ready(self, completed_nodes: Iterable[str]) -> bool:
        """Return True when the node has no unmet dependencies."""

        return all(dep in completed_nodes for dep in self.depends_on)


@dataclass
class AgentTask:
    """Task graph tracked during multi-agent orchestration."""

    id: UUID
    user_id: UUID
    original_request: str
    created_at: datetime
    nodes: Dict[str, TaskNode]
    final_result: Optional[Dict[str, Any]] = None

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        original_request: str,
        nodes: Iterable[TaskNode],
    ) -> "AgentTask":
        """Helper for constructing a task with generated identifier."""

        node_list = list(nodes)
        node_mapping = {node.id: node for node in node_list}
        if len(node_mapping) != len(node_list):
            raise ValueError("Task node identifiers must be unique")
        return cls(
            id=uuid4(),
            user_id=user_id,
            original_request=original_request,
            created_at=utc_now(),
            nodes=node_mapping,
        )

    def ready_nodes(self) -> List[TaskNode]:
        """Return nodes that are pending and whose dependencies are satisfied."""

        completed_ids = {
            node_id
            for node_id, node in self.nodes.items()
            if node.status == TaskNodeStatus.COMPLETED
        }
        ready: List[TaskNode] = []
        for node in self.nodes.values():
            if node.status != TaskNodeStatus.PENDING:
                continue
            if node.is_ready(completed_ids):
                ready.append(node)
        return ready

    def has_active_nodes(self) -> bool:
        """Return True while there are nodes pending or running."""

        return any(
            node.status in {TaskNodeStatus.PENDING, TaskNodeStatus.RUNNING}
            for node in self.nodes.values()
        )

    def mark_failed(self, node: TaskNode, error: str) -> None:
        """Persist failure information on the node."""

        node.status = TaskNodeStatus.FAILED
        node.error = error


__all__ = ["AgentTask", "TaskNode", "TaskNodeStatus"]
