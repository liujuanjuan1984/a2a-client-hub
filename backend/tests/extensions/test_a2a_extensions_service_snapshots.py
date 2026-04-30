from __future__ import annotations

from tests.extensions.a2a_extensions_service_support import (
    COMPATIBILITY_PROFILE_URI,
    INTERRUPT_RECOVERY_URI,
    OPENCODE_WIRE_CONTRACT_URI,
    SHARED_SESSION_BINDING_URI,
    SHARED_SESSION_QUERY_URI,
    A2AExtensionsService,
    CompatibilityRetentionEntry,
    DeclaredMethodCapabilitySnapshot,
    DeclaredSingleMethodCapabilitySnapshot,
    ResolvedCompatibilityProfileExtension,
    ResolvedConditionalMethodAvailability,
    SimpleNamespace,
    _compatibility_profile_snapshot,
    _wire_contract_extension_fixture,
    _wire_contract_snapshot,
    capability_snapshot_builder,
)
from tests.support.a2a import parse_agent_card


def test_build_interrupt_recovery_snapshot_preserves_scope_metadata() -> None:
    service = A2AExtensionsService()
    card = parse_agent_card(
        {
            "name": "Example Agent",
            "description": "Example",
            "version": "1.0",
            "supportedInterfaces": [
                {
                    "url": "https://example.com/jsonrpc",
                    "protocolBinding": "JSONRPC",
                }
            ],
            "capabilities": {
                "extensions": [
                    {
                        "uri": INTERRUPT_RECOVERY_URI,
                        "required": False,
                        "params": {
                            "provider": "opencode",
                            "methods": {
                                "list_permissions": "opencode.permissions.list",
                                "list_questions": "opencode.questions.list",
                            },
                            "recovery_scope": {
                                "data_source": "local_interrupt_binding_registry",
                                "identity_scope": "current_authenticated_caller",
                                "empty_result_when_identity_unavailable": True,
                            },
                            "errors": {"business_codes": {}},
                        },
                    }
                ]
            },
            "defaultInputModes": [],
            "defaultOutputModes": [],
            "skills": [{"id": "s1", "name": "s1", "description": "d", "tags": []}],
        }
    )

    service._support.ensure_outbound_allowed = lambda url, *, purpose: url
    snapshot = capability_snapshot_builder.build_interrupt_recovery_snapshot(
        service._support, card
    )

    assert snapshot.status == "supported"
    assert snapshot.ext is not None
    assert snapshot.ext.recovery_data_source == "local_interrupt_binding_registry"
    assert snapshot.ext.identity_scope == "current_authenticated_caller"
    assert snapshot.ext.empty_result_when_identity_unavailable is True


def test_build_compatibility_profile_snapshot_returns_supported_status() -> None:
    card = parse_agent_card(
        {
            "name": "Example Agent",
            "description": "Example",
            "version": "1.0",
            "supportedInterfaces": [
                {
                    "url": "https://example.com/jsonrpc",
                    "protocolBinding": "JSONRPC",
                }
            ],
            "capabilities": {
                "extensions": [
                    {
                        "uri": COMPATIBILITY_PROFILE_URI,
                        "required": False,
                        "params": {
                            "extension_retention": {
                                SHARED_SESSION_QUERY_URI: {
                                    "surface": "jsonrpc-extension",
                                    "availability": "always",
                                    "retention": "stable",
                                },
                                INTERRUPT_RECOVERY_URI: {
                                    "surface": "jsonrpc-extension",
                                    "availability": "always",
                                    "retention": "stable",
                                    "implementation_scope": "adapter-local",
                                    "identity_scope": "current_authenticated_caller",
                                },
                            },
                            "method_retention": {
                                "opencode.sessions.command": {
                                    "surface": "extension",
                                    "availability": "always",
                                    "retention": "stable",
                                    "extension_uri": SHARED_SESSION_QUERY_URI,
                                },
                                "opencode.permissions.list": {
                                    "surface": "extension",
                                    "availability": "always",
                                    "retention": "stable",
                                    "extension_uri": INTERRUPT_RECOVERY_URI,
                                    "implementation_scope": "adapter-local",
                                    "identity_scope": "current_authenticated_caller",
                                    "upstream_stability": "stable",
                                },
                            },
                            "service_behaviors": {
                                "classification": "stable-service-semantics",
                                "methods": {"tasks/cancel": {"retention": "stable"}},
                            },
                            "consumer_guidance": [
                                "Treat opencode.sessions.* as provider-private."
                            ],
                        },
                    }
                ]
            },
            "defaultInputModes": [],
            "defaultOutputModes": [],
            "skills": [{"id": "s1", "name": "s1", "description": "d", "tags": []}],
        }
    )

    snapshot = capability_snapshot_builder.build_compatibility_profile_snapshot(card)

    assert snapshot.status == "supported"
    assert snapshot.ext is not None
    assert snapshot.ext.method_retention["opencode.sessions.command"].retention == (
        "stable"
    )
    assert (
        snapshot.ext.extension_retention[INTERRUPT_RECOVERY_URI].implementation_scope
        == "adapter-local"
    )
    assert (
        snapshot.ext.method_retention["opencode.permissions.list"].identity_scope
        == "current_authenticated_caller"
    )
    assert (
        snapshot.ext.method_retention["opencode.permissions.list"].upstream_stability
        == "stable"
    )


def test_build_compatibility_profile_snapshot_allows_empty_retention_maps() -> None:
    card = parse_agent_card(
        {
            "name": "Example Agent",
            "description": "Example",
            "version": "1.0",
            "supportedInterfaces": [
                {
                    "url": "https://example.com/jsonrpc",
                    "protocolBinding": "JSONRPC",
                }
            ],
            "capabilities": {
                "extensions": [
                    {
                        "uri": COMPATIBILITY_PROFILE_URI,
                        "required": False,
                        "params": {
                            "extension_retention": {},
                            "method_retention": {},
                            "service_behaviors": {
                                "classification": "stable-service-semantics"
                            },
                            "consumer_guidance": [
                                "Treat opencode.sessions.* as provider-private."
                            ],
                        },
                    }
                ]
            },
            "defaultInputModes": [],
            "defaultOutputModes": [],
            "skills": [{"id": "s1", "name": "s1", "description": "d", "tags": []}],
        }
    )

    snapshot = capability_snapshot_builder.build_compatibility_profile_snapshot(card)

    assert snapshot.status == "supported"
    assert snapshot.ext is not None
    assert snapshot.ext.extension_retention == {}
    assert snapshot.ext.method_retention == {}


def test_build_codex_followup_snapshots_from_wire_contract_methods() -> None:
    card = SimpleNamespace(capabilities=SimpleNamespace(extensions=[]))
    wire_contract = _wire_contract_snapshot(
        status="supported",
        ext=_wire_contract_extension_fixture(
            all_jsonrpc_methods=(
                "shared.sessions.prompt_async",
                "codex.discovery.skills.list",
                "codex.discovery.plugins.read",
                "codex.turns.steer",
                "codex.threads.watch",
                "codex.exec.start",
                "codex.exec.terminate",
            )
        ),
    )

    compatibility_profile = _compatibility_profile_snapshot()
    discovery = capability_snapshot_builder.build_codex_discovery_snapshot(
        card,
        wire_contract,
        compatibility_profile,
        jsonrpc_url="https://example.com/jsonrpc",
    )
    threads = capability_snapshot_builder.build_codex_threads_snapshot(
        wire_contract,
        compatibility_profile,
        jsonrpc_url="https://example.com/jsonrpc",
    )
    turns = capability_snapshot_builder.build_codex_turns_snapshot(
        wire_contract,
        compatibility_profile,
        jsonrpc_url="https://example.com/jsonrpc",
    )
    review = capability_snapshot_builder.build_codex_review_snapshot(
        wire_contract,
        compatibility_profile,
        jsonrpc_url="https://example.com/jsonrpc",
    )
    thread_watch = capability_snapshot_builder.build_codex_thread_watch_snapshot(
        wire_contract,
        jsonrpc_url="https://example.com/jsonrpc",
    )
    exec_capability = capability_snapshot_builder.build_codex_exec_snapshot(
        wire_contract,
        compatibility_profile,
        jsonrpc_url="https://example.com/jsonrpc",
    )

    assert discovery.declared is True
    assert discovery.consumed_by_hub is True
    assert discovery.status == "supported"
    assert discovery.declaration_source == "wire_contract"
    assert discovery.declaration_confidence == "authoritative"
    assert discovery.negotiation_state == "supported"
    assert discovery.methods["skillsList"] == DeclaredMethodCapabilitySnapshot(
        declared=True,
        consumed_by_hub=True,
        method="codex.discovery.skills.list",
        availability="always",
    )
    assert discovery.methods["appsList"] == DeclaredMethodCapabilitySnapshot(
        declared=False,
        consumed_by_hub=False,
        method=None,
    )
    assert discovery.methods["pluginsRead"] == DeclaredMethodCapabilitySnapshot(
        declared=True,
        consumed_by_hub=True,
        method="codex.discovery.plugins.read",
        availability="always",
    )

    assert threads.declared is True
    assert threads.consumed_by_hub is False
    assert threads.status == "unsupported_by_design"
    assert threads.methods["fork"] == DeclaredMethodCapabilitySnapshot(
        declared=False,
        consumed_by_hub=False,
        method=None,
    )
    assert threads.methods["watch"] == DeclaredMethodCapabilitySnapshot(
        declared=True,
        consumed_by_hub=False,
        method="codex.threads.watch",
        availability="always",
    )

    assert turns.declared is True
    assert turns.consumed_by_hub is True
    assert turns.status == "supported"
    assert turns.methods["steer"] == DeclaredMethodCapabilitySnapshot(
        declared=True,
        consumed_by_hub=True,
        method="codex.turns.steer",
        availability="always",
    )

    assert review.declared is False
    assert review.consumed_by_hub is False
    assert review.status == "unsupported"
    assert review.methods["start"] == DeclaredMethodCapabilitySnapshot(
        declared=False,
        consumed_by_hub=False,
        method=None,
    )
    assert review.methods["watch"] == DeclaredMethodCapabilitySnapshot(
        declared=False,
        consumed_by_hub=False,
        method=None,
    )

    assert thread_watch == DeclaredSingleMethodCapabilitySnapshot(
        declared=True,
        consumed_by_hub=False,
        status="unsupported_by_design",
        method="codex.threads.watch",
        jsonrpc_url="https://example.com/jsonrpc",
    )

    assert exec_capability.declared is True
    assert exec_capability.consumed_by_hub is False
    assert exec_capability.status == "unsupported_by_design"
    assert exec_capability.methods["start"] == DeclaredMethodCapabilitySnapshot(
        declared=True,
        consumed_by_hub=False,
        method="codex.exec.start",
        availability="always",
    )
    assert exec_capability.methods["write"] == DeclaredMethodCapabilitySnapshot(
        declared=False,
        consumed_by_hub=False,
        method=None,
    )
    assert exec_capability.methods["terminate"] == DeclaredMethodCapabilitySnapshot(
        declared=True,
        consumed_by_hub=False,
        method="codex.exec.terminate",
        availability="always",
    )


def test_build_codex_followup_snapshots_return_unsupported_without_wire_contract() -> (
    None
):
    card = SimpleNamespace(capabilities=SimpleNamespace(extensions=[]))
    wire_contract = _wire_contract_snapshot(status="unsupported")

    compatibility_profile = _compatibility_profile_snapshot()
    discovery = capability_snapshot_builder.build_codex_discovery_snapshot(
        card, wire_contract, compatibility_profile, jsonrpc_url=None
    )
    threads = capability_snapshot_builder.build_codex_threads_snapshot(
        wire_contract, compatibility_profile, jsonrpc_url=None
    )
    turns = capability_snapshot_builder.build_codex_turns_snapshot(
        wire_contract, compatibility_profile, jsonrpc_url=None
    )
    review = capability_snapshot_builder.build_codex_review_snapshot(
        wire_contract, compatibility_profile, jsonrpc_url=None
    )
    thread_watch = capability_snapshot_builder.build_codex_thread_watch_snapshot(
        wire_contract, jsonrpc_url=None
    )
    exec_capability = capability_snapshot_builder.build_codex_exec_snapshot(
        wire_contract, compatibility_profile, jsonrpc_url=None
    )

    assert discovery.declared is False
    assert discovery.status == "unsupported"
    assert discovery.declaration_source == "none"
    assert discovery.declaration_confidence == "none"
    assert discovery.negotiation_state == "unsupported"
    assert all(method.declared is False for method in discovery.methods.values())

    assert threads.declared is False
    assert threads.status == "unsupported"
    assert all(method.declared is False for method in threads.methods.values())

    assert turns.declared is False
    assert turns.status == "unsupported"
    assert all(method.declared is False for method in turns.methods.values())

    assert review.declared is False
    assert review.status == "unsupported"
    assert all(method.declared is False for method in review.methods.values())

    assert thread_watch == DeclaredSingleMethodCapabilitySnapshot(
        declared=False,
        consumed_by_hub=False,
        status="unsupported",
        method=None,
        jsonrpc_url=None,
    )

    assert exec_capability.declared is False
    assert exec_capability.status == "unsupported"
    assert all(method.declared is False for method in exec_capability.methods.values())


def test_build_codex_conditional_snapshots_mark_disabled_methods() -> None:
    compatibility_profile = _compatibility_profile_snapshot(
        status="supported",
        ext=ResolvedCompatibilityProfileExtension(
            uri=COMPATIBILITY_PROFILE_URI,
            required=False,
            extension_retention={},
            method_retention={
                "codex.turns.steer": CompatibilityRetentionEntry(
                    surface="extension",
                    availability="disabled",
                    retention="deployment-conditional",
                    extension_uri="urn:codex-a2a:codex-turn-control/v1",
                    toggle="A2A_ENABLE_TURN_CONTROL",
                ),
                "codex.review.start": CompatibilityRetentionEntry(
                    surface="extension",
                    availability="disabled",
                    retention="deployment-conditional",
                    extension_uri="urn:codex-a2a:codex-review/v1",
                    toggle="A2A_ENABLE_REVIEW_CONTROL",
                ),
                "codex.review.watch": CompatibilityRetentionEntry(
                    surface="extension",
                    availability="disabled",
                    retention="deployment-conditional",
                    extension_uri="urn:codex-a2a:codex-review/v1",
                    toggle="A2A_ENABLE_REVIEW_CONTROL",
                ),
                "codex.exec.start": CompatibilityRetentionEntry(
                    surface="extension",
                    availability="disabled",
                    retention="deployment-conditional",
                    extension_uri="urn:codex-a2a:codex-exec/v1",
                    toggle="A2A_ENABLE_EXEC_CONTROL",
                ),
                "codex.exec.write": CompatibilityRetentionEntry(
                    surface="extension",
                    availability="disabled",
                    retention="deployment-conditional",
                    extension_uri="urn:codex-a2a:codex-exec/v1",
                    toggle="A2A_ENABLE_EXEC_CONTROL",
                ),
                "codex.exec.resize": CompatibilityRetentionEntry(
                    surface="extension",
                    availability="disabled",
                    retention="deployment-conditional",
                    extension_uri="urn:codex-a2a:codex-exec/v1",
                    toggle="A2A_ENABLE_EXEC_CONTROL",
                ),
                "codex.exec.terminate": CompatibilityRetentionEntry(
                    surface="extension",
                    availability="disabled",
                    retention="deployment-conditional",
                    extension_uri="urn:codex-a2a:codex-exec/v1",
                    toggle="A2A_ENABLE_EXEC_CONTROL",
                ),
            },
            service_behaviors={"classification": "stable-service-semantics"},
            consumer_guidance=(),
        ),
    )
    wire_contract = _wire_contract_snapshot(
        status="supported",
        ext=_wire_contract_extension_fixture(
            all_jsonrpc_methods=("codex.threads.watch",),
            conditional_methods={
                "codex.turns.steer": ResolvedConditionalMethodAvailability(
                    reason="disabled_by_configuration",
                    toggle="A2A_ENABLE_TURN_CONTROL",
                ),
                "codex.review.start": ResolvedConditionalMethodAvailability(
                    reason="disabled_by_configuration",
                    toggle="A2A_ENABLE_REVIEW_CONTROL",
                ),
                "codex.review.watch": ResolvedConditionalMethodAvailability(
                    reason="disabled_by_configuration",
                    toggle="A2A_ENABLE_REVIEW_CONTROL",
                ),
                "codex.exec.start": ResolvedConditionalMethodAvailability(
                    reason="disabled_by_configuration",
                    toggle="A2A_ENABLE_EXEC_CONTROL",
                ),
                "codex.exec.write": ResolvedConditionalMethodAvailability(
                    reason="disabled_by_configuration",
                    toggle="A2A_ENABLE_EXEC_CONTROL",
                ),
                "codex.exec.resize": ResolvedConditionalMethodAvailability(
                    reason="disabled_by_configuration",
                    toggle="A2A_ENABLE_EXEC_CONTROL",
                ),
                "codex.exec.terminate": ResolvedConditionalMethodAvailability(
                    reason="disabled_by_configuration",
                    toggle="A2A_ENABLE_EXEC_CONTROL",
                ),
            },
        ),
    )

    turns = capability_snapshot_builder.build_codex_turns_snapshot(
        wire_contract,
        compatibility_profile,
        jsonrpc_url="https://example.com/jsonrpc",
    )
    review = capability_snapshot_builder.build_codex_review_snapshot(
        wire_contract,
        compatibility_profile,
        jsonrpc_url="https://example.com/jsonrpc",
    )
    exec_capability = capability_snapshot_builder.build_codex_exec_snapshot(
        wire_contract,
        compatibility_profile,
        jsonrpc_url="https://example.com/jsonrpc",
    )

    assert turns.declared is True
    assert turns.consumed_by_hub is False
    assert turns.status == "declared_not_consumed"
    assert turns.methods["steer"] == DeclaredMethodCapabilitySnapshot(
        declared=True,
        consumed_by_hub=False,
        method="codex.turns.steer",
        availability="disabled",
        config_key="A2A_ENABLE_TURN_CONTROL",
        reason="disabled_by_configuration",
        retention="deployment-conditional",
    )

    assert review.declared is True
    assert review.methods["watch"] == DeclaredMethodCapabilitySnapshot(
        declared=True,
        consumed_by_hub=False,
        method="codex.review.watch",
        availability="disabled",
        config_key="A2A_ENABLE_REVIEW_CONTROL",
        reason="disabled_by_configuration",
        retention="deployment-conditional",
    )

    assert exec_capability.declared is True
    assert exec_capability.methods["start"] == DeclaredMethodCapabilitySnapshot(
        declared=True,
        consumed_by_hub=False,
        method="codex.exec.start",
        availability="disabled",
        config_key="A2A_ENABLE_EXEC_CONTROL",
        reason="disabled_by_configuration",
        retention="deployment-conditional",
    )


def test_build_codex_discovery_snapshot_uses_wire_contract_fallback_hints() -> None:
    card = SimpleNamespace(
        capabilities=SimpleNamespace(
            extensions=[
                SimpleNamespace(
                    uri=OPENCODE_WIRE_CONTRACT_URI,
                    params={
                        "all_jsonrpc_methods": [
                            "codex.discovery.skills.list",
                            "codex.discovery.plugins.read",
                        ]
                    },
                )
            ]
        )
    )
    wire_contract = _wire_contract_snapshot(
        status="invalid",
        error="Extension contract missing/invalid 'params.protocol_version'",
    )

    discovery = capability_snapshot_builder.build_codex_discovery_snapshot(
        card,
        wire_contract,
        _compatibility_profile_snapshot(),
        jsonrpc_url="https://example.com/jsonrpc",
    )

    assert discovery.declared is True
    assert discovery.consumed_by_hub is False
    assert discovery.status == "unsupported"
    assert discovery.jsonrpc_url is None
    assert discovery.declaration_source == "wire_contract_fallback"
    assert discovery.declaration_confidence == "fallback"
    assert discovery.negotiation_state == "invalid"
    assert discovery.methods["skillsList"] == DeclaredMethodCapabilitySnapshot(
        declared=True,
        consumed_by_hub=False,
        method="codex.discovery.skills.list",
        availability="always",
    )
    assert discovery.methods["pluginsRead"] == DeclaredMethodCapabilitySnapshot(
        declared=True,
        consumed_by_hub=False,
        method="codex.discovery.plugins.read",
        availability="always",
    )


def test_build_request_execution_options_snapshot_collects_declared_contracts() -> None:
    card = SimpleNamespace(
        capabilities=SimpleNamespace(
            extensions=[
                SimpleNamespace(
                    uri=SHARED_SESSION_BINDING_URI,
                    params={
                        "request_execution_options": {
                            "metadata_field": "metadata.codex.execution",
                            "fields": ["model", "effort"],
                            "persists_for_thread": True,
                            "notes": ["Binding notes"],
                        }
                    },
                ),
                SimpleNamespace(
                    uri=SHARED_SESSION_QUERY_URI,
                    params={
                        "request_execution_options": {
                            "metadata_field": "metadata.codex.execution",
                            "fields": ["summary", "personality"],
                            "persists_for_thread": True,
                            "notes": ["Query notes"],
                        }
                    },
                ),
            ]
        )
    )

    snapshot = capability_snapshot_builder.build_request_execution_options_snapshot(
        card
    )

    assert snapshot.status == "supported"
    assert snapshot.declared is True
    assert snapshot.consumed_by_hub is True
    assert snapshot.metadata_field == "metadata.codex.execution"
    assert snapshot.fields == ("model", "effort", "summary", "personality")
    assert snapshot.persists_for_thread is True
    assert snapshot.source_extensions == (
        SHARED_SESSION_BINDING_URI,
        SHARED_SESSION_QUERY_URI,
    )
    assert snapshot.notes == ("Binding notes", "Query notes")


def test_build_request_execution_options_snapshot_reports_invalid_contract() -> None:
    card = SimpleNamespace(
        capabilities=SimpleNamespace(
            extensions=[
                SimpleNamespace(
                    uri=SHARED_SESSION_QUERY_URI,
                    params={
                        "request_execution_options": {
                            "metadata_field": "metadata.shared.invoke",
                            "fields": ["model"],
                        }
                    },
                )
            ]
        )
    )

    snapshot = capability_snapshot_builder.build_request_execution_options_snapshot(
        card
    )

    assert snapshot.status == "invalid"
    assert snapshot.declared is True
    assert snapshot.consumed_by_hub is False
    assert snapshot.error == (
        "Extension contract missing/invalid "
        "'params.request_execution_options.metadata_field'"
    )


def test_build_codex_discovery_snapshot_uses_extension_method_hints() -> None:
    card = SimpleNamespace(
        capabilities=SimpleNamespace(
            extensions=[
                SimpleNamespace(
                    uri="urn:example:codex-discovery:v1",
                    params={
                        "methods": {
                            "appsList": "codex.discovery.apps.list",
                        }
                    },
                )
            ]
        )
    )
    wire_contract = _wire_contract_snapshot(status="unsupported")

    discovery = capability_snapshot_builder.build_codex_discovery_snapshot(
        card,
        wire_contract,
        _compatibility_profile_snapshot(),
        jsonrpc_url="https://example.com/jsonrpc",
    )

    assert discovery.declared is True
    assert discovery.consumed_by_hub is False
    assert discovery.status == "unsupported"
    assert discovery.declaration_source == "extension_method_hint"
    assert discovery.declaration_confidence == "fallback"
    assert discovery.negotiation_state == "missing"
    assert discovery.methods["appsList"] == DeclaredMethodCapabilitySnapshot(
        declared=True,
        consumed_by_hub=False,
        method="codex.discovery.apps.list",
        availability="always",
    )
