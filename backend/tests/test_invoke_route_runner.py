from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.a2a_invoke import A2AAgentInvokeRequest
from app.services import invoke_route_runner
from app.services.system_tools import ToolContext, ToolExecutionResult


async def _consume_stream(response: StreamingResponse) -> None:
    async for _ in response.body_iterator:
        pass


@pytest.mark.asyncio
async def test_http_stream_guard_blocks_duplicate_request_until_stream_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoke_route_runner._invoke_inflight_keys.clear()
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_run_http_invoke(**kwargs):  # noqa: ARG001
        async def iterator():
            started.set()
            await release.wait()
            yield "data: {}\n\n"

        return StreamingResponse(iterator(), media_type="text/event-stream")

    monkeypatch.setattr(invoke_route_runner, "run_http_invoke", fake_run_http_invoke)

    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/a2a", name="Demo Agent")
    )

    async def runtime_builder():
        return runtime

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "run long task",
            "conversationId": str(uuid4()),
            "metadata": {},
        }
    )
    common_kwargs = {
        "db": None,
        "user_id": uuid4(),
        "agent_id": uuid4(),
        "agent_source": "shared",
        "payload": payload,
        "gateway": object(),
        "runtime_builder": runtime_builder,
        "runtime_not_found_errors": (RuntimeError,),
        "runtime_not_found_status_code": 404,
        "runtime_validation_errors": (ValueError,),
        "runtime_validation_status_code": 400,
        "validate_message": lambda _: [],
        "logger": SimpleNamespace(info=lambda *args, **kwargs: None),
        "invoke_log_message": "test invoke",
        "invoke_log_extra_builder": lambda request, runtime: {},  # noqa: ARG001
    }

    first_response = await invoke_route_runner.run_http_invoke_route(
        **common_kwargs,
        stream=True,
    )
    assert isinstance(first_response, StreamingResponse)
    consume_task = asyncio.create_task(_consume_stream(first_response))
    await asyncio.wait_for(started.wait(), timeout=1.0)

    with pytest.raises(HTTPException) as exc_info:
        await invoke_route_runner.run_http_invoke_route(
            **common_kwargs,
            stream=False,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "invoke_inflight"

    release.set()
    await asyncio.wait_for(consume_task, timeout=1.0)
    assert invoke_route_runner._invoke_inflight_keys == {}


@pytest.mark.asyncio
async def test_run_http_invoke_records_usage_metadata(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    async def fake_prepare_state(**kwargs):  # noqa: ARG001
        return invoke_route_runner._InvokeState(
            local_session=object(),
            local_source="manual",
            conversation_id="conversation-1",
            context_id=None,
            metadata={},
            stream_identity={},
            stream_usage={},
            user_message_id=None,
            client_agent_message_id=None,
        )

    async def fake_record_local_invoke_messages(
        db,  # noqa: ARG001
        *,
        response_metadata=None,
        **kwargs,  # noqa: ARG001
    ):
        captured["response_metadata"] = response_metadata

    async def fake_commit_safely(db):  # noqa: ARG001
        return None

    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages",
        fake_record_local_invoke_messages,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    class _Gateway:
        async def invoke(self, **kwargs):  # noqa: ARG002
            return {
                "success": True,
                "content": "ok",
                "metadata": {
                    "opencode": {
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 20,
                            "total_tokens": 120,
                            "cost": 0.01,
                        }
                    }
                },
            }

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {},
        }
    )
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )

    response = await invoke_route_runner.run_http_invoke(
        db=object(),
        gateway=_Gateway(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        stream=False,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={},
    )

    assert response.success is True
    response_metadata = captured["response_metadata"]
    assert isinstance(response_metadata, dict)
    assert response_metadata["usage"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "cost": 0.01,
    }


def test_build_upstream_tools_merges_request_and_default_tools(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        invoke_route_runner.system_tool_registry,
        "build_upstream_tool_schema",
        lambda: [
            {"type": "function", "function": {"name": "hub_invoke_agent"}},
            {"type": "function", "function": {"name": "builtin-default"}},
        ],
    )

    merged = invoke_route_runner._build_upstream_tools(
        [
            {"function": {"name": "hub_invoke_agent"}},
            {"type": "function", "function": {"name": "custom_tool"}},
            {"function": {"name": "custom_tool"}},
        ]
    )
    assert [tool["function"]["name"] for tool in merged] == [
        "hub_invoke_agent",
        "custom_tool",
        "builtin-default",
    ]


@pytest.mark.asyncio
async def test_run_http_invoke_records_tool_call_result_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}
    tool_calls: list[dict[str, object]] = []

    class FakeTool:
        async def execute(self, params, context):  # noqa: ARG002
            return ToolExecutionResult(
                success=True,
                content="ok",
                metadata={"source": "fake"},
                error_code=None,
            )

    async def fake_prepare_state(**kwargs):  # noqa: ARG001
        return invoke_route_runner._InvokeState(
            local_session=object(),
            local_source="manual",
            conversation_id="conversation-1",
            context_id=None,
            metadata={},
            stream_identity={},
            stream_usage={},
            user_message_id=None,
            client_agent_message_id=None,
        )

    async def fake_record_local_invoke_messages(
        db,  # noqa: ARG001
        response_metadata=None,
        **kwargs,  # noqa: ARG001
    ):
        captured["response_metadata"] = response_metadata
        tool_calls.extend(response_metadata.get("tool_calls", []))

    async def fake_commit_safely(db):  # noqa: ARG001
        return None

    def fake_stream_sse(
        *,
        on_tool_call=None,
        on_complete=None,
        on_complete_metadata=None,
        on_event=None,
        **kwargs,  # noqa: ARG002, ANN001
    ):  # noqa: E501
        del on_event  # keep interface parity

        async def _iterator():
            if on_tool_call:
                await on_tool_call(
                    {
                        "tool_name": "fake_tool",
                        "tool_call_id": "tool-1",
                        "tool_args": {"foo": "bar"},
                    }
                )
            if on_complete_metadata:
                await on_complete_metadata({})
            if on_complete:
                await on_complete("assistant response")
            yield "data: {}\\n\\n"

        return StreamingResponse(_iterator(), media_type="text/event-stream")

    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)
    monkeypatch.setattr(
        invoke_route_runner.system_tool_registry,
        "get_tool",
        lambda name: FakeTool() if name == "fake_tool" else None,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages",
        fake_record_local_invoke_messages,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)
    monkeypatch.setattr(
        invoke_route_runner.a2a_invoke_service, "stream_sse", fake_stream_sse
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_build_upstream_tools",
        lambda request_tools: [{"type": "function", "function": {"name": "fake_tool"}}],
    )

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {},
            "tools": [{"type": "function", "function": {"name": "fake_tool"}}],
        }
    )
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )

    response = await invoke_route_runner.run_http_invoke(
        db=object(),
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        stream=True,
        validate_message=lambda _: [],
        logger=SimpleNamespace(
            info=lambda *args, **kwargs: None, debug=lambda *args, **kwargs: None
        ),
        log_extra={},
    )

    assert isinstance(response, StreamingResponse)
    async for _ in response.body_iterator:
        pass

    assert captured["response_metadata"] is not None
    assert tool_calls == [
        {
            "tool_name": "fake_tool",
            "tool_call_id": "tool-1",
            "success": True,
            "content": "ok",
            "error": None,
            "error_code": None,
            "metadata": {"source": "fake"},
            "args": {"foo": "bar"},
        }
    ]


@pytest.mark.asyncio
async def test_run_http_invoke_executes_non_stream_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeTool:
        async def execute(self, params, context):  # noqa: ARG002
            return ToolExecutionResult(
                success=True,
                content=f"tool:{params['task']}",
                metadata={"source": "fake"},
            )

    async def fake_prepare_state(**kwargs):  # noqa: ARG001
        return invoke_route_runner._InvokeState(
            local_session=object(),
            local_source="manual",
            conversation_id="conversation-1",
            context_id=None,
            metadata={},
            stream_identity={},
            stream_usage={},
            user_message_id=None,
            client_agent_message_id=None,
        )

    async def fake_record_local_invoke_messages(
        db,  # noqa: ARG001
        response_metadata=None,
        **kwargs,  # noqa: ARG001
    ):
        captured["response_metadata"] = response_metadata

    async def fake_commit_safely(db):  # noqa: ARG001
        return None

    class _Gateway:
        async def invoke(self, **kwargs):  # noqa: ARG002
            del kwargs
            return {
                "success": True,
                "content": "assistant",
                "tool_calls": [
                    {
                        "tool_name": "fake_tool",
                        "tool_call_id": "tool-1",
                        "tool_args": {"task": "calc"},
                    }
                ],
            }

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {},
            "tools": [{"type": "function", "function": {"name": "fake_tool"}}],
        }
    )
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )

    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)
    monkeypatch.setattr(
        invoke_route_runner.system_tool_registry,
        "get_tool",
        lambda name: FakeTool() if name == "fake_tool" else None,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages",
        fake_record_local_invoke_messages,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)
    response = await invoke_route_runner.run_http_invoke(
        db=object(),
        gateway=_Gateway(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        stream=False,
        validate_message=lambda _: [],
        logger=SimpleNamespace(
            info=lambda *args, **kwargs: None, debug=lambda *args, **kwargs: None
        ),
        log_extra={},
    )

    assert response.success is True
    response_metadata = captured["response_metadata"]
    assert isinstance(response_metadata, dict)
    assert response_metadata["tool_calls"] == [
        {
            "tool_name": "fake_tool",
            "tool_call_id": "tool-1",
            "success": True,
            "content": "tool:calc",
            "error": None,
            "error_code": None,
            "metadata": {"source": "fake"},
            "args": {"task": "calc"},
        }
    ]


@pytest.mark.asyncio
async def test_execute_tool_call_respects_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowTool:
        async def execute(self, params, context):  # noqa: ARG002
            del params
            del context
            await asyncio.sleep(1.0)
            return ToolExecutionResult(success=True, content="ok")

    tool_results: list[dict[str, object]] = []
    monkeypatch.setattr(
        invoke_route_runner.system_tool_registry, "get_tool", lambda name: SlowTool()
    )
    monkeypatch.setattr(
        invoke_route_runner.settings, "a2a_tool_call_timeout_seconds", 0.001
    )

    context = ToolContext(
        db=None,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        query="hello",
        context_id=None,
        conversation_id=None,
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        metadata={},
    )

    await invoke_route_runner._execute_tool_call(
        tool_call={
            "tool_name": "slow",
            "tool_call_id": "tool-3",
            "tool_args": {},
        },
        tool_context=context,
        tool_results=tool_results,
    )
    assert tool_results[0]["tool_call_id"] == "tool-3"
    assert tool_results[0]["success"] is False
    assert tool_results[0]["error_code"] == "tool_execution_timeout"


@pytest.mark.asyncio
async def test_run_http_invoke_records_tool_call_not_supported(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    async def fake_prepare_state(**kwargs):  # noqa: ARG001
        return invoke_route_runner._InvokeState(
            local_session=object(),
            local_source="manual",
            conversation_id="conversation-1",
            context_id=None,
            metadata={},
            stream_identity={},
            stream_usage={},
            user_message_id=None,
            client_agent_message_id=None,
        )

    async def fake_record_local_invoke_messages(
        db,  # noqa: ARG001
        response_metadata=None,
        **kwargs,  # noqa: ARG001
    ):
        captured["response_metadata"] = response_metadata

    async def fake_commit_safely(db):  # noqa: ARG001
        return None

    def fake_stream_sse(
        *,
        on_tool_call=None,
        on_complete=None,
        on_complete_metadata=None,
        on_event=None,
        **kwargs,  # noqa: ARG002, ANN001
    ):  # noqa: E501
        del on_event  # pragma: no cover - parity only

        async def _iterator():
            if on_tool_call:
                await on_tool_call(
                    {
                        "tool_name": "unsupported_tool",
                        "tool_call_id": "tool-2",
                        "tool_args": {},
                    }
                )
            if on_complete_metadata:
                await on_complete_metadata({})
            if on_complete:
                await on_complete("assistant response")
            yield "data: {}\\n\\n"

        return StreamingResponse(_iterator(), media_type="text/event-stream")

    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)
    monkeypatch.setattr(
        invoke_route_runner.system_tool_registry,
        "get_tool",
        lambda name: None,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages",
        fake_record_local_invoke_messages,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)
    monkeypatch.setattr(
        invoke_route_runner.a2a_invoke_service, "stream_sse", fake_stream_sse
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_build_upstream_tools",
        lambda request_tools: [
            {"type": "function", "function": {"name": "unsupported_tool"}}
        ],
    )

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {},
            "tools": [{"type": "function", "function": {"name": "unsupported_tool"}}],
        }
    )
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )

    response = await invoke_route_runner.run_http_invoke(
        db=object(),
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        stream=True,
        validate_message=lambda _: [],
        logger=SimpleNamespace(
            info=lambda *args, **kwargs: None, debug=lambda *args, **kwargs: None
        ),
        log_extra={},
    )
    assert isinstance(response, StreamingResponse)
    async for _ in response.body_iterator:
        pass

    response_metadata = captured["response_metadata"]
    assert response_metadata is not None
    assert response_metadata["tool_calls"] == [
        {
            "tool_name": "unsupported_tool",
            "tool_call_id": "tool-2",
            "success": False,
            "error": "Tool 'unsupported_tool' is not supported",
            "error_code": "method_not_supported",
        }
    ]
