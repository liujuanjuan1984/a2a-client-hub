from __future__ import annotations

from tests.agents.shared import hub_a2a_extensions_routes_support as support
from tests.agents.shared.hub_a2a_extensions_routes_support import (
    SimpleNamespace,
    _create_allowlisted_hub_agent,
    _FakeExtensionsService,
    create_test_client,
    extension_router_common,
    hub_extension_router,
    pytest,
    runtime_status_contract_payload,
    settings,
)

pytestmark = support.pytestmark


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_hub_extension_capabilities_route_returns_model_selection_true(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_opencode_cap_true@example.com",
        user_email="alice_opencode_cap_true@example.com",
        token="secret-token-opencode-capability-true",
    )

    fake_extensions = _FakeExtensionsService()
    fake_extensions.capability_snapshot = SimpleNamespace(
        model_selection=SimpleNamespace(status="supported"),
        provider_discovery=SimpleNamespace(status="supported"),
        interrupt_recovery=SimpleNamespace(
            status="supported",
            error=None,
            ext=SimpleNamespace(
                provider="opencode",
                methods={
                    "list_permissions": "opencode.permissions.list",
                    "list_questions": "opencode.questions.list",
                },
                recovery_data_source="local_interrupt_binding_registry",
                identity_scope="current_authenticated_caller",
                implementation_scope=None,
                empty_result_when_identity_unavailable=True,
                uri="urn:opencode-a2a:interrupt-recovery/v1",
            ),
        ),
        invoke_metadata=SimpleNamespace(status="unsupported", ext=None),
        request_execution_options=SimpleNamespace(
            declared=True,
            consumed_by_hub=True,
            status="supported",
            metadata_field="metadata.codex.execution",
            fields=("model", "effort", "summary", "personality"),
            persists_for_thread=True,
            source_extensions=(
                "urn:a2a:session-binding/v1",
                "urn:opencode-a2a:session-query/v1",
            ),
            notes=("Execution overrides are provider-private.",),
            error=None,
        ),
        stream_hints=SimpleNamespace(
            status="supported",
            error=None,
            ext=SimpleNamespace(
                stream_field="metadata.shared.stream",
                usage_field="metadata.shared.usage",
                interrupt_field="metadata.shared.interrupt",
                session_field="metadata.shared.session",
            ),
            meta={
                "stream_hints_declared": True,
                "stream_hints_mode": "declared_contract",
                "stream_hints_fallback_used": False,
            },
        ),
        wire_contract=SimpleNamespace(
            status="supported",
            error=None,
            ext=SimpleNamespace(
                protocol_version="0.3.0",
                preferred_transport="HTTP+JSON",
                additional_transports=("JSON-RPC",),
                all_jsonrpc_methods=(
                    "shared.sessions.prompt_async",
                    "shared.sessions.command",
                    "providers.list",
                    "models.list",
                    "codex.discovery.skills.list",
                    "codex.discovery.plugins.list",
                    "codex.discovery.plugins.read",
                    "codex.threads.archive",
                    "codex.threads.watch",
                    "codex.turns.steer",
                    "codex.review.watch",
                    "codex.exec.start",
                    "codex.exec.terminate",
                ),
                extension_uris=(
                    "urn:opencode-a2a:provider-discovery/v1",
                    "urn:opencode-a2a:session-query/v1",
                ),
                conditionally_available_methods={
                    "opencode.sessions.shell": SimpleNamespace(
                        reason="disabled_by_configuration",
                        toggle="A2A_ENABLE_SESSION_SHELL",
                    )
                },
                unsupported_method_error=SimpleNamespace(
                    code=-32601,
                    type="METHOD_NOT_SUPPORTED",
                    data_fields=(
                        "type",
                        "method",
                        "supported_methods",
                        "protocol_version",
                    ),
                ),
            ),
        ),
        compatibility_profile=SimpleNamespace(
            status="supported",
            error=None,
            ext=SimpleNamespace(
                uri="urn:a2a:compatibility-profile/v1",
                extension_retention={
                    "urn:opencode-a2a:session-query/v1": SimpleNamespace(
                        surface="jsonrpc-extension",
                        availability="always",
                        retention="stable",
                        extension_uri=None,
                        toggle=None,
                        implementation_scope=None,
                        identity_scope=None,
                        upstream_stability=None,
                    ),
                    "urn:opencode-a2a:interrupt-recovery/v1": SimpleNamespace(
                        surface="jsonrpc-extension",
                        availability="always",
                        retention="stable",
                        extension_uri=None,
                        toggle=None,
                        implementation_scope="adapter-local",
                        identity_scope="current_authenticated_caller",
                        upstream_stability=None,
                    ),
                },
                method_retention={
                    "opencode.sessions.shell": SimpleNamespace(
                        surface="extension",
                        availability="disabled",
                        retention="deployment-conditional",
                        extension_uri="urn:opencode-a2a:session-query/v1",
                        toggle="A2A_ENABLE_SESSION_SHELL",
                        implementation_scope=None,
                        identity_scope=None,
                        upstream_stability=None,
                    )
                },
                service_behaviors={
                    "classification": "stable-service-semantics",
                    "methods": {"tasks/cancel": {"retention": "stable"}},
                },
                consumer_guidance=(
                    "Treat opencode.sessions.shell as deployment-conditional.",
                ),
            ),
        ),
        upstream_discovery=SimpleNamespace(
            declared=True,
            consumed_by_hub=True,
            status="supported",
            declaration_source="wire_contract",
            declaration_confidence="authoritative",
            negotiation_state="supported",
            diagnostic_note=None,
            methods={
                "skillsList": SimpleNamespace(
                    declared=True,
                    consumed_by_hub=True,
                    method="codex.discovery.skills.list",
                ),
                "appsList": SimpleNamespace(
                    declared=False,
                    consumed_by_hub=False,
                    method=None,
                ),
                "pluginsList": SimpleNamespace(
                    declared=True,
                    consumed_by_hub=True,
                    method="codex.discovery.plugins.list",
                ),
                "pluginsRead": SimpleNamespace(
                    declared=True,
                    consumed_by_hub=True,
                    method="codex.discovery.plugins.read",
                ),
                "watch": SimpleNamespace(
                    declared=False,
                    consumed_by_hub=False,
                    method=None,
                ),
            },
        ),
        upstream_threads=SimpleNamespace(
            declared=True,
            consumed_by_hub=False,
            status="unsupported_by_design",
            methods={
                "fork": SimpleNamespace(
                    declared=False,
                    consumed_by_hub=False,
                    method=None,
                ),
                "archive": SimpleNamespace(
                    declared=True,
                    consumed_by_hub=False,
                    method="codex.threads.archive",
                ),
                "unarchive": SimpleNamespace(
                    declared=False,
                    consumed_by_hub=False,
                    method=None,
                ),
                "metadataUpdate": SimpleNamespace(
                    declared=False,
                    consumed_by_hub=False,
                    method=None,
                ),
                "watch": SimpleNamespace(
                    declared=True,
                    consumed_by_hub=False,
                    method="codex.threads.watch",
                ),
            },
        ),
        upstream_turns=SimpleNamespace(
            declared=True,
            consumed_by_hub=True,
            status="supported",
            methods={
                "steer": SimpleNamespace(
                    declared=True,
                    consumed_by_hub=True,
                    method="codex.turns.steer",
                ),
            },
        ),
        upstream_review=SimpleNamespace(
            declared=True,
            consumed_by_hub=False,
            status="unsupported_by_design",
            methods={
                "start": SimpleNamespace(
                    declared=False,
                    consumed_by_hub=False,
                    method=None,
                ),
                "watch": SimpleNamespace(
                    declared=True,
                    consumed_by_hub=False,
                    method="codex.review.watch",
                ),
            },
        ),
        upstream_exec=SimpleNamespace(
            declared=True,
            consumed_by_hub=False,
            status="unsupported_by_design",
            methods={
                "start": SimpleNamespace(
                    declared=True,
                    consumed_by_hub=False,
                    method="codex.exec.start",
                ),
                "write": SimpleNamespace(
                    declared=False,
                    consumed_by_hub=False,
                    method=None,
                ),
                "resize": SimpleNamespace(
                    declared=False,
                    consumed_by_hub=False,
                    method=None,
                ),
                "terminate": SimpleNamespace(
                    declared=True,
                    consumed_by_hub=False,
                    method="codex.exec.terminate",
                ),
            },
        ),
        session_query=SimpleNamespace(
            status="supported",
            capability=SimpleNamespace(
                control_methods={
                    "prompt_async": SimpleNamespace(
                        declared=True,
                        availability="always",
                        method="shared.sessions.prompt_async",
                    ),
                    "command": SimpleNamespace(
                        declared=True,
                        availability="always",
                        method="shared.sessions.command",
                    ),
                    "shell": SimpleNamespace(
                        declared=False,
                        availability="conditional",
                        config_key="A2A_ENABLE_SESSION_SHELL",
                        enabled_by_default=False,
                    ),
                }
            ),
        ),
    )
    monkeypatch.setattr(
        extension_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    async with create_test_client(
        hub_extension_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        response = await user_client.get(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/capabilities"
        )

    assert response.status_code == 200
    assert response.json() == {
        "modelSelection": True,
        "providerDiscovery": True,
        "interruptRecovery": True,
        "interruptRecoveryDetails": {
            "declared": True,
            "consumedByHub": True,
            "status": "supported",
            "provider": "opencode",
            "methods": {
                "list_permissions": "opencode.permissions.list",
                "list_questions": "opencode.questions.list",
            },
            "recoveryDataSource": "local_interrupt_binding_registry",
            "identityScope": "current_authenticated_caller",
            "implementationScope": "adapter-local",
            "emptyResultWhenIdentityUnavailable": True,
            "error": None,
        },
        "sessionPromptAsync": True,
        "sessionControl": {
            "append": {
                "declared": True,
                "consumedByHub": True,
                "status": "supported",
                "routeMode": "hybrid",
                "requiresStreamIdentity": False,
            },
            "promptAsync": {
                "declared": True,
                "consumedByHub": True,
                "availability": "always",
                "method": "shared.sessions.prompt_async",
                "enabledByDefault": None,
                "configKey": None,
            },
            "command": {
                "declared": True,
                "consumedByHub": True,
                "availability": "always",
                "method": "shared.sessions.command",
                "enabledByDefault": None,
                "configKey": None,
            },
            "shell": {
                "declared": False,
                "consumedByHub": False,
                "availability": "conditional",
                "method": None,
                "enabledByDefault": False,
                "configKey": "A2A_ENABLE_SESSION_SHELL",
            },
        },
        "invokeMetadata": {
            "declared": False,
            "consumedByHub": True,
            "status": "unsupported",
            "metadataField": None,
            "appliesToMethods": [],
            "fields": [],
            "error": None,
        },
        "requestExecutionOptions": {
            "declared": True,
            "consumedByHub": True,
            "status": "supported",
            "metadataField": "metadata.codex.execution",
            "fields": ["model", "effort", "summary", "personality"],
            "persistsForThread": True,
            "sourceExtensions": [
                "urn:a2a:session-binding/v1",
                "urn:opencode-a2a:session-query/v1",
            ],
            "notes": ["Execution overrides are provider-private."],
            "error": None,
        },
        "streamHints": {
            "declared": True,
            "consumedByHub": True,
            "status": "supported",
            "streamField": "metadata.shared.stream",
            "usageField": "metadata.shared.usage",
            "interruptField": "metadata.shared.interrupt",
            "sessionField": "metadata.shared.session",
            "mode": "declared_contract",
            "fallbackUsed": False,
            "error": None,
        },
        "wireContract": {
            "declared": True,
            "consumedByHub": True,
            "status": "supported",
            "protocolVersion": "0.3.0",
            "preferredTransport": "HTTP+JSON",
            "additionalTransports": ["JSON-RPC"],
            "allJsonrpcMethods": [
                "shared.sessions.prompt_async",
                "shared.sessions.command",
                "providers.list",
                "models.list",
                "codex.discovery.skills.list",
                "codex.discovery.plugins.list",
                "codex.discovery.plugins.read",
                "codex.threads.archive",
                "codex.threads.watch",
                "codex.turns.steer",
                "codex.review.watch",
                "codex.exec.start",
                "codex.exec.terminate",
            ],
            "extensionUris": [
                "urn:opencode-a2a:provider-discovery/v1",
                "urn:opencode-a2a:session-query/v1",
            ],
            "conditionalMethods": {
                "opencode.sessions.shell": {
                    "reason": "disabled_by_configuration",
                    "toggle": "A2A_ENABLE_SESSION_SHELL",
                }
            },
            "unsupportedMethodError": {
                "code": -32601,
                "type": "METHOD_NOT_SUPPORTED",
                "dataFields": [
                    "type",
                    "method",
                    "supported_methods",
                    "protocol_version",
                ],
            },
            "error": None,
        },
        "compatibilityProfile": {
            "declared": True,
            "status": "supported",
            "uri": "urn:a2a:compatibility-profile/v1",
            "advisoryOnly": True,
            "usedFor": ["diagnostics", "retention_hints"],
            "extensionRetentionCount": 2,
            "methodRetentionCount": 1,
            "serviceBehaviorKeys": ["classification", "methods"],
            "consumerGuidance": [
                "Treat opencode.sessions.shell as deployment-conditional."
            ],
            "error": None,
        },
        "upstreamMethodFamilies": {
            "discovery": {
                "declared": True,
                "consumedByHub": True,
                "status": "supported",
                "declarationSource": "wire_contract",
                "declarationConfidence": "authoritative",
                "negotiationState": "supported",
                "diagnosticNote": None,
                "methods": {
                    "skillsList": {
                        "declared": True,
                        "consumedByHub": True,
                        "method": "codex.discovery.skills.list",
                        "availability": "always",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                    "appsList": {
                        "declared": False,
                        "consumedByHub": False,
                        "method": None,
                        "availability": "unsupported",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                    "pluginsList": {
                        "declared": True,
                        "consumedByHub": True,
                        "method": "codex.discovery.plugins.list",
                        "availability": "always",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                    "pluginsRead": {
                        "declared": True,
                        "consumedByHub": True,
                        "method": "codex.discovery.plugins.read",
                        "availability": "always",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                    "watch": {
                        "declared": False,
                        "consumedByHub": False,
                        "method": None,
                        "availability": "unsupported",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                },
            },
            "threads": {
                "declared": True,
                "consumedByHub": False,
                "status": "unsupported_by_design",
                "declarationSource": None,
                "declarationConfidence": None,
                "negotiationState": None,
                "diagnosticNote": None,
                "methods": {
                    "fork": {
                        "declared": False,
                        "consumedByHub": False,
                        "method": None,
                        "availability": "unsupported",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                    "archive": {
                        "declared": True,
                        "consumedByHub": False,
                        "method": "codex.threads.archive",
                        "availability": "always",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                    "unarchive": {
                        "declared": False,
                        "consumedByHub": False,
                        "method": None,
                        "availability": "unsupported",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                    "metadataUpdate": {
                        "declared": False,
                        "consumedByHub": False,
                        "method": None,
                        "availability": "unsupported",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                    "watch": {
                        "declared": True,
                        "consumedByHub": False,
                        "method": "codex.threads.watch",
                        "availability": "always",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                },
            },
            "turns": {
                "declared": True,
                "consumedByHub": True,
                "status": "supported",
                "declarationSource": None,
                "declarationConfidence": None,
                "negotiationState": None,
                "diagnosticNote": None,
                "methods": {
                    "steer": {
                        "declared": True,
                        "consumedByHub": True,
                        "method": "codex.turns.steer",
                        "availability": "always",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    }
                },
            },
            "review": {
                "declared": True,
                "consumedByHub": False,
                "status": "unsupported_by_design",
                "declarationSource": None,
                "declarationConfidence": None,
                "negotiationState": None,
                "diagnosticNote": None,
                "methods": {
                    "start": {
                        "declared": False,
                        "consumedByHub": False,
                        "method": None,
                        "availability": "unsupported",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                    "watch": {
                        "declared": True,
                        "consumedByHub": False,
                        "method": "codex.review.watch",
                        "availability": "always",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                },
            },
            "exec": {
                "declared": True,
                "consumedByHub": False,
                "status": "unsupported_by_design",
                "declarationSource": None,
                "declarationConfidence": None,
                "negotiationState": None,
                "diagnosticNote": None,
                "methods": {
                    "start": {
                        "declared": True,
                        "consumedByHub": False,
                        "method": "codex.exec.start",
                        "availability": "always",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                    "write": {
                        "declared": False,
                        "consumedByHub": False,
                        "method": None,
                        "availability": "unsupported",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                    "resize": {
                        "declared": False,
                        "consumedByHub": False,
                        "method": None,
                        "availability": "unsupported",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                    "terminate": {
                        "declared": True,
                        "consumedByHub": False,
                        "method": "codex.exec.terminate",
                        "availability": "always",
                        "configKey": None,
                        "reason": None,
                        "retention": None,
                    },
                },
            },
        },
        "runtimeStatus": runtime_status_contract_payload(),
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_hub_extension_capabilities_route_returns_model_selection_false_for_unsupported_agent(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_opencode_cap_false@example.com",
        user_email="alice_opencode_cap_false@example.com",
        token="secret-token-opencode-capability-false",
    )

    fake_extensions = _FakeExtensionsService()
    fake_extensions.capability_snapshot = SimpleNamespace(
        model_selection=SimpleNamespace(status="supported"),
        provider_discovery=SimpleNamespace(status="unsupported"),
        interrupt_recovery=SimpleNamespace(status="unsupported"),
        wire_contract=SimpleNamespace(
            status="unsupported",
            ext=None,
            error="Wire contract extension not found",
        ),
        compatibility_profile=SimpleNamespace(
            status="unsupported",
            ext=None,
            error="Compatibility profile extension not found",
        ),
        session_query=SimpleNamespace(
            status="supported",
            capability=SimpleNamespace(
                control_methods={
                    "prompt_async": SimpleNamespace(
                        declared=False,
                        availability="unsupported",
                        method=None,
                    ),
                    "command": SimpleNamespace(
                        declared=False,
                        availability="unsupported",
                        method=None,
                    ),
                    "shell": SimpleNamespace(
                        declared=False,
                        availability="unsupported",
                        method=None,
                    ),
                }
            ),
        ),
        invoke_metadata=SimpleNamespace(status="unsupported", ext=None),
    )
    monkeypatch.setattr(
        extension_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    async with create_test_client(
        hub_extension_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        response = await user_client.get(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/capabilities"
        )

    assert response.status_code == 200
    assert response.json() == {
        "modelSelection": True,
        "providerDiscovery": False,
        "interruptRecovery": False,
        "interruptRecoveryDetails": {
            "declared": False,
            "consumedByHub": False,
            "status": "unsupported",
            "provider": None,
            "methods": {},
            "recoveryDataSource": None,
            "identityScope": None,
            "implementationScope": None,
            "emptyResultWhenIdentityUnavailable": None,
            "error": None,
        },
        "sessionPromptAsync": False,
        "sessionControl": {
            "append": {
                "declared": False,
                "consumedByHub": True,
                "status": "unsupported",
                "routeMode": "unsupported",
                "requiresStreamIdentity": False,
            },
            "promptAsync": {
                "declared": False,
                "consumedByHub": True,
                "availability": "unsupported",
                "method": None,
                "enabledByDefault": None,
                "configKey": None,
            },
            "command": {
                "declared": False,
                "consumedByHub": True,
                "availability": "unsupported",
                "method": None,
                "enabledByDefault": None,
                "configKey": None,
            },
            "shell": {
                "declared": False,
                "consumedByHub": False,
                "availability": "unsupported",
                "method": None,
                "enabledByDefault": None,
                "configKey": None,
            },
        },
        "invokeMetadata": {
            "declared": False,
            "consumedByHub": True,
            "status": "unsupported",
            "metadataField": None,
            "appliesToMethods": [],
            "fields": [],
            "error": None,
        },
        "requestExecutionOptions": {
            "declared": False,
            "consumedByHub": False,
            "status": "unsupported",
            "metadataField": None,
            "fields": [],
            "persistsForThread": None,
            "sourceExtensions": [],
            "notes": [],
            "error": None,
        },
        "streamHints": {
            "declared": False,
            "consumedByHub": False,
            "status": "unsupported",
            "streamField": None,
            "usageField": None,
            "interruptField": None,
            "sessionField": None,
            "mode": None,
            "fallbackUsed": None,
            "error": None,
        },
        "wireContract": {
            "declared": False,
            "consumedByHub": True,
            "status": "unsupported",
            "protocolVersion": None,
            "preferredTransport": None,
            "additionalTransports": [],
            "allJsonrpcMethods": [],
            "extensionUris": [],
            "conditionalMethods": {},
            "unsupportedMethodError": None,
            "error": "Wire contract extension not found",
        },
        "compatibilityProfile": {
            "declared": False,
            "status": "unsupported",
            "uri": None,
            "advisoryOnly": True,
            "usedFor": ["diagnostics", "retention_hints"],
            "extensionRetentionCount": 0,
            "methodRetentionCount": 0,
            "serviceBehaviorKeys": [],
            "consumerGuidance": [],
            "error": "Compatibility profile extension not found",
        },
        "upstreamMethodFamilies": {
            "discovery": {
                "declared": False,
                "consumedByHub": False,
                "status": "unsupported",
                "methods": {},
                "declarationSource": None,
                "declarationConfidence": None,
                "negotiationState": None,
                "diagnosticNote": None,
            },
            "threads": {
                "declared": False,
                "consumedByHub": False,
                "status": "unsupported",
                "methods": {},
                "declarationSource": None,
                "declarationConfidence": None,
                "negotiationState": None,
                "diagnosticNote": None,
            },
            "turns": {
                "declared": False,
                "consumedByHub": False,
                "status": "unsupported",
                "methods": {},
                "declarationSource": None,
                "declarationConfidence": None,
                "negotiationState": None,
                "diagnosticNote": None,
            },
            "review": {
                "declared": False,
                "consumedByHub": False,
                "status": "unsupported",
                "methods": {},
                "declarationSource": None,
                "declarationConfidence": None,
                "negotiationState": None,
                "diagnosticNote": None,
            },
            "exec": {
                "declared": False,
                "consumedByHub": False,
                "status": "unsupported",
                "declarationSource": None,
                "declarationConfidence": None,
                "negotiationState": None,
                "diagnosticNote": None,
                "methods": {},
            },
        },
        "runtimeStatus": runtime_status_contract_payload(),
    }


@pytest.mark.asyncio
async def test_hub_extension_capabilities_closes_read_only_transaction_before_upstream_call(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_opencode_cap_close@example.com",
        user_email="alice_opencode_cap_close@example.com",
        token="secret-token-opencode-cap-close",
    )

    call_order: list[str] = []
    fake_extensions = _FakeExtensionsService()

    async def fake_load_for_external_call(_db, operation):
        call_order.append("prepare_external_call")
        return await operation(_db)

    async def fake_resolve_capability_snapshot(*, runtime):
        call_order.append("resolve_capability_snapshot")
        return await _FakeExtensionsService.resolve_capability_snapshot(
            fake_extensions,
            runtime=runtime,
        )

    monkeypatch.setattr(
        extension_router_common,
        "load_for_external_call",
        fake_load_for_external_call,
    )
    monkeypatch.setattr(
        fake_extensions,
        "resolve_capability_snapshot",
        fake_resolve_capability_snapshot,
    )
    monkeypatch.setattr(
        extension_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    async with create_test_client(
        hub_extension_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        response = await user_client.get(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/capabilities"
        )

    assert response.status_code == 200
    assert call_order == ["prepare_external_call", "resolve_capability_snapshot"]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_hub_extension_capabilities_route_distinguishes_model_selection_from_provider_discovery(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_model_selection_only@example.com",
        user_email="alice_model_selection_only@example.com",
        token="secret-token-model-selection-only",
    )

    fake_extensions = _FakeExtensionsService()
    fake_extensions.capability_snapshot = SimpleNamespace(
        model_selection=SimpleNamespace(status="unsupported"),
        provider_discovery=SimpleNamespace(status="supported"),
        interrupt_recovery=SimpleNamespace(status="unsupported"),
        wire_contract=SimpleNamespace(
            status="invalid",
            ext=None,
            error="Extension contract missing/invalid 'params.extensions.jsonrpc_methods'",
        ),
        compatibility_profile=SimpleNamespace(
            status="invalid",
            ext=None,
            error="Extension contract missing/invalid 'params.method_retention'",
        ),
        session_query=SimpleNamespace(
            status="supported",
            capability=SimpleNamespace(
                control_methods={
                    "prompt_async": SimpleNamespace(
                        declared=True,
                        availability="always",
                        method="shared.sessions.prompt_async",
                    ),
                    "command": SimpleNamespace(
                        declared=True,
                        availability="always",
                        method="shared.sessions.command",
                    ),
                    "shell": SimpleNamespace(
                        declared=False,
                        availability="conditional",
                        config_key="A2A_ENABLE_SESSION_SHELL",
                        enabled_by_default=False,
                    ),
                }
            ),
        ),
        invoke_metadata=SimpleNamespace(status="unsupported", ext=None),
    )
    monkeypatch.setattr(
        extension_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    async with create_test_client(
        hub_extension_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        response = await user_client.get(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/capabilities"
        )

    assert response.status_code == 200
    assert response.json() == {
        "modelSelection": False,
        "providerDiscovery": True,
        "interruptRecovery": False,
        "interruptRecoveryDetails": {
            "declared": False,
            "consumedByHub": False,
            "status": "unsupported",
            "provider": None,
            "methods": {},
            "recoveryDataSource": None,
            "identityScope": None,
            "implementationScope": None,
            "emptyResultWhenIdentityUnavailable": None,
            "error": None,
        },
        "sessionPromptAsync": True,
        "sessionControl": {
            "append": {
                "declared": True,
                "consumedByHub": True,
                "status": "supported",
                "routeMode": "prompt_async",
                "requiresStreamIdentity": False,
            },
            "promptAsync": {
                "declared": True,
                "consumedByHub": True,
                "availability": "always",
                "method": "shared.sessions.prompt_async",
                "enabledByDefault": None,
                "configKey": None,
            },
            "command": {
                "declared": True,
                "consumedByHub": True,
                "availability": "always",
                "method": "shared.sessions.command",
                "enabledByDefault": None,
                "configKey": None,
            },
            "shell": {
                "declared": False,
                "consumedByHub": False,
                "availability": "conditional",
                "method": None,
                "enabledByDefault": False,
                "configKey": "A2A_ENABLE_SESSION_SHELL",
            },
        },
        "invokeMetadata": {
            "declared": False,
            "consumedByHub": True,
            "status": "unsupported",
            "metadataField": None,
            "appliesToMethods": [],
            "fields": [],
            "error": None,
        },
        "requestExecutionOptions": {
            "declared": False,
            "consumedByHub": False,
            "status": "unsupported",
            "metadataField": None,
            "fields": [],
            "persistsForThread": None,
            "sourceExtensions": [],
            "notes": [],
            "error": None,
        },
        "streamHints": {
            "declared": False,
            "consumedByHub": False,
            "status": "unsupported",
            "streamField": None,
            "usageField": None,
            "interruptField": None,
            "sessionField": None,
            "mode": None,
            "fallbackUsed": None,
            "error": None,
        },
        "wireContract": {
            "declared": True,
            "consumedByHub": True,
            "status": "invalid",
            "protocolVersion": None,
            "preferredTransport": None,
            "additionalTransports": [],
            "allJsonrpcMethods": [],
            "extensionUris": [],
            "conditionalMethods": {},
            "unsupportedMethodError": None,
            "error": "Extension contract missing/invalid 'params.extensions.jsonrpc_methods'",
        },
        "compatibilityProfile": {
            "declared": True,
            "status": "invalid",
            "uri": None,
            "advisoryOnly": True,
            "usedFor": ["diagnostics", "retention_hints"],
            "extensionRetentionCount": 0,
            "methodRetentionCount": 0,
            "serviceBehaviorKeys": [],
            "consumerGuidance": [],
            "error": "Extension contract missing/invalid 'params.method_retention'",
        },
        "upstreamMethodFamilies": {
            "discovery": {
                "declared": False,
                "consumedByHub": False,
                "status": "unsupported",
                "methods": {},
                "declarationSource": None,
                "declarationConfidence": None,
                "negotiationState": None,
                "diagnosticNote": None,
            },
            "threads": {
                "declared": False,
                "consumedByHub": False,
                "status": "unsupported",
                "methods": {},
                "declarationSource": None,
                "declarationConfidence": None,
                "negotiationState": None,
                "diagnosticNote": None,
            },
            "turns": {
                "declared": False,
                "consumedByHub": False,
                "status": "unsupported",
                "methods": {},
                "declarationSource": None,
                "declarationConfidence": None,
                "negotiationState": None,
                "diagnosticNote": None,
            },
            "review": {
                "declared": False,
                "consumedByHub": False,
                "status": "unsupported",
                "methods": {},
                "declarationSource": None,
                "declarationConfidence": None,
                "negotiationState": None,
                "diagnosticNote": None,
            },
            "exec": {
                "declared": False,
                "consumedByHub": False,
                "status": "unsupported",
                "declarationSource": None,
                "declarationConfidence": None,
                "negotiationState": None,
                "diagnosticNote": None,
                "methods": {},
            },
        },
        "runtimeStatus": runtime_status_contract_payload(),
    }


@pytest.mark.asyncio
async def test_hub_generic_model_discovery_routes_forward_working_directory(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_model_discovery@example.com",
        user_email="alice_model_discovery@example.com",
        token="secret-token-model-discovery",
    )

    fake_extensions = _FakeExtensionsService()
    monkeypatch.setattr(
        extension_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    async with create_test_client(
        hub_extension_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        providers_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/models/providers:list",
            json={"workingDirectory": "/workspace"},
        )
        assert providers_resp.status_code == 200
        providers_payload = providers_resp.json()
        assert providers_payload["success"] is True
        assert providers_payload["result"]["items"][0]["provider_id"] == "openai"

        models_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/models:list",
            json={
                "provider_id": "openai",
                "workingDirectory": "/workspace",
            },
        )
        assert models_resp.status_code == 200
        models_payload = models_resp.json()
        assert models_payload["success"] is True
        assert models_payload["result"]["items"][0]["model_id"] == "gpt-5"

    assert len(fake_extensions.calls) == 2
    assert fake_extensions.calls[0]["fn"] == "list_model_providers"
    assert fake_extensions.calls[0]["session_metadata"] is None
    assert fake_extensions.calls[0]["working_directory"] == "/workspace"
    assert fake_extensions.calls[1]["fn"] == "list_models"
    assert fake_extensions.calls[1]["provider_id"] == "openai"
    assert fake_extensions.calls[1]["session_metadata"] is None
    assert fake_extensions.calls[1]["working_directory"] == "/workspace"
    for call in fake_extensions.calls:
        resolved = call["runtime"].resolved
        assert resolved.headers["Authorization"].endswith(
            "secret-token-model-discovery"
        )


@pytest.mark.asyncio
async def test_hub_upstream_discovery_routes_return_normalized_results(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_upstream_discovery@example.com",
        user_email="alice_upstream_discovery@example.com",
        token="secret-token-upstream-discovery",
    )

    fake_extensions = _FakeExtensionsService()
    monkeypatch.setattr(
        extension_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    async with create_test_client(
        hub_extension_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        skills_resp = await user_client.get(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/upstream/skills"
        )
        assert skills_resp.status_code == 200
        skills_payload = skills_resp.json()
        assert skills_payload["success"] is True
        assert (
            skills_payload["result"]["items"][0]["skills"][0]["path"]
            == "/workspace/project/.codex/skills/PLANNING/SKILL.md"
        )

        plugin_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/upstream/plugins:read",
            json={
                "marketplacePath": "/workspace/project/.codex/plugins/marketplace.json",
                "pluginName": "planner",
            },
        )
        assert plugin_resp.status_code == 200
        plugin_payload = plugin_resp.json()
        assert plugin_payload["success"] is True
        assert plugin_payload["result"]["item"]["name"] == "planner"
        assert plugin_payload["result"]["item"]["marketplacePath"] == (
            "/workspace/project/.codex/plugins/marketplace.json"
        )
        assert plugin_payload["result"]["item"]["summary"] == ["Use for planning"]

    assert fake_extensions.calls[0]["fn"] == "list_upstream_skills"
    assert fake_extensions.calls[1]["fn"] == "read_upstream_plugin"
    assert fake_extensions.calls[1]["marketplace_path"] == (
        "/workspace/project/.codex/plugins/marketplace.json"
    )
    assert fake_extensions.calls[1]["plugin_name"] == "planner"
