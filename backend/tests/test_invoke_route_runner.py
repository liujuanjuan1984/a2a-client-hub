from __future__ import annotations

import asyncio
import inspect
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app.schemas.a2a_invoke import A2AAgentInvokeRequest, A2AAgentInvokeResponse
from app.services import invoke_route_runner
from app.services.system_tools import ToolExecutionResult


async def _consume_stream(response: StreamingResponse) -> None:
    async for _ in response.body_iterator:
        pass


class _NoopWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)


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


@pytest.mark.asyncio
async def test_run_http_invoke_route_retries_session_not_found_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    original_conversation_id = str(uuid4())
    rebound_conversation_id = str(uuid4())
    attempts: list[dict[str, str]] = []

    async def fake_run_http_invoke(**kwargs):  # noqa: ARG001
        payload = kwargs["payload"]
        attempts.append(
            {
                "conversationId": payload.conversation_id,
                "metadata": dict(payload.metadata or {}),
            }
        )
        if len(attempts) == 1:
            return A2AAgentInvokeResponse(
                success=False,
                error="session missing",
                error_code="session_not_found",
                agent_name="Demo Agent",
                agent_url="https://example.com",
            )
        return A2AAgentInvokeResponse(
            success=True,
            content="ok",
            error_code=None,
            agent_name="Demo Agent",
            agent_url="https://example.com",
        )

    async def fake_continue_session(
        *_,
        user_id: object,  # noqa: ARG002
        conversation_id: str,
        **__,  # noqa: ARG001
    ) -> tuple[dict[str, object], bool]:
        assert conversation_id == original_conversation_id
        return (
            {
                "conversationId": rebound_conversation_id,
                "source": "manual",
                "metadata": {
                    "provider": "opencode",
                    "externalSessionId": "upstream-sid-2",
                    "contextId": "ctx-2",
                },
            },
            True,
        )

    async def fake_commit_safely(_: object) -> None:
        return None

    monkeypatch.setattr(invoke_route_runner, "run_http_invoke", fake_run_http_invoke)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "continue_session",
        fake_continue_session,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    async def runtime_builder():
        return runtime

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "test invoke route",
            "conversationId": original_conversation_id,
            "metadata": {},
        }
    )

    response = await invoke_route_runner.run_http_invoke_route(
        db=object(),
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        stream=False,
        gateway=object(),
        runtime_builder=runtime_builder,
        runtime_not_found_errors=(RuntimeError,),
        runtime_not_found_status_code=404,
        runtime_validation_errors=(ValueError,),
        runtime_validation_status_code=400,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        invoke_log_message="test invoke",
        invoke_log_extra_builder=lambda req, runtime: {},  # noqa: ARG001
    )

    assert isinstance(response, A2AAgentInvokeResponse)
    assert response.success is True
    assert response.content == "ok"
    assert len(attempts) == 2
    assert attempts[0]["conversationId"] == original_conversation_id
    assert attempts[1]["conversationId"] == rebound_conversation_id
    assert attempts[1]["metadata"].get("provider") == "opencode"
    assert attempts[1]["metadata"].get("externalSessionId") == "upstream-sid-2"
    assert attempts[1]["metadata"].get("opencode_session_id") == "upstream-sid-2"


@pytest.mark.asyncio
async def test_run_http_invoke_route_retries_once_for_session_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    attempt = 0

    async def fake_run_http_invoke(**kwargs):  # noqa: ARG001
        nonlocal attempt
        attempt += 1
        return A2AAgentInvokeResponse(
            success=False,
            error="session missing",
            error_code="session_not_found",
            agent_name="Demo Agent",
            agent_url="https://example.com",
        )

    async def fake_continue_session(
        *_,
        user_id: object,  # noqa: ARG002
        conversation_id: str,
        **__,  # noqa: ARG001
    ) -> tuple[dict[str, object], bool]:
        assert conversation_id
        return (
            {
                "conversationId": conversation_id,
                "source": "manual",
                "metadata": {
                    "provider": "opencode",
                    "externalSessionId": "upstream-sid-2",
                    "contextId": "ctx-2",
                },
            },
            True,
        )

    async def fake_commit_safely(_: object) -> None:
        return None

    monkeypatch.setattr(invoke_route_runner, "run_http_invoke", fake_run_http_invoke)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "continue_session",
        fake_continue_session,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    async def runtime_builder():
        return runtime

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "test invoke route",
            "conversationId": str(uuid4()),
            "metadata": {},
        }
    )

    response = await invoke_route_runner.run_http_invoke_route(
        db=object(),
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        stream=False,
        gateway=object(),
        runtime_builder=runtime_builder,
        runtime_not_found_errors=(RuntimeError,),
        runtime_not_found_status_code=404,
        runtime_validation_errors=(ValueError,),
        runtime_validation_status_code=400,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        invoke_log_message="test invoke",
        invoke_log_extra_builder=lambda req, runtime: {},  # noqa: ARG001
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 404
    response_payload = json.loads(response.body.decode())
    assert response_payload["success"] is False
    assert response_payload["error_code"] == "session_not_found"
    assert attempt == 2


@pytest.mark.asyncio
async def test_run_ws_invoke_route_retries_session_not_found_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    original_conversation_id = str(uuid4())
    rebound_conversation_id = str(uuid4())
    prepare_payloads: list[dict[str, object]] = []
    stream_calls = 0

    async def fake_prepare_state(**kwargs):  # noqa: ARG001
        payload = kwargs["payload"]
        prepare_payloads.append(
            {
                "conversationId": payload.conversation_id,
                "metadata": dict(payload.metadata or {}),
            }
        )
        return invoke_route_runner._InvokeState(
            local_session=object(),
            local_source="manual",
            context_id=None,
            metadata={},
            stream_identity={},
            stream_usage={},
            user_message_id=None,
            client_agent_message_id=None,
        )

    async def fake_stream_ws(*, on_error_metadata=None, **kwargs):  # noqa: ARG001
        nonlocal stream_calls
        stream_calls += 1
        if stream_calls == 1 and on_error_metadata:
            result = on_error_metadata(
                {
                    "message": "Upstream streaming failed",
                    "error_code": "session_not_found",
                }
            )
            if inspect.isawaitable(result):
                await result

    async def fake_continue_session(
        *_,
        user_id: object,  # noqa: ARG002
        conversation_id: str,
        **__,  # noqa: ARG001
    ) -> tuple[dict[str, object], bool]:
        assert conversation_id == original_conversation_id
        return (
            {
                "conversationId": rebound_conversation_id,
                "source": "manual",
                "metadata": {
                    "provider": "opencode",
                    "externalSessionId": "upstream-sid-2",
                    "contextId": "ctx-2",
                },
            },
            True,
        )

    async def fake_commit_safely(_: object) -> None:
        return None

    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)
    monkeypatch.setattr(
        invoke_route_runner.a2a_invoke_service,
        "stream_ws",
        fake_stream_ws,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "continue_session",
        fake_continue_session,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages",
        lambda **kwargs: None,  # noqa: ARG005
    )

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "test invoke route",
            "conversationId": original_conversation_id,
            "metadata": {},
        }
    )
    websocket = _NoopWebSocket()

    await invoke_route_runner.run_ws_invoke_with_session_recovery(
        websocket=websocket,
        db=object(),
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={
            "user_id": str(uuid4()),
            "agent_id": str(uuid4()),
        },
        max_recovery_attempts=1,
    )

    assert prepare_payloads == [
        {
            "conversationId": original_conversation_id,
            "metadata": {},
        },
        {
            "conversationId": rebound_conversation_id,
            "metadata": {
                "provider": "opencode",
                "externalSessionId": "upstream-sid-2",
                "external_session_id": "upstream-sid-2",
                "opencode_session_id": "upstream-sid-2",
            },
        },
    ]
    assert stream_calls == 2
    assert len(websocket.sent) == 1
    assert json.loads(websocket.sent[0]) == {"event": "stream_end", "data": {}}


@pytest.mark.asyncio
async def test_run_ws_invoke_route_retries_session_not_found_then_exhausts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )
    original_conversation_id = str(uuid4())
    rebound_conversation_id = str(uuid4())
    prepare_payloads: list[dict[str, object]] = []
    stream_calls = 0
    observed_error_codes: list[str] = []

    async def fake_prepare_state(**kwargs):  # noqa: ARG001
        payload = kwargs["payload"]
        prepare_payloads.append(
            {
                "conversationId": payload.conversation_id,
                "metadata": dict(payload.metadata or {}),
            }
        )
        return invoke_route_runner._InvokeState(
            local_session=object(),
            local_source="manual",
            context_id=None,
            metadata={},
            stream_identity={},
            stream_usage={},
            user_message_id=None,
            client_agent_message_id=None,
        )

    async def fake_stream_ws(*, on_error_metadata=None, **kwargs):  # noqa: ARG001
        nonlocal stream_calls
        stream_calls += 1
        if on_error_metadata:
            observed_error_codes.append("session_not_found")
            result = on_error_metadata(
                {
                    "message": "Upstream streaming failed",
                    "error_code": "session_not_found",
                }
            )
            if inspect.isawaitable(result):
                await result

    async def fake_continue_session(
        *_,
        user_id: object,  # noqa: ARG002
        conversation_id: str,
        **__,  # noqa: ARG001
    ) -> tuple[dict[str, object], bool]:
        assert conversation_id == original_conversation_id
        return (
            {
                "conversationId": rebound_conversation_id,
                "source": "manual",
                "metadata": {
                    "provider": "opencode",
                    "externalSessionId": "upstream-sid-2",
                    "contextId": "ctx-2",
                },
            },
            True,
        )

    async def fake_commit_safely(_: object) -> None:
        return None

    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)
    monkeypatch.setattr(
        invoke_route_runner.a2a_invoke_service,
        "stream_ws",
        fake_stream_ws,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "continue_session",
        fake_continue_session,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages",
        lambda **kwargs: None,  # noqa: ARG005
    )

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "test invoke route",
            "conversationId": original_conversation_id,
            "metadata": {},
        }
    )
    websocket = _NoopWebSocket()

    await invoke_route_runner.run_ws_invoke_with_session_recovery(
        websocket=websocket,
        db=object(),
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={
            "user_id": str(uuid4()),
            "agent_id": str(uuid4()),
        },
        max_recovery_attempts=1,
    )

    sent = [json.loads(item) for item in websocket.sent]
    error_events = [event for event in sent if event["event"] == "error"]
    assert prepare_payloads == [
        {
            "conversationId": original_conversation_id,
            "metadata": {},
        },
        {
            "conversationId": rebound_conversation_id,
            "metadata": {
                "provider": "opencode",
                "externalSessionId": "upstream-sid-2",
                "external_session_id": "upstream-sid-2",
                "opencode_session_id": "upstream-sid-2",
            },
        },
    ]
    assert stream_calls == 2
    assert observed_error_codes == ["session_not_found", "session_not_found"]
    assert prepare_payloads == [
        {
            "conversationId": original_conversation_id,
            "metadata": {},
        },
        {
            "conversationId": rebound_conversation_id,
            "metadata": {
                "provider": "opencode",
                "externalSessionId": "upstream-sid-2",
                "external_session_id": "upstream-sid-2",
                "opencode_session_id": "upstream-sid-2",
            },
        },
    ]
    assert len(error_events) == 1
    assert (
        error_events[0]["data"]["error_code"] == "session_not_found_recovery_exhausted"
    )
    assert sent[-1] == {"event": "stream_end", "data": {}}


@pytest.mark.parametrize(
    "error_code, expected_status",
    [
        ("session_not_found", 404),
        ("outbound_not_allowed", 403),
        ("upstream_unreachable", 503),
        ("upstream_http_error", 502),
        ("upstream_error", 502),
        ("timeout", 504),
    ],
)
@pytest.mark.asyncio
async def test_run_http_invoke_route_returns_status_for_error_code(
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
    expected_status: int,
) -> None:
    async def fake_run_http_invoke(**kwargs):  # noqa: ARG001
        return A2AAgentInvokeResponse(
            success=False,
            error="synthetic upstream error",
            error_code=error_code,
            agent_name="Demo Agent",
            agent_url="https://example.com",
        )

    monkeypatch.setattr(invoke_route_runner, "run_http_invoke", fake_run_http_invoke)
    if error_code == "session_not_found":

        async def fake_continue_session(
            *_,
            user_id: object,  # noqa: ARG002
            conversation_id: str,
            **__,  # noqa: ARG001
        ) -> tuple[dict[str, object], bool]:
            return (
                {"conversationId": conversation_id},
                False,
            )

        async def fake_commit_safely(_: object) -> None:
            return None

        monkeypatch.setattr(
            invoke_route_runner.session_hub_service,
            "continue_session",
            fake_continue_session,
        )
        monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    runtime = SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")

    async def runtime_builder():
        return runtime

    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "test invoke route",
            "conversationId": str(uuid4()),
            "metadata": {},
        }
    )

    response = await invoke_route_runner.run_http_invoke_route(
        db=object(),
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        stream=False,
        gateway=object(),
        runtime_builder=runtime_builder,
        runtime_not_found_errors=(RuntimeError,),
        runtime_not_found_status_code=404,
        runtime_validation_errors=(ValueError,),
        runtime_validation_status_code=400,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        invoke_log_message="test invoke",
        invoke_log_extra_builder=lambda req, runtime: {},  # noqa: ARG001
    )
    assert isinstance(response, JSONResponse)
    assert response.status_code == expected_status
    response_payload = json.loads(response.body.decode())
    assert response_payload["success"] is False
    assert response_payload["error_code"] == error_code
            conversation_id="conversation-1",


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
