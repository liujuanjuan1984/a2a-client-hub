"""Lifecycle management utilities for agent tools."""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass
from typing import Dict, Optional

from app.agents.tools.base import AbstractTool, ToolHealthStatus
from app.core.logging import get_logger, log_exception

logger = get_logger(__name__)


class ToolUnavailableError(RuntimeError):
    """Raised when a tool is temporarily unavailable due to lifecycle state."""


@dataclass
class ToolLifecycleState:
    """Mutable state captured for each tool instance."""

    initialised: bool = False
    last_initialised_at: float = 0.0
    last_health_check_at: float = 0.0
    consecutive_failures: int = 0
    circuit_open_until: float = 0.0
    last_failure_reason: Optional[str] = None
    lock: Optional[asyncio.Lock] = None


class ToolLifecycleManager:
    """Manage tool initialisation, health checks and circuit breaking."""

    def __init__(
        self,
        *,
        health_check_interval: float = 300.0,
        failure_threshold: int = 3,
        circuit_breaker_timeout: float = 120.0,
    ) -> None:
        self.health_check_interval = max(0.0, health_check_interval)
        self.failure_threshold = max(1, failure_threshold)
        self.circuit_breaker_timeout = max(1.0, circuit_breaker_timeout)
        self._states: Dict[str, ToolLifecycleState] = {}

    def get_state(self, tool_name: str) -> ToolLifecycleState:
        """Return lifecycle state for the given tool."""

        state = self._states.get(tool_name)
        if state is None:
            state = ToolLifecycleState()
            self._states[tool_name] = state
        return state

    def _ensure_lock(self, state: ToolLifecycleState) -> asyncio.Lock:
        if state.lock is None:
            state.lock = asyncio.Lock()
        return state.lock

    def _apply_failure(
        self,
        state: ToolLifecycleState,
        error: Exception,
        *,
        now: Optional[float] = None,
        tool_name: Optional[str] = None,
    ) -> None:
        timestamp = time.monotonic() if now is None else now
        state.consecutive_failures += 1
        state.last_failure_reason = str(error)

        if state.consecutive_failures >= self.failure_threshold:
            state.circuit_open_until = timestamp + self.circuit_breaker_timeout
            state.consecutive_failures = 0
            if tool_name:
                logger.warning(
                    "Opening circuit for tool '%s' after repeated failures",
                    tool_name,
                )

    def _apply_success(self, state: ToolLifecycleState) -> None:
        state.consecutive_failures = 0
        state.circuit_open_until = 0.0
        state.last_failure_reason = None

    async def ensure_ready(self, tool_name: str, tool: AbstractTool) -> None:
        """Ensure a tool instance is initialised and healthy."""

        state = self.get_state(tool_name)
        async with self._ensure_lock(state):
            now = time.monotonic()
            if state.circuit_open_until and now < state.circuit_open_until:
                raise ToolUnavailableError(
                    f"Tool '{tool_name}' unavailable until "
                    f"{state.circuit_open_until - now:.0f}s later: "
                    f"{state.last_failure_reason or 'circuit open'}"
                )

            if not state.initialised:
                logger.info("Initialising tool '%s'", tool_name)
                await tool.initialise()
                state.initialised = True
                state.last_initialised_at = now

            if self.health_check_interval <= 0:
                return

            if (
                state.last_health_check_at
                and (now - state.last_health_check_at) < self.health_check_interval
            ):
                return

            try:
                health = await tool.health_check()
            except Exception as exc:  # pragma: no cover - defensive logging
                log_exception(
                    logger,
                    f"Health check failed for tool '{tool_name}': {exc}",
                    sys.exc_info(),
                )
                self._apply_failure(state, exc, now=now, tool_name=tool_name)
                raise ToolUnavailableError(
                    f"Tool '{tool_name}' failed health check: {exc}"
                ) from exc

            if isinstance(health, ToolHealthStatus):
                if not health.healthy:
                    reason = health.message or "reported unhealthy state"
                    failure = RuntimeError(health.detail or reason)
                    self._apply_failure(
                        state,
                        failure,
                        now=now,
                        tool_name=tool_name,
                    )
                    raise ToolUnavailableError(
                        f"Tool '{tool_name}' reported unhealthy: {reason}"
                    )

            state.last_health_check_at = now

    async def record_success(self, tool_name: str) -> None:
        """Reset failure counters after successful execution."""

        state = self.get_state(tool_name)
        async with self._ensure_lock(state):
            self._apply_success(state)

    async def record_failure(self, tool_name: str, error: Exception) -> None:
        """Increase failure counters and trigger circuit break if necessary."""

        state = self.get_state(tool_name)
        async with self._ensure_lock(state):
            self._apply_failure(
                state,
                error,
                now=time.monotonic(),
                tool_name=tool_name,
            )

    async def shutdown(self) -> None:
        """Reset lifecycle manager (used in testing/cleanup)."""

        for state in self._states.values():
            async with self._ensure_lock(state):
                state.initialised = False
                state.last_initialised_at = 0.0
                state.last_health_check_at = 0.0
                self._apply_success(state)
