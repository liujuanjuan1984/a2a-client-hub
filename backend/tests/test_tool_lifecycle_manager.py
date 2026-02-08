"""Tests covering ToolLifecycleManager behaviour."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.agents.tools.base import AbstractTool, ToolHealthStatus
from app.agents.tools.lifecycle import ToolLifecycleManager, ToolUnavailableError
from app.agents.tools.responses import ToolResult, create_tool_response


class _EmptyArgsSchema:
    """Minimal Pydantic-like shim."""

    @classmethod
    def model_json_schema(cls):
        return {"properties": {}, "required": []}

    def __init__(self, **kwargs):
        if kwargs:
            raise ValueError("No args supported")

    def model_dump(self):
        return {}


class _BaseDummyTool(AbstractTool):
    name = "dummy_tool"
    description = "dummy"
    args_schema = _EmptyArgsSchema  # type: ignore[assignment]

    def __init__(self):
        super().__init__(db=MagicMock(), user_id=uuid4())
        self.initialise_calls = 0
        self.health_calls = 0

    async def initialise(self) -> None:
        self.initialise_calls += 1

    async def execute(self, **kwargs) -> ToolResult:
        return create_tool_response()


class HealthyDummyTool(_BaseDummyTool):
    async def health_check(self) -> ToolHealthStatus:
        self.health_calls += 1
        return ToolHealthStatus()


class FailingHealthDummyTool(_BaseDummyTool):
    async def health_check(self) -> ToolHealthStatus:
        self.health_calls += 1
        raise RuntimeError("health check failed")


@pytest.mark.asyncio
async def test_manager_initialises_once():
    manager = ToolLifecycleManager(health_check_interval=0.0)
    tool = HealthyDummyTool()

    await manager.ensure_ready("dummy", tool)
    assert tool.initialise_calls == 1

    await manager.ensure_ready("dummy", tool)
    assert tool.initialise_calls == 1  # no double initialisation


@pytest.mark.asyncio
async def test_manager_opens_circuit_on_health_check_failure():
    manager = ToolLifecycleManager(
        health_check_interval=0.01,
        failure_threshold=1,
        circuit_breaker_timeout=5.0,
    )
    tool = FailingHealthDummyTool()

    with pytest.raises(ToolUnavailableError):
        await manager.ensure_ready("failing", tool)

    # Subsequent calls stay blocked while circuit open
    with pytest.raises(ToolUnavailableError):
        await manager.ensure_ready("failing", tool)


@pytest.mark.asyncio
async def test_record_failure_triggers_circuit_breaker():
    manager = ToolLifecycleManager(
        health_check_interval=3600.0,
        failure_threshold=2,
        circuit_breaker_timeout=5.0,
    )
    tool = HealthyDummyTool()

    await manager.ensure_ready("dummy", tool)
    await manager.record_failure("dummy", RuntimeError("first failure"))

    # First failure should not open circuit yet
    await manager.ensure_ready("dummy", tool)

    await manager.record_failure("dummy", RuntimeError("second failure"))
    with pytest.raises(ToolUnavailableError):
        await manager.ensure_ready("dummy", tool)

    # Reset circuit via success record
    await manager.record_success("dummy")
    await manager.ensure_ready("dummy", tool)
