import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.agents.agent_service import AgentService
from app.agents.service_types import AgentRuntimeContext


def test_handle_invalid_tool_call_records_failure(monkeypatch):
    service = AgentService()
    engine = service.tool_executor
    tool_call = SimpleNamespace(id="call-123")
    run_record = {
        "tool_call_id": "call-123",
        "tool_name": "invalid_tool",
        "status": "started",
        "message": None,
        "arguments": {},
        "sequence": 1,
        "started_at": "2025-10-14T00:00:00+00:00",
    }
    messages = []
    failures = []

    runtime = AgentRuntimeContext(
        db=None,
        user_id=uuid4(),
        agent_name="root_agent",
        message_id=uuid4(),
    )

    monkeypatch.setattr(
        engine,
        "_sync_tool_result_to_cardbox",
        lambda **kwargs: None,
    )

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(engine, "_persist_tool_message", _noop)

    event = asyncio.run(
        engine.handle_invalid_tool_call(
            tool_call=tool_call,
            run_record=run_record,
            reason="Missing tool name",
            error_kind="invalid_tool_call",
            messages=messages,
            tool_failures=failures,
            runtime=runtime,
        )
    )

    assert event.event == "tool_failed"
    assert failures == [{"tool": "invalid_tool", "reason": "Missing tool name"}]
    assert messages and messages[-1]["role"] == "tool"
