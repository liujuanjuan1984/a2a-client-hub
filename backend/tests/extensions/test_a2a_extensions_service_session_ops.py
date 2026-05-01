from __future__ import annotations

from tests.extensions.a2a_extensions_service_support import (
    OPENCODE_WIRE_CONTRACT_URI,
    SHARED_SESSION_QUERY_URI,
    A2AExtensionsService,
    Any,
    DeclaredMethodCapabilitySnapshot,
    DeclaredMethodCollectionCapabilitySnapshot,
    ExtensionCallResult,
    ResolvedConditionalMethodAvailability,
    ResolvedExtension,
    SimpleNamespace,
    _binding_snapshot,
    _capability_snapshot,
    _resolved_extension,
    _session_query_snapshot,
    _wire_contract_extension_fixture,
    _wire_contract_snapshot,
    pytest,
)


@pytest.mark.asyncio
async def test_prompt_session_async_forwards_request_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(supports_offset=True)
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "prompt_async"
        assert kwargs["params"]["session_id"] == "ses_123"
        assert kwargs["params"]["request"] == {
            "parts": [{"type": "text", "text": "continue"}],
            "noReply": True,
        }
        assert kwargs["params"]["metadata"] == {
            "shared": {
                "session": {
                    "id": "ses_123",
                    "provider": "opencode",
                }
            }
        }
        assert kwargs["normalize_envelope"] is False
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "session_id": "ses_123"},
            meta={"session_id": "ses_123"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _fake_invoke)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.prompt_session_async(
        runtime=runtime,
        session_id="ses_123",
        request_payload={
            "parts": [{"type": "text", "text": "continue"}],
            "noReply": True,
        },
        metadata={"provider": "opencode", "externalSessionId": "ses_123"},
    )

    assert result.success is True
    assert result.result == {"ok": True, "session_id": "ses_123"}


@pytest.mark.asyncio
async def test_prompt_session_async_returns_method_not_supported_if_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _resolved_extension()
    ext = ResolvedExtension(
        uri=ext.uri,
        required=ext.required,
        provider=ext.provider,
        jsonrpc=ext.jsonrpc,
        methods={
            "list_sessions": ext.methods["list_sessions"],
            "get_session_messages": ext.methods["get_session_messages"],
            "prompt_async": None,
        },
        pagination=ext.pagination,
        business_code_map=ext.business_code_map,
        result_envelope=ext.result_envelope,
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._support, "_call_with_retry", _unexpected_remote_call)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.prompt_session_async(
        runtime=runtime,
        session_id="ses_123",
        request_payload={"parts": [{"type": "text", "text": "continue"}]},
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta == {
        "extension_uri": SHARED_SESSION_QUERY_URI,
        "session_query_negotiation_mode": "declared_contract",
        "session_query_compatibility_hints_applied": False,
    }


@pytest.mark.asyncio
async def test_prompt_session_async_returns_method_disabled_when_wire_contract_marks_method_conditional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _resolved_extension()
    wire_contract = _wire_contract_extension_fixture(
        all_jsonrpc_methods=(
            "shared.sessions.list",
            "shared.sessions.messages.list",
            "shared.sessions.command",
        ),
        conditional_methods={
            "shared.sessions.prompt_async": ResolvedConditionalMethodAvailability(
                reason="disabled_by_configuration",
                toggle="A2A_ENABLE_SESSION_PROMPT_ASYNC",
            )
        },
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
            wire_contract=_wire_contract_snapshot(
                status="supported",
                ext=wire_contract,
            ),
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be rejected during wire-contract preflight")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(
        service._session_extensions, "invoke_method", _unexpected_remote_call
    )

    result = await service.prompt_session_async(
        runtime=runtime,
        session_id="ses_123",
        request_payload={"parts": [{"type": "text", "text": "continue"}]},
    )

    assert result.success is False
    assert result.error_code == "method_disabled"
    assert result.source == "wire_contract"
    assert result.upstream_error == {
        "message": "Method shared.sessions.prompt_async is disabled by upstream deployment",
        "type": "METHOD_DISABLED",
        "method": "shared.sessions.prompt_async",
        "reason": "disabled_by_configuration",
        "toggle": "A2A_ENABLE_SESSION_PROMPT_ASYNC",
    }
    assert result.meta == {
        "extension_uri": SHARED_SESSION_QUERY_URI,
        "wire_contract_uri": OPENCODE_WIRE_CONTRACT_URI,
        "wire_contract_preflight": "conditionally_available",
        "method_name": "shared.sessions.prompt_async",
    }


@pytest.mark.asyncio
async def test_prompt_session_async_requires_non_empty_parts() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError):
        await service.prompt_session_async(
            runtime=runtime,
            session_id="ses_123",
            request_payload={"parts": []},
        )


@pytest.mark.asyncio
async def test_prompt_session_async_rejects_non_object_metadata() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError, match="metadata must be an object"):
        await service.prompt_session_async(
            runtime=runtime,
            session_id="ses_123",
            request_payload={"parts": [{"type": "text", "text": "continue"}]},
            metadata=[],
        )


@pytest.mark.asyncio
async def test_append_session_control_prefers_codex_turn_steer_when_stream_identity_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _resolved_extension()
    codex_turns = DeclaredMethodCollectionCapabilitySnapshot(
        declared=True,
        consumed_by_hub=True,
        status="supported",
        methods={
            "steer": DeclaredMethodCapabilitySnapshot(
                declared=True,
                consumed_by_hub=True,
                method="codex.turns.steer",
                availability="always",
            )
        },
        jsonrpc_url="https://example.com/jsonrpc",
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
            codex_turns=codex_turns,
            wire_contract=_wire_contract_snapshot(
                status="supported",
                ext=_wire_contract_extension_fixture(
                    all_jsonrpc_methods=("codex.turns.steer",),
                ),
            ),
        )

    async def _unexpected_prompt_async(**_kwargs):
        raise AssertionError("prompt_async should not be used when steer is available")

    async def _fake_jsonrpc_call(**kwargs):
        assert kwargs["method_name"] == "codex.turns.steer"
        assert kwargs["params"] == {
            "thread_id": "thread-1",
            "expected_turn_id": "turn-1",
            "request": {
                "parts": [{"type": "text", "text": "continue"}],
            },
        }
        assert kwargs["requested_extensions"] == ["urn:codex-a2a:codex-turn-control/v1"]
        return SimpleNamespace(ok=True, result={"ok": True, "turn_id": "turn-2"})

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(
        service._session_extensions,
        "prompt_session_async",
        _unexpected_prompt_async,
    )
    monkeypatch.setattr(
        service._support,
        "perform_jsonrpc_call",
        _fake_jsonrpc_call,
    )

    result = await service.append_session_control(
        runtime=runtime,
        session_id="ses_123",
        request_payload={
            "parts": [{"type": "text", "text": "continue"}],
            "messageID": "msg-1",
        },
        metadata={
            "shared": {
                "stream": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                }
            }
        },
    )

    assert result.success is True
    assert result.result == {
        "ok": True,
        "session_id": "ses_123",
        "thread_id": "thread-1",
        "turn_id": "turn-2",
    }


@pytest.mark.asyncio
async def test_append_session_control_falls_back_to_prompt_async_without_stream_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _resolved_extension()
    codex_turns = DeclaredMethodCollectionCapabilitySnapshot(
        declared=True,
        consumed_by_hub=True,
        status="supported",
        methods={
            "steer": DeclaredMethodCapabilitySnapshot(
                declared=True,
                consumed_by_hub=True,
                method="codex.turns.steer",
                availability="always",
            )
        },
        jsonrpc_url="https://example.com/jsonrpc",
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
            codex_turns=codex_turns,
        )

    async def _fake_prompt_async(**kwargs):
        assert kwargs["session_id"] == "ses_123"
        assert kwargs["request_payload"] == {
            "parts": [{"type": "text", "text": "continue"}],
            "messageID": "msg-1",
        }
        assert kwargs["metadata"] == {"locale": "en"}
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "session_id": "ses_123"},
            meta={},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(
        service._session_extensions,
        "prompt_session_async",
        _fake_prompt_async,
    )

    result = await service.append_session_control(
        runtime=runtime,
        session_id="ses_123",
        request_payload={
            "parts": [{"type": "text", "text": "continue"}],
            "messageID": "msg-1",
        },
        metadata={"locale": "en"},
    )

    assert result.success is True
    assert result.result == {"ok": True, "session_id": "ses_123"}


@pytest.mark.asyncio
async def test_append_session_control_strips_shared_metadata_before_prompt_async(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _resolved_extension()

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
        )

    async def _fake_prompt_async(**kwargs):
        assert kwargs["session_id"] == "ses_123"
        assert kwargs["request_payload"] == {
            "parts": [{"type": "text", "text": "continue"}],
            "messageID": "msg-1",
        }
        assert kwargs["metadata"] == {"locale": "en"}
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "session_id": "ses_123"},
            meta={},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(
        service._session_extensions,
        "prompt_session_async",
        _fake_prompt_async,
    )

    result = await service.append_session_control(
        runtime=runtime,
        session_id="ses_123",
        request_payload={
            "parts": [{"type": "text", "text": "continue"}],
            "messageID": "msg-1",
        },
        metadata={
            "locale": "en",
            "shared": {
                "stream": {
                    "thread_id": "thread-1",
                    "turn_id": "turn-1",
                },
                "model": {
                    "providerID": "openai",
                    "modelID": "gpt-5.4",
                },
            },
        },
    )

    assert result.success is True
    assert result.result == {"ok": True, "session_id": "ses_123"}


@pytest.mark.asyncio
async def test_command_session_forwards_request_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(supports_offset=True)
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "command"
        assert kwargs["params"]["session_id"] == "ses_123"
        assert kwargs["params"]["request"] == {
            "command": "/review",
            "arguments": "--quick",
            "parts": [{"type": "text", "text": "Focus on tests"}],
        }
        assert kwargs["params"]["metadata"] == {
            "shared": {
                "session": {
                    "id": "ses_123",
                    "provider": "opencode",
                }
            }
        }
        assert kwargs["normalize_envelope"] is False
        return ExtensionCallResult(
            success=True,
            result={"item": {"kind": "message", "messageId": "msg-cmd-1"}},
            meta={"session_id": "ses_123"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _fake_invoke)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.command_session(
        runtime=runtime,
        session_id="ses_123",
        request_payload={
            "command": "/review",
            "arguments": "--quick",
            "parts": [{"type": "text", "text": "Focus on tests"}],
        },
        metadata={"provider": "opencode", "externalSessionId": "ses_123"},
    )

    assert result.success is True
    assert result.result == {"item": {"kind": "message", "messageId": "msg-cmd-1"}}


@pytest.mark.asyncio
async def test_command_session_returns_method_not_supported_if_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _resolved_extension()
    ext = ResolvedExtension(
        uri=ext.uri,
        required=ext.required,
        provider=ext.provider,
        jsonrpc=ext.jsonrpc,
        methods={
            "list_sessions": ext.methods["list_sessions"],
            "get_session_messages": ext.methods["get_session_messages"],
            "prompt_async": ext.methods["prompt_async"],
            "command": None,
            "shell": ext.methods["shell"],
        },
        pagination=ext.pagination,
        business_code_map=ext.business_code_map,
        result_envelope=ext.result_envelope,
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._support, "_call_with_retry", _unexpected_remote_call)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.command_session(
        runtime=runtime,
        session_id="ses_123",
        request_payload={"command": "/review", "arguments": "--quick"},
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta == {
        "extension_uri": SHARED_SESSION_QUERY_URI,
        "session_query_negotiation_mode": "declared_contract",
        "session_query_compatibility_hints_applied": False,
    }


@pytest.mark.asyncio
async def test_command_session_returns_method_not_supported_when_wire_contract_disallows_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _resolved_extension()
    wire_contract = _wire_contract_extension_fixture(
        all_jsonrpc_methods=(
            "shared.sessions.list",
            "shared.sessions.messages.list",
            "shared.sessions.prompt_async",
        ),
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
            wire_contract=_wire_contract_snapshot(
                status="supported",
                ext=wire_contract,
            ),
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be rejected during wire-contract preflight")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(
        service._session_extensions, "invoke_method", _unexpected_remote_call
    )

    result = await service.command_session(
        runtime=runtime,
        session_id="ses_123",
        request_payload={"command": "/review", "arguments": "--quick"},
    )

    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.source == "wire_contract"
    assert result.jsonrpc_code == -32601
    assert result.upstream_error == {
        "message": "Unsupported method: shared.sessions.command",
        "type": "METHOD_NOT_SUPPORTED",
        "method": "shared.sessions.command",
        "supported_methods": [
            "shared.sessions.list",
            "shared.sessions.messages.list",
            "shared.sessions.prompt_async",
        ],
        "protocol_version": "0.3.0",
    }
    assert result.meta == {
        "extension_uri": SHARED_SESSION_QUERY_URI,
        "wire_contract_uri": OPENCODE_WIRE_CONTRACT_URI,
        "wire_contract_preflight": "unsupported_method",
        "method_name": "shared.sessions.command",
    }


@pytest.mark.asyncio
async def test_command_session_requires_non_empty_command() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError, match="request.command must be a non-empty string"):
        await service.command_session(
            runtime=runtime,
            session_id="ses_123",
            request_payload={"command": "", "arguments": "--quick"},
        )


@pytest.mark.asyncio
async def test_command_session_rejects_non_string_arguments() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError, match="request.arguments must be a string"):
        await service.command_session(
            runtime=runtime,
            session_id="ses_123",
            request_payload={"command": "/review", "arguments": []},
        )


@pytest.mark.asyncio
async def test_command_session_allows_missing_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(supports_offset=True)
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "command"
        assert kwargs["params"]["request"] == {
            "command": "/status",
        }
        return ExtensionCallResult(
            success=True,
            result={"item": {"kind": "message", "messageId": "msg-cmd-status-2"}},
            meta={"session_id": "ses_123"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _fake_invoke)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.command_session(
        runtime=runtime,
        session_id="ses_123",
        request_payload={
            "command": "/status",
        },
    )

    assert result.success is True
    assert result.result == {
        "item": {"kind": "message", "messageId": "msg-cmd-status-2"}
    }


@pytest.mark.asyncio
async def test_command_session_allows_empty_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(supports_offset=True)
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            session_binding=_binding_snapshot(status="unsupported"),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "command"
        assert kwargs["params"]["request"] == {
            "command": "/status",
            "arguments": "",
        }
        return ExtensionCallResult(
            success=True,
            result={"item": {"kind": "message", "messageId": "msg-cmd-status-1"}},
            meta={"session_id": "ses_123"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._session_extensions, "invoke_method", _fake_invoke)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )

    result = await service.command_session(
        runtime=runtime,
        session_id="ses_123",
        request_payload={
            "command": "/status",
            "arguments": "",
        },
    )

    assert result.success is True
    assert result.result == {
        "item": {"kind": "message", "messageId": "msg-cmd-status-1"}
    }


@pytest.mark.asyncio
async def test_command_session_rejects_non_object_metadata() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError, match="metadata must be an object"):
        await service.command_session(
            runtime=runtime,
            session_id="ses_123",
            request_payload={"command": "/review", "arguments": "--quick"},
            metadata=[],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service_method", "delegate_name", "call_kwargs", "delegate_result"),
    [
        (
            "get_session",
            "get_session",
            {"session_id": "ses_123", "include_raw": True},
            {
                "item": {"id": "ses_123"},
                "raw": {"id": "ses_123", "provider": "opencode"},
            },
        ),
        (
            "get_session_children",
            "get_session_children",
            {"session_id": "ses_123", "include_raw": True},
            {"items": [{"id": "ses-child-1"}], "raw": [{"id": "ses-child-1"}]},
        ),
        (
            "get_session_todo",
            "get_session_todo",
            {"session_id": "ses_123"},
            {"items": [{"id": "todo-1"}]},
        ),
        (
            "get_session_diff",
            "get_session_diff",
            {"session_id": "ses_123", "message_id": "msg-9", "include_raw": True},
            {
                "items": [{"path": "README.md"}],
                "raw": [{"path": "README.md", "provider": "opencode"}],
            },
        ),
        (
            "get_session_message",
            "get_session_message",
            {"session_id": "ses_123", "message_id": "msg-9"},
            {"item": {"id": "msg-9", "text": "hello"}},
        ),
        (
            "fork_session",
            "fork_session",
            {
                "session_id": "ses_123",
                "request_payload": {"messageID": "msg-1"},
                "metadata": {"provider": "opencode"},
            },
            {"item": {"id": "ses_456", "parentId": "ses_123"}},
        ),
        (
            "share_session",
            "share_session",
            {"session_id": "ses_123", "metadata": {"provider": "opencode"}},
            {"item": {"id": "ses_123", "shared": True}},
        ),
        (
            "unshare_session",
            "unshare_session",
            {"session_id": "ses_123"},
            {"item": {"id": "ses_123", "shared": False}},
        ),
        (
            "summarize_session",
            "summarize_session",
            {
                "session_id": "ses_123",
                "request_payload": {"providerID": "openai", "auto": True},
            },
            {"ok": True, "sessionId": "ses_123"},
        ),
        (
            "revert_session",
            "revert_session",
            {
                "session_id": "ses_123",
                "request_payload": {"messageID": "msg-1", "partID": "part-2"},
            },
            {"item": {"id": "ses_123", "revertedTo": "msg-1"}},
        ),
        (
            "unrevert_session",
            "unrevert_session",
            {"session_id": "ses_123"},
            {"item": {"id": "ses_123", "reverted": False}},
        ),
    ],
)
async def test_extended_session_management_methods_delegate_to_session_service(
    monkeypatch: pytest.MonkeyPatch,
    service_method: str,
    delegate_name: str,
    call_kwargs: dict[str, Any],
    delegate_result: dict[str, Any],
) -> None:
    service = A2AExtensionsService()
    ext = _resolved_extension(supports_offset=True)
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    captured: dict[str, Any] = {}

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            wire_contract=_wire_contract_snapshot(
                status="supported",
                ext=_wire_contract_extension_fixture(),
            ),
        )

    async def _fake_delegate(**kwargs):
        captured.update(kwargs)
        return ExtensionCallResult(success=True, result=delegate_result, meta={})

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._session_extensions, delegate_name, _fake_delegate)

    result = await getattr(service, service_method)(runtime=runtime, **call_kwargs)

    assert result.success is True
    assert result.result == delegate_result
    assert captured["ext"] is ext
    assert captured["runtime_hints"] == {
        "session_query_negotiation_mode": "declared_contract",
        "session_query_compatibility_hints_applied": False,
    }


@pytest.mark.asyncio
async def test_get_session_returns_method_not_supported_when_wire_contract_disallows_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _resolved_extension()
    wire_contract = _wire_contract_extension_fixture(
        all_jsonrpc_methods=(
            "shared.sessions.list",
            "shared.sessions.messages.list",
            "shared.sessions.prompt_async",
            "shared.sessions.command",
        ),
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(ext),
            wire_contract=_wire_contract_snapshot(
                status="supported",
                ext=wire_contract,
            ),
        )

    async def _unexpected_call(**_kwargs):
        raise AssertionError("method should be rejected during wire-contract preflight")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._session_extensions, "get_session", _unexpected_call)

    result = await service.get_session(runtime=runtime, session_id="ses_123")

    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.source == "wire_contract"
    assert result.meta == {
        "extension_uri": SHARED_SESSION_QUERY_URI,
        "wire_contract_uri": OPENCODE_WIRE_CONTRACT_URI,
        "wire_contract_preflight": "unsupported_method",
        "method_name": "shared.sessions.get",
    }


@pytest.mark.asyncio
async def test_revert_session_requires_request_message_id() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    with pytest.raises(
        ValueError, match="request.messageID must be a non-empty string"
    ):
        await service.revert_session(
            runtime=runtime,
            session_id="ses_123",
            request_payload={"partID": "part-1"},
        )
