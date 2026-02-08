"""Runtime policies for agent tool execution."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple

from app.agents.tools.base import ToolMetadata
from app.core.logging import get_logger

logger = get_logger(__name__)

RATE_WINDOW_SECONDS = 60


@dataclass
class ToolPolicyConfig:
    """Configuration values controlling tool availability and execution order."""

    disabled_tools: set[str] = field(default_factory=set)
    per_request_limit: Dict[str, int] = field(default_factory=dict)
    priority: Dict[str, int] = field(default_factory=dict)
    rate_limits: Dict[str, int] = field(default_factory=dict)  # calls per minute
    concurrency_limits: Dict[str, int] = field(default_factory=dict)
    require_confirmation: set[str] = field(default_factory=set)


DEFAULT_TOOL_POLICY = ToolPolicyConfig()


class ToolPolicy:
    """Evaluate LLM tool calls against policy rules."""

    def __init__(self, config: Optional[ToolPolicyConfig] = None) -> None:
        self.config = config or DEFAULT_TOOL_POLICY
        self._lock = Lock()
        self._active_counts: Dict[str, int] = defaultdict(int)
        self._recent_calls: Dict[str, Deque[float]] = defaultdict(deque)

    def order_calls(self, tool_calls: Iterable[Any]) -> List[Any]:
        """Return tool calls sorted by configured priority (lower number first)."""

        def _priority(call: Any) -> int:
            name = getattr(getattr(call, "function", None), "name", None)
            if name is None:
                return 100
            return self.config.priority.get(name, 50)

        return sorted(tool_calls, key=_priority)

    def should_execute(
        self,
        tool_name: str,
        call_index: int,
        metadata: Optional[ToolMetadata] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Determine whether a tool call should run."""

        with self._lock:
            if tool_name in self.config.disabled_tools:
                return False, "disabled"

            limit = self.config.per_request_limit.get(tool_name)
            if limit is not None and call_index > limit:
                return False, "limit_exceeded"

            concurrency_limit = self.config.concurrency_limits.get(tool_name)
            if concurrency_limit is not None:
                active = self._active_counts[tool_name]
                if active >= concurrency_limit:
                    return False, "concurrency_limit"

            rate_limit = self.config.rate_limits.get(tool_name)
            if rate_limit is not None and rate_limit > 0:
                calls = self._recent_calls[tool_name]
                now = time.time()
                while calls and now - calls[0] > RATE_WINDOW_SECONDS:
                    calls.popleft()
                if len(calls) >= rate_limit:
                    return False, "rate_limit"

        return True, None

    def register_start(self, tool_name: str) -> None:
        with self._lock:
            self._active_counts[tool_name] += 1

    def register_finish(self, tool_name: str, success: bool) -> None:
        with self._lock:
            self._active_counts[tool_name] = max(0, self._active_counts[tool_name] - 1)
            self._recent_calls[tool_name].append(time.time())

    def requires_confirmation(
        self, tool_name: str, metadata: Optional[ToolMetadata] = None
    ) -> bool:
        metadata_requires = metadata.requires_confirmation if metadata else False
        policy_requires = tool_name in self.config.require_confirmation
        return metadata_requires or policy_requires


tool_policy = ToolPolicy()

__all__ = ["ToolPolicy", "ToolPolicyConfig", "tool_policy"]
