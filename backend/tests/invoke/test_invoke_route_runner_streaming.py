from __future__ import annotations

from tests.invoke.invoke_route_runner_support import (
    UUID,
    A2AAgentInvokeRequest,
    BindInflightTaskReport,
    SimpleNamespace,
    StreamFinishReason,
    StreamingResponse,
    StreamOutcome,
    _build_persistence_request,
    _consume_stream,
    _NoopWebSocket,
    deserialize_interrupt_event_block_content,
    invoke_route_runner,
    pytest,
    uuid4,
)


@pytest.mark.asyncio
async def test_build_consume_stream_callbacks_persists_outcome_content_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _DummySessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, _exc_type, _exc, _tb) -> None:
            return None

    async def fake_record_local_invoke_messages(
        db,
        **kwargs,
    ) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "conversation_id": kwargs["local_session_id"],
            "user_message_id": uuid4(),
            "agent_message_id": uuid4(),
        }

    async def fake_commit_safely(db):
        return None

    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages_by_local_session_id",
        fake_record_local_invoke_messages,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    client_user_message_id = str(uuid4())
    client_agent_message_id = str(uuid4())
    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="scheduled",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        user_message_id=client_user_message_id,
        agent_message_id=client_agent_message_id,
    )
    on_event, on_finalized = invoke_route_runner._build_consume_stream_callbacks(
        state=state,
        request=_build_persistence_request(transport="scheduled"),
    )

    await on_event(
        {
            "artifactUpdate": {
                "op": "append",
                "artifact": {
                    "parts": [{"text": "partial response"}],
                    "metadata": {
                        "shared": {
                            "stream": {
                                "blockType": "text",
                                "messageId": "msg-partial-1",
                                "eventId": "evt-partial-1",
                            }
                        }
                    },
                },
            }
        }
    )
    await on_finalized(
        StreamOutcome(
            success=False,
            finish_reason=StreamFinishReason.TIMEOUT_TOTAL,
            final_text="partial response",
            error_message="A2A stream total timeout after 60.0s",
            error_code="timeout",
            elapsed_seconds=60.0,
            idle_seconds=0.1,
            terminal_event_seen=False,
        )
    )

    assert captured["response_content"] == "partial response"
    assert captured["success"] is False
    response_metadata = captured["response_metadata"]
    assert isinstance(response_metadata, dict)
    stream_metadata = response_metadata["stream"]
    assert stream_metadata["schema_version"] == 1
    assert stream_metadata["finish_reason"] == "timeout_total"
    assert stream_metadata["error"]["message"] == "A2A stream total timeout after 60.0s"
    assert stream_metadata["error"]["error_code"] == "timeout"
    assert "message_blocks" not in response_metadata
    assert state.persisted_response_content == "partial response"
    assert state.persisted_error_code == "timeout"
    assert state.persisted_finish_reason == "timeout_total"
    assert captured["user_message_id"] == UUID(client_user_message_id)
    assert captured["agent_message_id"] == UUID(client_agent_message_id)


@pytest.mark.asyncio
async def test_build_consume_stream_callbacks_persists_interrupt_lifecycle_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_calls: list[tuple[str, object]] = []

    class _DummySession:
        async def scalar(self, *_args, **_kwargs):
            return object()

    class _DummySessionContext:
        async def __aenter__(self) -> _DummySession:
            return _DummySession()

        async def __aexit__(self, _exc_type, _exc, _tb) -> None:
            return None

    async def fake_append_agent_message_block_updates(_db, **kwargs) -> list[object]:
        captured_calls.append(("flush", kwargs))
        return [object()]

    async def fake_append_agent_message_block_update(_db, **kwargs) -> object:
        captured_calls.append(("interrupt", kwargs))
        return object()

    async def fake_commit_safely(_db):
        return None

    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "append_agent_message_block_updates",
        fake_append_agent_message_block_updates,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "append_agent_message_block_update",
        fake_append_agent_message_block_update,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    local_session_id = uuid4()
    agent_message_id = uuid4()
    state = invoke_route_runner._InvokeState(
        local_session_id=local_session_id,
        local_source="manual",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        message_refs={
            "user_message_id": str(uuid4()),
            "agent_message_id": str(agent_message_id),
        },
        next_event_seq=3,
        chunk_buffer=[
            {
                "seq": 2,
                "block_type": "text",
                "content": "partial",
                "op": "append",
                "is_finished": False,
                "event_id": "evt-partial",
                "source": "stream",
            }
        ],
        current_block_type="text",
    )
    on_event, _ = invoke_route_runner._build_consume_stream_callbacks(
        state=state,
        request=_build_persistence_request(transport="http_sse"),
    )

    await on_event(
        {
            "statusUpdate": {
                "status": {"state": "TASK_STATE_INPUT_REQUIRED"},
                "metadata": {
                    "shared": {
                        "interrupt": {
                            "requestId": "perm-1",
                            "type": "permission",
                            "phase": "asked",
                            "details": {
                                "permission": "read",
                                "patterns": ["/repo/.env"],
                            },
                        },
                    }
                },
            }
        }
    )

    assert captured_calls[0][0] == "flush"
    flushed_updates = captured_calls[0][1]
    assert isinstance(flushed_updates, dict)
    assert flushed_updates["agent_message_id"] == agent_message_id
    assert flushed_updates["updates"][0]["content"] == "partial"

    assert captured_calls[1][0] == "interrupt"
    interrupt_call = captured_calls[1][1]
    assert isinstance(interrupt_call, dict)
    assert interrupt_call["agent_message_id"] == agent_message_id
    assert interrupt_call["seq"] == 3
    assert interrupt_call["block_type"] == "interrupt_event"
    assert interrupt_call["append"] is False
    assert interrupt_call["is_finished"] is True
    assert interrupt_call["source"] == "interrupt_lifecycle"
    content, interrupt = deserialize_interrupt_event_block_content(
        interrupt_call["content"]
    )
    assert content == "Agent requested permission: read.\nTargets: /repo/.env"
    assert interrupt is not None
    assert interrupt["requestId"] == "perm-1"
    assert interrupt["type"] == "permission"
    assert interrupt["phase"] == "asked"
    assert interrupt["details"]["permission"] == "read"
    assert interrupt["details"]["patterns"] == ["/repo/.env"]
    assert interrupt["details"]["displayMessage"] is None
    assert interrupt["details"]["questions"] == []
    assert "permissions" not in interrupt["details"]
    assert "serverName" not in interrupt["details"]
    assert "mode" not in interrupt["details"]
    assert "requestedSchema" not in interrupt["details"]
    assert "url" not in interrupt["details"]
    assert "elicitationId" not in interrupt["details"]
    assert "meta" not in interrupt["details"]
    assert state.chunk_buffer == []
    assert state.persisted_block_count == 2
    assert state.next_event_seq == 4


@pytest.mark.asyncio
async def test_consume_stream_callbacks_bind_task_id_and_unregister_inflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_bind_inflight_task_id_report(
        *,
        user_id,
        conversation_id,
        token,
        task_id,
    ) -> BindInflightTaskReport:
        captured["bound_token"] = token
        captured["bound_task_id"] = task_id
        return BindInflightTaskReport(bound=True)

    async def fake_unregister_inflight_invoke(
        *,
        user_id,
        conversation_id,
        token,
    ) -> bool:
        captured["unregistered_token"] = token
        return True

    async def fake_persist_local_outcome(**_kwargs):
        return None

    async def fake_record_upstream_task_binding(**kwargs):
        captured["recorded_task_id"] = kwargs["task_id"]

    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "bind_inflight_task_id_report",
        fake_bind_inflight_task_id_report,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "unregister_inflight_invoke",
        fake_unregister_inflight_invoke,
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_persist_local_outcome",
        fake_persist_local_outcome,
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_record_upstream_task_binding",
        fake_record_upstream_task_binding,
    )

    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="manual",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        user_message_id=None,
        inflight_token="token-1",
    )
    on_event, on_finalized = invoke_route_runner._build_consume_stream_callbacks(
        state=state,
        request=_build_persistence_request(
            transport="http_json",
            stream_enabled=False,
        ),
    )

    await on_event({"task": {"id": "task-xyz"}})
    assert captured["bound_token"] == "token-1"
    assert captured["bound_task_id"] == "task-xyz"
    assert captured["recorded_task_id"] == "task-xyz"
    assert state.upstream_task_id == "task-xyz"

    await on_finalized(
        StreamOutcome(
            success=True,
            finish_reason=StreamFinishReason.SUCCESS,
            final_text="ok",
            error_message=None,
            error_code=None,
            elapsed_seconds=1.0,
            idle_seconds=0.1,
            terminal_event_seen=True,
        )
    )
    assert captured["unregistered_token"] == "token-1"
    assert state.inflight_token is None


@pytest.mark.asyncio
async def test_bind_inflight_task_if_needed_records_deferred_preempt_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded_events: list[dict[str, object]] = []
    preempt_event = {
        "reason": "invoke_interrupt",
        "status": "completed",
        "source": "user",
        "target_message_id": str(uuid4()),
        "replacement_user_message_id": str(uuid4()),
        "replacement_agent_message_id": str(uuid4()),
        "target_task_ids": ["task-xyz"],
        "failed_error_codes": [],
    }

    async def fake_bind_inflight_task_id_report(
        *,
        user_id,
        conversation_id,
        token,
        task_id,
    ) -> BindInflightTaskReport:
        return BindInflightTaskReport(bound=True, preempt_event=preempt_event)

    async def fake_record_preempt_history_event(
        *,
        state,
        user_id,
        event,
    ) -> None:
        recorded_events.append(dict(event))

    async def fake_record_upstream_task_binding(**_kwargs):
        return None

    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "bind_inflight_task_id_report",
        fake_bind_inflight_task_id_report,
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_record_preempt_history_event",
        fake_record_preempt_history_event,
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_record_upstream_task_binding",
        fake_record_upstream_task_binding,
    )

    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="manual",
        context_id=None,
        metadata={},
        stream_identity={"upstream_task_id": "task-xyz"},
        stream_usage={},
        inflight_token="token-1",
    )

    await invoke_route_runner._bind_inflight_task_if_needed(
        state=state,
        user_id=uuid4(),
    )

    assert state.upstream_task_id == "task-xyz"
    assert recorded_events == [preempt_event]


@pytest.mark.asyncio
async def test_persist_stream_block_update_rewrites_when_only_agent_message_id_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    agent_message_id = str(uuid4())

    class _DummySession:
        async def scalar(self, *_args, **_kwargs):
            return object()

    class _DummySessionContext:
        async def __aenter__(self) -> _DummySession:
            return _DummySession()

        async def __aexit__(self, _exc_type, _exc, _tb) -> None:
            return None

    async def fake_append_agent_message_block_updates(_db, **kwargs):
        captured.update(kwargs)
        return [object()]

    async def fake_commit_safely(_db):
        return None

    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "append_agent_message_block_updates",
        fake_append_agent_message_block_updates,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="manual",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        user_message_id=str(uuid4()),
        agent_message_id=agent_message_id,
        message_refs={
            "user_message_id": str(uuid4()),
            "agent_message_id": agent_message_id,
        },
        next_event_seq=1,
        persisted_block_count=0,
    )

    event_payload = {
        "artifactUpdate": {
            "op": "append",
            "lastChunk": True,
            "artifact": {
                "parts": [{"text": "stream"}],
                "metadata": {"shared": {"stream": {"blockType": "text"}}},
            },
        }
    }

    await invoke_route_runner._persist_stream_block_update(
        state=state,
        event_payload=event_payload,
        request=_build_persistence_request(transport="ws"),
    )

    assert event_payload["artifactUpdate"]["artifact"]["metadata"]["shared"][
        "stream"
    ] == {"blockType": "text"}
    local_stream_context = event_payload["__hub_local_stream"]
    assert local_stream_context["message_id"] == agent_message_id
    assert isinstance(local_stream_context.get("event_id"), str)
    assert local_stream_context["seq"] == 1
    updates = captured["updates"]
    assert isinstance(updates, list)
    assert len(updates) == 1
    assert updates[0]["content"] == "stream"


@pytest.mark.asyncio
async def test_persist_stream_block_update_inferrs_canonical_artifact_text_without_private_block_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    agent_message_id = str(uuid4())

    class _DummySession:
        async def scalar(self, *_args, **_kwargs):
            return object()

    class _DummySessionContext:
        async def __aenter__(self) -> _DummySession:
            return _DummySession()

        async def __aexit__(self, _exc_type, _exc, _tb) -> None:
            return None

    async def fake_append_agent_message_block_updates(_db, **kwargs):
        captured.update(kwargs)
        return [object()]

    async def fake_commit_safely(_db):
        return None

    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "append_agent_message_block_updates",
        fake_append_agent_message_block_updates,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="manual",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        user_message_id=str(uuid4()),
        agent_message_id=agent_message_id,
        message_refs={
            "user_message_id": str(uuid4()),
            "agent_message_id": agent_message_id,
        },
        next_event_seq=1,
        persisted_block_count=0,
    )

    event_payload = {
        "artifactUpdate": {
            "taskId": "task-raw-1",
            "append": True,
            "lastChunk": True,
            "artifact": {
                "artifactId": "task-raw-1:stream:text",
                "parts": [{"text": "Code"}],
            },
            "metadata": {
                "shared": {
                    "stream": {
                        "eventId": "stream:4",
                        "seq": 4,
                    }
                }
            },
        }
    }

    await invoke_route_runner._persist_stream_block_update(
        state=state,
        event_payload=event_payload,
        request=_build_persistence_request(transport="ws"),
    )

    assert event_payload["artifactUpdate"]["metadata"]["shared"]["stream"] == {
        "eventId": "stream:4",
        "seq": 4,
    }
    local_stream_context = event_payload["__hub_local_stream"]
    assert local_stream_context["message_id"] == agent_message_id
    assert local_stream_context["event_id"] == "stream:4"
    assert local_stream_context["seq"] == 1
    updates = captured["updates"]
    assert isinstance(updates, list)
    assert len(updates) == 1
    assert updates[0]["content"] == "Code"
    assert updates[0]["append"] is True


@pytest.mark.asyncio
async def test_persist_stream_block_update_consumes_and_persists_optional_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _DummySession:
        async def scalar(self, *_args, **_kwargs):
            return object()

    class _DummySessionContext:
        async def __aenter__(self) -> _DummySession:
            return _DummySession()

        async def __aexit__(self, _exc_type, _exc, _tb) -> None:
            return None

    async def fake_append_agent_message_block_updates(_db, **kwargs):
        captured.update(kwargs)
        return [object()]

    async def fake_commit_safely(_db):
        return None

    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "append_agent_message_block_updates",
        fake_append_agent_message_block_updates,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="manual",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        user_message_id=None,
        message_refs={
            "user_message_id": str(uuid4()),
            "agent_message_id": str(uuid4()),
        },
        next_event_seq=3,
        persisted_block_count=0,
    )

    event_payload = {
        "artifactUpdate": {
            "seq": 9,
            "op": "replace",
            "lastChunk": True,
            "artifact": {
                "parts": [{"text": "chunk-body"}],
                "metadata": {
                    "shared": {
                        "stream": {
                            "blockType": "text",
                            "messageId": "msg-opt",
                            "eventId": "evt-opt",
                        }
                    }
                },
            },
        }
    }

    await invoke_route_runner._persist_stream_block_update(
        state=state,
        event_payload=event_payload,
        request=_build_persistence_request(transport="http_json"),
    )

    updates = captured["updates"]
    assert isinstance(updates, list)
    assert len(updates) == 1
    assert updates[0]["seq"] == 3
    assert updates[0]["append"] is False
    assert updates[0]["is_finished"] is True
    assert state.next_event_seq == 4
    assert state.persisted_block_count == 1
    assert state.chunk_buffer == []
    assert event_payload["artifactUpdate"]["artifact"]["metadata"]["shared"][
        "stream"
    ] == {
        "blockType": "text",
        "messageId": "msg-opt",
        "eventId": "evt-opt",
    }
    local_stream_context = event_payload["__hub_local_stream"]
    assert local_stream_context["message_id"] == str(
        state.message_refs["agent_message_id"]
    )
    assert local_stream_context["event_id"] == "evt-opt"
    assert local_stream_context["seq"] == 3


@pytest.mark.asyncio
async def test_persist_stream_block_update_preserves_canonical_message_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _DummySession:
        async def scalar(self, *_args, **_kwargs):
            return object()

    class _DummySessionContext:
        async def __aenter__(self) -> _DummySession:
            return _DummySession()

        async def __aexit__(self, _exc_type, _exc, _tb) -> None:
            return None

    async def fake_append_agent_message_block_updates(_db, **kwargs):
        captured.update(kwargs)
        return [object()]

    async def fake_commit_safely(_db):
        return None

    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "append_agent_message_block_updates",
        fake_append_agent_message_block_updates,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    refs = {
        "user_message_id": str(uuid4()),
        "agent_message_id": str(uuid4()),
    }
    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="manual",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        user_message_id=None,
        message_refs=refs,
        next_event_seq=5,
        persisted_block_count=0,
    )

    event_payload = {
        "message": {
            "messageId": "msg-upstream-root",
            "role": "ROLE_AGENT",
            "parts": [{"text": "root text"}],
            "metadata": {"shared": {"stream": {"blockType": "text", "op": "replace"}}},
        }
    }

    await invoke_route_runner._persist_stream_block_update(
        state=state,
        event_payload=event_payload,
        request=_build_persistence_request(transport="http_sse"),
    )

    assert captured == {}
    assert len(state.chunk_buffer) == 1
    assert state.chunk_buffer[0]["content"] == "root text"
    assert state.chunk_buffer[0]["append"] is False
    assert "message" in event_payload
    assert event_payload["message"]["parts"] == [{"text": "root text"}]
    assert event_payload["message"]["metadata"]["shared"]["stream"] == {
        "blockType": "text",
        "op": "replace",
    }
    assert event_payload["__hub_local_stream"] == {
        "message_id": refs["agent_message_id"],
        "event_id": f"{refs['agent_message_id']}:5",
        "seq": 5,
        "block_id": "msg-upstream-root:primary_text",
        "lane_id": "primary_text",
        "op": "replace",
    }


@pytest.mark.asyncio
async def test_persist_stream_block_update_flushes_when_block_type_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flushed_batches: list[list[dict[str, object]]] = []

    class _DummySession:
        async def scalar(self, *_args, **_kwargs):
            return object()

    class _DummySessionContext:
        async def __aenter__(self) -> _DummySession:
            return _DummySession()

        async def __aexit__(self, _exc_type, _exc, _tb) -> None:
            return None

    async def fake_append_agent_message_block_updates(_db, **kwargs):
        updates = kwargs.get("updates") or []
        flushed_batches.append(list(updates))
        return [object() for _ in updates]

    async def fake_commit_safely(_db):
        return None

    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "append_agent_message_block_updates",
        fake_append_agent_message_block_updates,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="manual",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        message_refs={
            "user_message_id": str(uuid4()),
            "agent_message_id": str(uuid4()),
        },
        next_event_seq=1,
        persisted_block_count=0,
    )

    await invoke_route_runner._persist_stream_block_update(
        state=state,
        event_payload={
            "artifactUpdate": {
                "op": "append",
                "artifact": {
                    "parts": [{"text": "alpha"}],
                    "metadata": {
                        "shared": {
                            "stream": {
                                "blockType": "text",
                                "messageId": "msg-alpha",
                                "eventId": "evt-alpha",
                            }
                        }
                    },
                },
            }
        },
        request=_build_persistence_request(transport="http_json"),
    )
    assert flushed_batches == []
    assert len(state.chunk_buffer) == 1

    await invoke_route_runner._persist_stream_block_update(
        state=state,
        event_payload={
            "artifactUpdate": {
                "op": "append",
                "artifact": {
                    "parts": [{"text": "beta"}],
                    "metadata": {
                        "shared": {
                            "stream": {
                                "blockType": "reasoning",
                                "messageId": "msg-beta",
                                "eventId": "evt-beta",
                            }
                        }
                    },
                },
            }
        },
        request=_build_persistence_request(transport="http_json"),
    )

    assert len(flushed_batches) == 1
    assert flushed_batches[0][0]["block_type"] == "text"
    assert len(state.chunk_buffer) == 1
    assert state.chunk_buffer[0]["block_type"] == "reasoning"
    assert state.persisted_block_count == 1


@pytest.mark.asyncio
async def test_persist_stream_block_update_generates_local_event_id_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _DummySession:
        async def scalar(self, *_args, **_kwargs):
            return object()

    class _DummySessionContext:
        async def __aenter__(self) -> _DummySession:
            return _DummySession()

        async def __aexit__(self, _exc_type, _exc, _tb) -> None:
            return None

    async def fake_append_agent_message_block_updates(_db, **kwargs):
        captured.update(kwargs)
        return [object()]

    async def fake_commit_safely(_db):
        return None

    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "append_agent_message_block_updates",
        fake_append_agent_message_block_updates,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    refs = {
        "user_message_id": str(uuid4()),
        "agent_message_id": str(uuid4()),
    }
    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="manual",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        user_message_id=None,
        message_refs=refs,
        next_event_seq=4,
        persisted_block_count=0,
    )

    event_payload = {
        "artifactUpdate": {
            "op": "append",
            "lastChunk": True,
            "artifact": {
                "parts": [{"text": "chunk-body"}],
                "metadata": {
                    "shared": {
                        "stream": {
                            "blockType": "text",
                        }
                    }
                },
            },
        }
    }

    await invoke_route_runner._persist_stream_block_update(
        state=state,
        event_payload=event_payload,
        request=_build_persistence_request(transport="http_json"),
    )

    expected_event_id = f"{refs['agent_message_id']}:4"
    updates = captured["updates"]
    assert isinstance(updates, list)
    assert len(updates) == 1
    assert updates[0]["event_id"] == expected_event_id
    assert updates[0]["seq"] == 4
    assert event_payload["artifactUpdate"]["artifact"]["metadata"]["shared"][
        "stream"
    ] == {
        "blockType": "text",
    }
    assert event_payload["__hub_local_stream"] == {
        "message_id": refs["agent_message_id"],
        "event_id": expected_event_id,
        "seq": 4,
        "block_id": "stream:primary_text",
        "lane_id": "primary_text",
        "op": "append",
    }
    assert state.next_event_seq == 5


@pytest.mark.asyncio
async def test_on_finalized_flushes_remaining_stream_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_flushes: list[list[dict[str, object]]] = []
    captured_outcome: dict[str, object] = {}

    class _DummySession:
        async def scalar(self, *_args, **_kwargs):
            return object()

    class _DummySessionContext:
        async def __aenter__(self) -> _DummySession:
            return _DummySession()

        async def __aexit__(self, _exc_type, _exc, _tb) -> None:
            return None

    async def fake_append_agent_message_block_updates(_db, **kwargs):
        updates = kwargs.get("updates") or []
        captured_flushes.append(list(updates))
        return [object() for _ in updates]

    async def fake_has_agent_message_blocks(_db, **_kwargs) -> bool:
        return True

    async def fake_record_local_invoke_messages(_db, **kwargs) -> dict[str, object]:
        captured_outcome.update(kwargs)
        return {
            "conversation_id": kwargs["local_session_id"],
            "user_message_id": uuid4(),
            "agent_message_id": uuid4(),
        }

    async def fake_commit_safely(_db):
        return None

    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "append_agent_message_block_updates",
        fake_append_agent_message_block_updates,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "has_agent_message_blocks",
        fake_has_agent_message_blocks,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages_by_local_session_id",
        fake_record_local_invoke_messages,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="manual",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        message_refs={
            "conversation_id": uuid4(),
            "user_message_id": uuid4(),
            "agent_message_id": uuid4(),
        },
        next_event_seq=5,
        persisted_block_count=0,
    )

    on_event, on_finalized = invoke_route_runner._build_consume_stream_callbacks(
        state=state,
        request=_build_persistence_request(transport="http_sse"),
    )

    await on_event(
        {
            "artifactUpdate": {
                "op": "append",
                "artifact": {
                    "parts": [{"text": "partial"}],
                    "metadata": {
                        "shared": {
                            "stream": {
                                "blockType": "text",
                                "messageId": "msg-partial",
                                "eventId": "evt-partial",
                            }
                        }
                    },
                },
            }
        }
    )
    assert len(state.chunk_buffer) == 1

    persisted_ack = await on_finalized(
        StreamOutcome(
            success=True,
            finish_reason=StreamFinishReason.SUCCESS,
            final_text="partial",
            error_message=None,
            error_code=None,
            elapsed_seconds=1.0,
            idle_seconds=0.1,
            terminal_event_seen=True,
        )
    )

    assert len(captured_flushes) == 1
    assert captured_flushes[0][0]["content"] == "partial"
    assert state.chunk_buffer == []
    assert state.persisted_block_count == 1
    assert captured_outcome["response_content"] == "partial"
    assert persisted_ack == {
        "statusUpdate": {
            "status": {"state": "TASK_STATE_COMPLETED"},
            "metadata": {
                "shared": {
                    "stream": {
                        "messageId": str(state.message_refs["agent_message_id"]),
                        "completionPhase": "persisted",
                        "finishReason": "success",
                        "success": True,
                    }
                }
            },
        }
    }


@pytest.mark.asyncio
async def test_persist_local_outcome_synthesizes_final_chunk_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_chunk: dict[str, object] = {}
    captured_outcome: dict[str, object] = {}

    class _DummySession:
        async def scalar(self, *_args, **_kwargs):
            return object()

    class _DummySessionContext:
        async def __aenter__(self) -> _DummySession:
            return _DummySession()

        async def __aexit__(self, _exc_type, _exc, _tb) -> None:
            return None

    async def fake_has_agent_message_blocks(_db, **_kwargs) -> bool:
        return False

    async def fake_append_agent_message_block_update(_db, **kwargs) -> object:
        captured_chunk.update(kwargs)
        return object()

    async def fake_record_local_invoke_messages(_db, **kwargs) -> dict[str, object]:
        captured_outcome.update(kwargs)
        return {
            "conversation_id": kwargs["local_session_id"],
            "user_message_id": kwargs["idempotency_key"] and uuid4(),
            "agent_message_id": uuid4(),
        }

    async def fake_commit_safely(_db):
        return None

    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "has_agent_message_blocks",
        fake_has_agent_message_blocks,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "append_agent_message_block_update",
        fake_append_agent_message_block_update,
    )
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages_by_local_session_id",
        fake_record_local_invoke_messages,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)

    state = invoke_route_runner._InvokeState(
        local_session_id=uuid4(),
        local_source="manual",
        context_id=None,
        metadata={},
        stream_identity={},
        stream_usage={},
        user_message_id=None,
        message_refs={
            "conversation_id": uuid4(),
            "user_message_id": uuid4(),
            "agent_message_id": uuid4(),
        },
        next_event_seq=1,
        persisted_block_count=0,
    )

    await invoke_route_runner._persist_local_outcome(
        state=state,
        outcome=StreamOutcome(
            success=True,
            finish_reason=StreamFinishReason.SUCCESS,
            final_text="non-stream final",
            error_message=None,
            error_code=None,
            elapsed_seconds=1.0,
            idle_seconds=0.1,
            terminal_event_seen=True,
        ),
        request=_build_persistence_request(
            transport="http_json",
            stream_enabled=False,
        ),
    )

    assert captured_chunk["seq"] == 1
    assert captured_chunk["block_type"] == "text"
    assert captured_chunk["content"] == "non-stream final"
    assert captured_chunk["append"] is False
    assert captured_chunk["is_finished"] is True
    assert captured_chunk["source"] == "finalize_snapshot"
    assert captured_outcome["response_content"] == "non-stream final"
    assert state.persisted_block_count == 1
    assert state.next_event_seq == 2


@pytest.mark.asyncio
async def test_run_http_invoke_stream_uses_finalized_callback_for_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _DummySessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, _exc_type, _exc, _tb) -> None:
            return None

    async def fake_prepare_state(**kwargs):
        return invoke_route_runner._InvokeState(
            local_session_id=uuid4(),
            local_source="manual",
            context_id=None,
            metadata={"run_id": "run-1"},
            stream_identity={},
            stream_usage={},
            user_message_id=None,
        )

    async def fake_record_local_invoke_messages(
        db,
        **kwargs,
    ) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "conversation_id": kwargs["local_session_id"],
            "user_message_id": uuid4(),
            "agent_message_id": uuid4(),
        }

    async def fake_commit_safely(db):
        return None

    def fake_stream_sse(**kwargs):
        finalized = kwargs.get("on_finalized")
        assert callable(finalized)

        async def _iterator():
            await finalized(
                StreamOutcome(
                    success=False,
                    finish_reason=StreamFinishReason.TIMEOUT_TOTAL,
                    final_text="partial sse",
                    error_message="timeout",
                    error_code="timeout",
                    elapsed_seconds=60.0,
                    idle_seconds=1.0,
                    terminal_event_seen=False,
                )
            )
            yield "event: stream_end\ndata: {}\n\n"

        return StreamingResponse(_iterator(), media_type="text/event-stream")

    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages_by_local_session_id",
        fake_record_local_invoke_messages,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)
    monkeypatch.setattr(
        invoke_route_runner.a2a_invoke_streaming_runtime,
        "stream_sse",
        fake_stream_sse,
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )

    payload = A2AAgentInvokeRequest.model_validate(
        {"query": "hello", "conversationId": str(uuid4()), "metadata": {}}
    )
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )

    response = await invoke_route_runner.run_http_invoke(
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        stream=True,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={},
    )

    assert isinstance(response, StreamingResponse)
    await _consume_stream(response)
    assert captured["response_content"] == "partial sse"
    stream_metadata = captured["response_metadata"]["stream"]
    assert stream_metadata["finish_reason"] == "timeout_total"


@pytest.mark.asyncio
async def test_run_ws_invoke_uses_finalized_callback_for_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _DummySessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, _exc_type, _exc, _tb) -> None:
            return None

    async def fake_prepare_state(**kwargs):
        return invoke_route_runner._InvokeState(
            local_session_id=uuid4(),
            local_source="manual",
            context_id=None,
            metadata={"run_id": "run-2"},
            stream_identity={},
            stream_usage={},
            user_message_id=None,
        )

    async def fake_record_local_invoke_messages(
        db,
        **kwargs,
    ) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "conversation_id": kwargs["local_session_id"],
            "user_message_id": uuid4(),
            "agent_message_id": uuid4(),
        }

    async def fake_commit_safely(db):
        return None

    async def fake_stream_ws(**kwargs):
        finalized = kwargs.get("on_finalized")
        assert callable(finalized)
        await finalized(
            StreamOutcome(
                success=True,
                finish_reason=StreamFinishReason.SUCCESS,
                final_text="ws final",
                error_message=None,
                error_code=None,
                elapsed_seconds=1.0,
                idle_seconds=0.1,
                terminal_event_seen=True,
            )
        )

    monkeypatch.setattr(invoke_route_runner, "_prepare_state", fake_prepare_state)
    monkeypatch.setattr(
        invoke_route_runner.session_hub_service,
        "record_local_invoke_messages_by_local_session_id",
        fake_record_local_invoke_messages,
    )
    monkeypatch.setattr(invoke_route_runner, "commit_safely", fake_commit_safely)
    monkeypatch.setattr(
        invoke_route_runner.a2a_invoke_streaming_runtime,
        "stream_ws",
        fake_stream_ws,
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
    )

    payload = A2AAgentInvokeRequest.model_validate(
        {"query": "hello", "conversationId": str(uuid4()), "metadata": {}}
    )
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
    )

    await invoke_route_runner.run_ws_invoke(
        websocket=_NoopWebSocket(),
        gateway=object(),
        runtime=runtime,
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
        validate_message=lambda _: [],
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        log_extra={},
    )

    assert captured["response_content"] == "ws final"
    assert captured["response_metadata"]["stream"]["finish_reason"] == "success"
