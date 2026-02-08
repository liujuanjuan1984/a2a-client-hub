"""Planning utilities for batching agent tool executions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence

from app.agents.tools.base import ToolMetadata


@dataclass(frozen=True)
class PreparedToolCall:
    """Minimal data required to evaluate and execute a tool call."""

    tool_call: Any
    name: str
    arguments: Dict[str, Any]
    run_record: Dict[str, Any]
    metadata: ToolMetadata
    call_index: int


@dataclass(frozen=True)
class ToolExecutionBatch:
    """A batch of tool calls to execute either sequentially or concurrently."""

    calls: List[PreparedToolCall]
    concurrent: bool = False

    @property
    def is_concurrent(self) -> bool:
        return self.concurrent and len(self.calls) > 1


class ToolExecutionPlanner:
    """
    Group prepared tool calls into execution batches based on metadata.

    当前策略会将连续的只读(`read_only`)、幂等(`idempotent`)且无需确认的调用
    归为同一并发批次，其余调用保持串行执行，整体顺序不变。
    """

    def __init__(self, *, allowed_labels: Iterable[str] | None = None) -> None:
        self.allowed_labels = set(allowed_labels or [])

    def plan(self, calls: Sequence[PreparedToolCall]) -> List[ToolExecutionBatch]:
        """Return execution batches preserving call order."""

        batches: List[ToolExecutionBatch] = []
        current_batch: List[PreparedToolCall] = []
        current_concurrent = False

        for call in calls:
            can_parallel = self._is_concurrency_candidate(call)
            if can_parallel:
                if current_batch and not current_concurrent:
                    # Flush preceding sequential batch.
                    batches.append(
                        ToolExecutionBatch(calls=list(current_batch), concurrent=False)
                    )
                    current_batch = []
                current_concurrent = True
                current_batch.append(call)
                continue

            # Flush any existing concurrent batch before handling sequential call.
            if current_batch:
                batches.append(
                    ToolExecutionBatch(
                        calls=list(current_batch),
                        concurrent=current_concurrent and len(current_batch) > 1,
                    )
                )
                current_batch = []

            current_concurrent = False
            batches.append(ToolExecutionBatch(calls=[call], concurrent=False))

        if current_batch:
            batches.append(
                ToolExecutionBatch(
                    calls=list(current_batch),
                    concurrent=current_concurrent and len(current_batch) > 1,
                )
            )

        return batches

    def _is_concurrency_candidate(self, call: PreparedToolCall) -> bool:
        metadata = call.metadata
        if not metadata.read_only or metadata.requires_confirmation:
            return False
        if not metadata.idempotent:
            return False
        if self.allowed_labels:
            labels = set(metadata.labels)
            return bool(labels & self.allowed_labels)
        return True


__all__ = [
    "PreparedToolCall",
    "ToolExecutionBatch",
    "ToolExecutionPlanner",
]
