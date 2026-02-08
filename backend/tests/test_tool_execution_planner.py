"""Tests for ToolExecutionPlanner batching behaviour."""

from __future__ import annotations

from types import SimpleNamespace

from app.agents.tools.base import ToolMetadata
from app.agents.tools.planner import PreparedToolCall, ToolExecutionPlanner


def _prepared_call(
    name: str,
    *,
    read_only: bool = True,
    idempotent: bool = True,
    requires_confirmation: bool = False,
) -> PreparedToolCall:
    metadata = ToolMetadata(
        read_only=read_only,
        idempotent=idempotent,
        requires_confirmation=requires_confirmation,
    )
    return PreparedToolCall(
        tool_call=SimpleNamespace(id=f"{name}-id"),
        name=name,
        arguments={},
        run_record={"tool_name": name},
        metadata=metadata,
        call_index=1,
    )


def test_planner_groups_read_only_calls():
    planner = ToolExecutionPlanner()
    calls = [
        _prepared_call("read_a"),
        _prepared_call("read_b"),
    ]
    batches = planner.plan(calls)
    assert len(batches) == 1
    assert batches[0].is_concurrent
    assert [c.name for c in batches[0].calls] == ["read_a", "read_b"]


def test_planner_splits_write_call():
    planner = ToolExecutionPlanner()
    calls = [
        _prepared_call("read_a"),
        _prepared_call("write_b", read_only=False),
        _prepared_call("read_c"),
    ]
    batches = planner.plan(calls)
    assert len(batches) == 3
    assert batches[0].is_concurrent is False  # single call batch
    assert batches[1].is_concurrent is False
    assert batches[1].calls[0].name == "write_b"
    assert batches[2].is_concurrent is False  # single read call


def test_planner_respects_confirmation_flag():
    planner = ToolExecutionPlanner()
    calls = [
        _prepared_call("read_a"),
        _prepared_call("confirm_b", requires_confirmation=True),
        _prepared_call("read_c"),
    ]
    batches = planner.plan(calls)
    assert len(batches) == 3
    assert batches[0].is_concurrent is False  # single read
    assert batches[1].is_concurrent is False
    assert batches[1].calls[0].name == "confirm_b"
