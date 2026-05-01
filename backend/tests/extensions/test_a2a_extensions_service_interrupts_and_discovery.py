from __future__ import annotations

from tests.extensions.a2a_extensions_service_support import (
    INTERRUPT_RECOVERY_URI,
    OPENCODE_WIRE_CONTRACT_URI,
    PROVIDER_DISCOVERY_URI,
    SHARED_INTERRUPT_CALLBACK_URI,
    SHARED_SESSION_QUERY_URI,
    A2AExtensionsService,
    DeclaredMethodCapabilitySnapshot,
    DeclaredMethodCollectionCapabilitySnapshot,
    ExtensionCallResult,
    JsonRpcInterface,
    ResolvedInterruptCallbackExtension,
    ResolvedInterruptRecoveryExtension,
    SimpleNamespace,
    _capability_snapshot,
    _compatibility_profile_snapshot,
    _interrupt_extension_fixture,
    _interrupt_recovery_extension_fixture,
    _interrupt_recovery_snapshot,
    _interrupt_snapshot,
    _provider_discovery_extension_fixture,
    _provider_discovery_snapshot,
    _resolved_extension,
    _session_query_snapshot,
    _wire_contract_extension_fixture,
    _wire_contract_snapshot,
    pytest,
)


@pytest.mark.asyncio
async def test_reply_permission_interrupt_uses_request_id_and_reply_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = ResolvedInterruptCallbackExtension(
        uri=SHARED_INTERRUPT_CALLBACK_URI,
        required=False,
        provider_key="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={"reply_permission": "shared.permission.reply"},
        business_code_map={-32004: "interrupt_request_not_found"},
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "reply_permission"
        assert kwargs["jsonrpc_url"] == "https://example.com/jsonrpc"
        assert kwargs["params"] == {"request_id": "perm-1", "reply": "once"}
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "request_id": "perm-1"},
            meta={"request_id": "perm-1"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._interrupt_extensions, "invoke_method", _fake_invoke)

    result = await service.reply_permission_interrupt(
        runtime=runtime,
        request_id="perm-1",
        reply="once",
    )
    assert result.success is True
    assert result.result == {"ok": True, "request_id": "perm-1"}


@pytest.mark.asyncio
async def test_reply_permission_interrupt_rejects_invalid_reply_value() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError):
        await service.reply_permission_interrupt(
            runtime=runtime,
            request_id="perm-1",
            reply="allow",
        )


@pytest.mark.asyncio
async def test_reply_permission_interrupt_forwards_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = ResolvedInterruptCallbackExtension(
        uri=SHARED_INTERRUPT_CALLBACK_URI,
        required=False,
        provider_key="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={"reply_permission": "shared.permission.reply"},
        business_code_map={-32004: "interrupt_request_not_found"},
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "reply_permission"
        assert kwargs["jsonrpc_url"] == "https://example.com/jsonrpc"
        assert kwargs["params"] == {
            "request_id": "perm-1",
            "reply": "once",
            "metadata": {"provider": "opencode", "requestScope": "shared"},
        }
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "request_id": "perm-1"},
            meta={"request_id": "perm-1"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._interrupt_extensions, "invoke_method", _fake_invoke)

    result = await service.reply_permission_interrupt(
        runtime=runtime,
        request_id="perm-1",
        reply="once",
        metadata={"provider": "opencode", "requestScope": "shared"},
    )
    assert result.success is True


@pytest.mark.asyncio
async def test_reply_permission_interrupt_rejects_non_object_metadata() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError, match="metadata must be an object"):
        await service.reply_permission_interrupt(
            runtime=runtime,
            request_id="perm-1",
            reply="once",
            metadata=[],
        )


@pytest.mark.asyncio
async def test_reject_question_interrupt_uses_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = ResolvedInterruptCallbackExtension(
        uri=SHARED_INTERRUPT_CALLBACK_URI,
        required=False,
        provider_key="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={"reject_question": "shared.question.reject"},
        business_code_map={-32004: "interrupt_request_not_found"},
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "reject_question"
        assert kwargs["jsonrpc_url"] == "https://example.com/jsonrpc"
        assert kwargs["params"] == {"request_id": "q-1"}
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "request_id": "q-1"},
            meta={"request_id": "q-1"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._interrupt_extensions, "invoke_method", _fake_invoke)

    result = await service.reject_question_interrupt(runtime=runtime, request_id="q-1")
    assert result.success is True
    assert result.result == {"ok": True, "request_id": "q-1"}


@pytest.mark.asyncio
async def test_reply_permission_interrupt_returns_method_not_supported_if_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=_interrupt_extension_fixture(),
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._support, "_call_with_retry", _unexpected_remote_call)

    result = await service.reply_permission_interrupt(
        runtime=runtime,
        request_id="perm-1",
        reply="once",
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta == {"extension_uri": SHARED_INTERRUPT_CALLBACK_URI}


@pytest.mark.asyncio
async def test_reply_question_interrupt_returns_method_not_supported_if_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _interrupt_extension_fixture()
    ext = ResolvedInterruptCallbackExtension(
        uri=ext.uri,
        required=ext.required,
        provider_key=ext.provider_key,
        jsonrpc=ext.jsonrpc,
        methods={
            "reply_permission": "shared.permission.reply",
            "reply_question": None,
            "reject_question": "shared.question.reject",
            "reply_permissions": "shared.permissions.reply",
            "reply_elicitation": "shared.elicitation.reply",
        },
        business_code_map=ext.business_code_map,
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._support, "_call_with_retry", _unexpected_remote_call)

    result = await service.reply_question_interrupt(
        runtime=runtime,
        request_id="q-1",
        answers=[["yes"], ["no"]],
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta["extension_uri"] == SHARED_INTERRUPT_CALLBACK_URI


@pytest.mark.asyncio
async def test_reply_permissions_interrupt_uses_request_id_permissions_and_scope_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = ResolvedInterruptCallbackExtension(
        uri=SHARED_INTERRUPT_CALLBACK_URI,
        required=False,
        provider_key="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={"reply_permissions": "shared.permissions.reply"},
        business_code_map={-32004: "interrupt_request_not_found"},
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "reply_permissions"
        assert kwargs["jsonrpc_url"] == "https://example.com/jsonrpc"
        assert kwargs["params"] == {
            "request_id": "perm-v2-1",
            "permissions": {"fileSystem": {"write": ["/workspace/project"]}},
            "scope": "session",
        }
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "request_id": "perm-v2-1"},
            meta={"request_id": "perm-v2-1"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._interrupt_extensions, "invoke_method", _fake_invoke)

    result = await service.reply_permissions_interrupt(
        runtime=runtime,
        request_id="perm-v2-1",
        permissions={"fileSystem": {"write": ["/workspace/project"]}},
        scope="session",
    )
    assert result.success is True
    assert result.result == {"ok": True, "request_id": "perm-v2-1"}


@pytest.mark.asyncio
async def test_reply_permissions_interrupt_rejects_non_object_permissions() -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(ValueError, match="permissions must be an object"):
        await service.reply_permissions_interrupt(
            runtime=runtime,
            request_id="perm-v2-1",
            permissions=[],  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_reply_permissions_interrupt_returns_method_not_supported_if_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=_interrupt_extension_fixture(),
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._support, "_call_with_retry", _unexpected_remote_call)

    result = await service.reply_permissions_interrupt(
        runtime=runtime,
        request_id="perm-v2-1",
        permissions={"fileSystem": {"write": ["/workspace/project"]}},
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta == {"extension_uri": SHARED_INTERRUPT_CALLBACK_URI}


@pytest.mark.asyncio
async def test_reply_elicitation_interrupt_uses_request_id_action_and_content_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = ResolvedInterruptCallbackExtension(
        uri=SHARED_INTERRUPT_CALLBACK_URI,
        required=False,
        provider_key="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={"reply_elicitation": "shared.elicitation.reply"},
        business_code_map={-32004: "interrupt_request_not_found"},
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "reply_elicitation"
        assert kwargs["jsonrpc_url"] == "https://example.com/jsonrpc"
        assert kwargs["params"] == {
            "request_id": "eli-1",
            "action": "accept",
            "content": {"approved": True},
        }
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "request_id": "eli-1"},
            meta={"request_id": "eli-1"},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._interrupt_extensions, "invoke_method", _fake_invoke)

    result = await service.reply_elicitation_interrupt(
        runtime=runtime,
        request_id="eli-1",
        action="accept",
        content={"approved": True},
    )
    assert result.success is True
    assert result.result == {"ok": True, "request_id": "eli-1"}


@pytest.mark.asyncio
async def test_reply_elicitation_interrupt_rejects_non_null_content_for_decline() -> (
    None
):
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    with pytest.raises(
        ValueError, match="content must be null when action is decline or cancel"
    ):
        await service.reply_elicitation_interrupt(
            runtime=runtime,
            request_id="eli-1",
            action="decline",
            content={"approved": False},
        )


@pytest.mark.asyncio
async def test_reply_elicitation_interrupt_returns_method_not_supported_if_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_callback=_interrupt_snapshot(
                status="supported",
                ext=_interrupt_extension_fixture(),
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("method should be short-circuited as unsupported")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._support, "_call_with_retry", _unexpected_remote_call)

    result = await service.reply_elicitation_interrupt(
        runtime=runtime,
        request_id="eli-1",
        action="cancel",
    )
    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta == {"extension_uri": SHARED_INTERRUPT_CALLBACK_URI}


@pytest.mark.asyncio
async def test_list_model_providers_uses_resolved_provider_discovery_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _provider_discovery_extension_fixture()

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            provider_discovery=_provider_discovery_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        assert kwargs["method_key"] == "list_providers"
        assert kwargs["jsonrpc_url"] == "https://example.com/jsonrpc"
        assert kwargs["params"] == {
            "metadata": {"opencode": {"directory": "/workspace"}}
        }
        return ExtensionCallResult(success=True, result={"items": []}, meta={})

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._provider_discovery, "invoke_method", _fake_invoke)

    result = await service.list_model_providers(
        runtime=runtime,
        working_directory="/workspace",
    )

    assert result.success is True
    assert result.result == {"items": []}


@pytest.mark.asyncio
async def test_list_model_providers_returns_method_not_supported_when_wire_contract_disallows_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    ext = _provider_discovery_extension_fixture()
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
            session_query=_session_query_snapshot(_resolved_extension()),
            provider_discovery=_provider_discovery_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
            wire_contract=_wire_contract_snapshot(
                status="supported",
                ext=wire_contract,
            ),
        )

    async def _unexpected_remote_call(**_kwargs):
        raise AssertionError("provider discovery should be rejected during preflight")

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(
        service._provider_discovery, "invoke_method", _unexpected_remote_call
    )

    result = await service.list_model_providers(runtime=runtime)

    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.source == "wire_contract"
    assert result.meta == {
        "extension_uri": PROVIDER_DISCOVERY_URI,
        "wire_contract_uri": OPENCODE_WIRE_CONTRACT_URI,
        "wire_contract_preflight": "unsupported_method",
        "method_name": "providers.list",
    }


@pytest.mark.asyncio
async def test_list_upstream_skills_invokes_upstream_discovery_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    wire_contract = _wire_contract_extension_fixture(
        all_jsonrpc_methods=("codex.discovery.skills.list",)
    )

    async def _fake_snapshot(*, runtime):
        assert runtime is not None
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            wire_contract=_wire_contract_snapshot(
                status="supported", ext=wire_contract
            ),
            compatibility_profile=_compatibility_profile_snapshot(),
            upstream_discovery=DeclaredMethodCollectionCapabilitySnapshot(
                declared=True,
                consumed_by_hub=True,
                status="supported",
                methods={
                    "skillsList": DeclaredMethodCapabilitySnapshot(
                        declared=True,
                        consumed_by_hub=True,
                        method="codex.discovery.skills.list",
                        availability="always",
                    ),
                    "appsList": DeclaredMethodCapabilitySnapshot(
                        declared=False,
                        consumed_by_hub=False,
                        method=None,
                    ),
                    "pluginsList": DeclaredMethodCapabilitySnapshot(
                        declared=False,
                        consumed_by_hub=False,
                        method=None,
                    ),
                    "pluginsRead": DeclaredMethodCapabilitySnapshot(
                        declared=False,
                        consumed_by_hub=False,
                        method=None,
                    ),
                    "watch": DeclaredMethodCapabilitySnapshot(
                        declared=False,
                        consumed_by_hub=False,
                        method=None,
                    ),
                },
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_list_skills(**kwargs):
        assert kwargs["method_name"] == "codex.discovery.skills.list"
        return ExtensionCallResult(
            success=True, result={"items": []}, meta=kwargs["meta"]
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._upstream_discovery, "list_skills", _fake_list_skills)

    result = await service.list_upstream_skills(runtime=runtime)

    assert result.success is True
    assert result.result == {"items": []}


@pytest.mark.asyncio
async def test_read_upstream_plugin_validates_marketplace_path_and_plugin_name() -> (
    None
):
    service = A2AExtensionsService()
    runtime = SimpleNamespace(resolved=SimpleNamespace(url="https://example.com"))

    with pytest.raises(ValueError):
        await service.read_upstream_plugin(
            runtime=runtime,
            marketplace_path="   ",
            plugin_name="planner",
        )
    with pytest.raises(ValueError):
        await service.read_upstream_plugin(
            runtime=runtime,
            marketplace_path="/workspace/.codex/plugins/marketplace.json",
            plugin_name="   ",
        )


@pytest.mark.asyncio
async def test_read_upstream_plugin_returns_method_not_supported_when_wire_contract_disallows_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(resolved=SimpleNamespace(url="https://example.com"))
    wire_contract = _wire_contract_extension_fixture(
        all_jsonrpc_methods=("codex.discovery.skills.list",)
    )

    async def _fake_snapshot(*, runtime):
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            wire_contract=_wire_contract_snapshot(
                status="supported", ext=wire_contract
            ),
            upstream_discovery=DeclaredMethodCollectionCapabilitySnapshot(
                declared=True,
                consumed_by_hub=True,
                status="partially_consumed",
                methods={
                    "skillsList": DeclaredMethodCapabilitySnapshot(
                        declared=True,
                        consumed_by_hub=True,
                        method="codex.discovery.skills.list",
                        availability="always",
                    ),
                    "appsList": DeclaredMethodCapabilitySnapshot(
                        declared=False,
                        consumed_by_hub=False,
                        method=None,
                    ),
                    "pluginsList": DeclaredMethodCapabilitySnapshot(
                        declared=False,
                        consumed_by_hub=False,
                        method=None,
                    ),
                    "pluginsRead": DeclaredMethodCapabilitySnapshot(
                        declared=True,
                        consumed_by_hub=True,
                        method="codex.discovery.plugins.read",
                        availability="always",
                    ),
                    "watch": DeclaredMethodCapabilitySnapshot(
                        declared=False,
                        consumed_by_hub=False,
                        method=None,
                    ),
                },
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _unexpected_read_plugin(**_kwargs):
        raise AssertionError(
            "plugin read should be rejected during wire-contract preflight"
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(
        service._upstream_discovery, "read_plugin", _unexpected_read_plugin
    )

    result = await service.read_upstream_plugin(
        runtime=runtime,
        marketplace_path="/workspace/.codex/plugins/marketplace.json",
        plugin_name="planner",
    )

    assert result.success is False
    assert result.error_code == "method_not_supported"
    assert result.meta == {
        "extension_uri": OPENCODE_WIRE_CONTRACT_URI,
        "wire_contract_uri": OPENCODE_WIRE_CONTRACT_URI,
        "wire_contract_preflight": "unsupported_method",
        "method_name": "codex.discovery.plugins.read",
    }


@pytest.mark.asyncio
async def test_provider_and_interrupt_share_single_card_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(url="https://example.com/.well-known/agent-card.json")
    )
    fetch_calls = 0
    fake_card = SimpleNamespace(
        supported_interfaces=[
            SimpleNamespace(
                protocol_binding="JSONRPC",
                url="https://example.com/jsonrpc",
            )
        ],
        capabilities=SimpleNamespace(
            extensions=[
                SimpleNamespace(
                    uri=SHARED_SESSION_QUERY_URI,
                    required=False,
                    params={
                        "provider": "opencode",
                        "methods": {
                            "list_sessions": "shared.sessions.list",
                            "get_session_messages": "shared.sessions.messages.list",
                            "prompt_async": "shared.sessions.prompt_async",
                        },
                        "pagination": {
                            "mode": "limit",
                            "default_limit": 20,
                            "max_limit": 100,
                            "params": ["limit", "offset"],
                        },
                    },
                ),
                SimpleNamespace(
                    uri=PROVIDER_DISCOVERY_URI,
                    required=False,
                    params={
                        "methods": {
                            "list_providers": "providers.list",
                            "list_models": "models.list",
                        }
                    },
                ),
                SimpleNamespace(
                    uri=SHARED_INTERRUPT_CALLBACK_URI,
                    required=False,
                    params={
                        "methods": {
                            "reply_permission": "shared.permission.reply",
                            "reply_question": "shared.question.reply",
                            "reject_question": "shared.question.reject",
                        }
                    },
                ),
            ]
        ),
    )

    async def _fake_fetch_card(_runtime):
        nonlocal fetch_calls
        fetch_calls += 1
        return fake_card

    async def _fake_provider_invoke(**kwargs):
        assert kwargs["method_key"] == "list_providers"
        return ExtensionCallResult(success=True, result={"items": []}, meta={})

    async def _fake_interrupt_invoke(**kwargs):
        assert kwargs["method_key"] == "reply_permission"
        return ExtensionCallResult(
            success=True,
            result={"ok": True, "request_id": "perm-1"},
            meta={"request_id": "perm-1"},
        )

    monkeypatch.setattr(service._support, "fetch_card", _fake_fetch_card)
    monkeypatch.setattr(
        service._support,
        "ensure_outbound_allowed",
        lambda url, *, purpose: url,
    )
    monkeypatch.setattr(
        service._provider_discovery, "invoke_method", _fake_provider_invoke
    )
    monkeypatch.setattr(
        service._interrupt_extensions, "invoke_method", _fake_interrupt_invoke
    )

    providers = await service.list_model_providers(runtime=runtime)
    interrupt = await service.reply_permission_interrupt(
        runtime=runtime,
        request_id="perm-1",
        reply="once",
    )

    assert providers.success is True
    assert interrupt.success is True
    assert fetch_calls == 1


@pytest.mark.asyncio
async def test_recover_interrupts_merges_and_filters_by_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(resolved=SimpleNamespace(url="https://example.com"))
    ext = _interrupt_recovery_extension_fixture()
    calls: list[str] = []

    async def _fake_snapshot(*, runtime):
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_recovery=_interrupt_recovery_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        calls.append(kwargs["method_key"])
        if kwargs["method_key"] == "list_permissions":
            return ExtensionCallResult(
                success=True,
                result={
                    "items": [
                        {
                            "request_id": "perm-1",
                            "session_id": "sess-1",
                            "type": "permission",
                            "details": {"permission": "write"},
                            "expires_at": 20,
                        },
                        {
                            "request_id": "perm-2",
                            "session_id": "sess-2",
                            "type": "permission",
                            "details": {"permission": "read"},
                            "expires_at": 25,
                        },
                    ]
                },
                meta={},
            )
        return ExtensionCallResult(
            success=True,
            result={
                "items": [
                    {
                        "request_id": "perm-1",
                        "session_id": "sess-1",
                        "type": "permission",
                        "details": {"permission": "write"},
                        "expires_at": 20,
                    },
                    {
                        "request_id": "q-1",
                        "session_id": "sess-1",
                        "type": "question",
                        "details": {"questions": []},
                        "expires_at": 10,
                    },
                ]
            },
            meta={},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._interrupt_recovery, "invoke_method", _fake_invoke)

    result = await service.recover_interrupts(runtime=runtime, session_id="sess-1")

    assert result.success is True
    assert calls == ["list_permissions", "list_questions"]
    assert result.result == {
        "items": [
            {
                "request_id": "q-1",
                "session_id": "sess-1",
                "type": "question",
                "details": {"questions": []},
                "expires_at": 10,
            },
            {
                "request_id": "perm-1",
                "session_id": "sess-1",
                "type": "permission",
                "details": {"permission": "write"},
                "expires_at": 20,
            },
        ]
    }


@pytest.mark.asyncio
async def test_recover_interrupts_returns_method_not_supported_when_upstream_missing_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(resolved=SimpleNamespace(url="https://example.com"))
    ext = ResolvedInterruptRecoveryExtension(
        uri=INTERRUPT_RECOVERY_URI,
        required=False,
        provider_key="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={
            "list_permissions": "opencode.permissions.list",
            "list_questions": None,
        },
        business_code_map={},
    )

    async def _fake_snapshot(*, runtime):
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_recovery=_interrupt_recovery_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_invoke(**kwargs):
        if kwargs["method_key"] == "list_permissions":
            return ExtensionCallResult(success=True, result={"items": []}, meta={})
        assert kwargs["method_key"] == "list_questions"
        return ExtensionCallResult(
            success=False,
            error_code="method_not_supported",
            upstream_error={"message": "Method list_questions is not supported"},
            meta={},
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(service._interrupt_recovery, "invoke_method", _fake_invoke)

    result = await service.recover_interrupts(runtime=runtime, session_id="sess-1")

    assert result.success is False
    assert result.error_code == "method_not_supported"


@pytest.mark.asyncio
async def test_recover_interrupts_supports_single_list_method_and_properties_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = A2AExtensionsService()
    runtime = SimpleNamespace(resolved=SimpleNamespace(url="https://example.com"))
    ext = ResolvedInterruptRecoveryExtension(
        uri="urn:codex-a2a:codex-interrupt-recovery/v1",
        required=False,
        provider_key="codex",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={
            "list": "codex.interrupts.list",
            "list_permissions": None,
            "list_questions": None,
        },
        business_code_map={},
    )

    async def _fake_snapshot(*, runtime):
        return _capability_snapshot(
            session_query=_session_query_snapshot(_resolved_extension()),
            interrupt_recovery=_interrupt_recovery_snapshot(
                status="supported",
                ext=ext,
                jsonrpc_url="https://example.com/jsonrpc",
            ),
        )

    async def _fake_jsonrpc_call(**kwargs):
        assert kwargs["method_name"] == "codex.interrupts.list"
        return SimpleNamespace(
            ok=True,
            result={
                "items": [
                    {
                        "request_id": "q-1",
                        "session_id": "sess-1",
                        "interrupt_type": "question",
                        "properties": {"questions": []},
                        "expires_at": 10,
                    },
                    {
                        "request_id": "perm-1",
                        "session_id": "sess-1",
                        "interrupt_type": "permission",
                        "properties": {"permission": "write"},
                        "expires_at": 20,
                    },
                    {
                        "request_id": "perm-2",
                        "session_id": "sess-2",
                        "interrupt_type": "permission",
                        "properties": {"permission": "read"},
                        "expires_at": 30,
                    },
                ]
            },
        )

    monkeypatch.setattr(service, "resolve_capability_snapshot", _fake_snapshot)
    monkeypatch.setattr(
        service._support,
        "perform_jsonrpc_call",
        _fake_jsonrpc_call,
    )

    result = await service.recover_interrupts(runtime=runtime, session_id="sess-1")

    assert result.success is True
    assert result.result == {
        "items": [
            {
                "request_id": "q-1",
                "session_id": "sess-1",
                "type": "question",
                "details": {"questions": []},
                "expires_at": 10,
            },
            {
                "request_id": "perm-1",
                "session_id": "sess-1",
                "type": "permission",
                "details": {"permission": "write"},
                "expires_at": 20,
            },
        ]
    }
