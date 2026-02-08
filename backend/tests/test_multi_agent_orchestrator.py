"""Unit tests for the multi-agent orchestrator."""

from __future__ import annotations

from typing import Dict
from uuid import uuid4

import pytest

from app.agents.multi_agent.models import AgentTask, TaskNode, TaskNodeStatus
from app.agents.multi_agent.orchestrator import AgentTaskOrchestrator
from app.agents.multi_agent.runtime import AgentRuntime, RuntimeManager


class _RecordingRuntime(AgentRuntime):
    def __init__(self, name: str, records: list[str], payload: Dict[str, str]):
        self.name = name
        self._records = records
        self._payload = payload

    async def run(self, *, db, user_id, task, node):  # type: ignore[no-untyped-def]
        self._records.append(self.name)
        return dict(self._payload)


@pytest.mark.asyncio
async def test_orchestrator_executes_nodes_in_dependency_order():
    order: list[str] = []

    first_runtime = _RecordingRuntime("first_agent", order, {"value": "first"})
    second_runtime = _RecordingRuntime("second_agent", order, {"value": "second"})

    manager = RuntimeManager()
    manager.register(first_runtime)
    manager.register(second_runtime)

    first_node = TaskNode(
        id="first",
        agent="first_agent",
        instruction="run first",
    )
    second_node = TaskNode(
        id="second",
        agent="second_agent",
        instruction="run second",
        depends_on=["first"],
    )

    task = AgentTask.create(
        user_id=uuid4(),
        original_request="demo",
        nodes=[first_node, second_node],
    )

    orchestrator = AgentTaskOrchestrator(manager)
    completed_task = await orchestrator.run(db=None, task=task)

    assert order == ["first_agent", "second_agent"]
    assert completed_task.nodes["first"].status == TaskNodeStatus.COMPLETED
    assert completed_task.nodes["second"].status == TaskNodeStatus.COMPLETED
    assert completed_task.final_result == {"value": "second"}
