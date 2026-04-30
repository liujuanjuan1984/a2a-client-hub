from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from a2a.types import AgentCard

from app.integrations.a2a_extensions import capability_snapshot_builder
from app.integrations.a2a_extensions.capability_snapshot import (
    CompatibilityProfileCapabilitySnapshot,
    DeclaredMethodCapabilitySnapshot,
    DeclaredMethodCollectionCapabilitySnapshot,
    DeclaredSingleMethodCapabilitySnapshot,
    InterruptCallbackCapabilitySnapshot,
    InterruptRecoveryCapabilitySnapshot,
    InvokeMetadataCapabilitySnapshot,
    ModelSelectionCapabilitySnapshot,
    ProviderDiscoveryCapabilitySnapshot,
    RequestExecutionOptionsCapabilitySnapshot,
    ResolvedCapabilitySnapshot,
    SessionBindingCapabilitySnapshot,
    SessionQueryCapabilitySnapshot,
    StreamHintsCapabilitySnapshot,
    WireContractCapabilitySnapshot,
)
from app.integrations.a2a_extensions.errors import A2AExtensionContractError
from app.integrations.a2a_extensions.service import A2AExtensionsService
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.session_extension_service import (
    SessionExtensionService,
)
from app.integrations.a2a_extensions.session_query_runtime_selection import (
    ResolvedSessionQueryRuntimeCapability,
)
from app.integrations.a2a_extensions.shared_contract import (
    COMPATIBILITY_PROFILE_URI,
    INTERRUPT_RECOVERY_URI,
    INVOKE_METADATA_URI,
    OPENCODE_WIRE_CONTRACT_URI,
    PROVIDER_DISCOVERY_URI,
    SHARED_INTERRUPT_CALLBACK_URI,
    SHARED_INVOKE_FIELD,
    SHARED_SESSION_BINDING_URI,
    SHARED_SESSION_ID_FIELD,
    SHARED_SESSION_QUERY_URI,
    STREAM_HINTS_URI,
)
from app.integrations.a2a_extensions.shared_support import A2AExtensionSupport
from app.integrations.a2a_extensions.types import (
    CompatibilityRetentionEntry,
    JsonRpcInterface,
    MessageCursorPaginationContract,
    PageSizePagination,
    ResolvedCompatibilityProfileExtension,
    ResolvedConditionalMethodAvailability,
    ResolvedExtension,
    ResolvedInterruptCallbackExtension,
    ResolvedInterruptRecoveryExtension,
    ResolvedInvokeMetadataExtension,
    ResolvedInvokeMetadataField,
    ResolvedModelSelectionExtension,
    ResolvedProviderDiscoveryExtension,
    ResolvedSessionControlMethodCapability,
    ResolvedStreamHintsExtension,
    ResolvedUnsupportedMethodErrorContract,
    ResolvedWireContractExtension,
    ResultEnvelopeMapping,
    SessionListFilterFieldContract,
    SessionListFiltersContract,
)


def _session_query_snapshot(
    ext: ResolvedExtension,
    *,
    compatibility_hints_applied: bool = False,
) -> SessionQueryCapabilitySnapshot:
    control_methods = {
        "prompt_async": ResolvedSessionControlMethodCapability(
            method=ext.methods.get("prompt_async"),
            declared=bool(ext.methods.get("prompt_async")),
            availability="always" if ext.methods.get("prompt_async") else "unsupported",
        ),
        "command": ResolvedSessionControlMethodCapability(
            method=ext.methods.get("command"),
            declared=bool(ext.methods.get("command")),
            availability="always" if ext.methods.get("command") else "unsupported",
        ),
        "shell": ResolvedSessionControlMethodCapability(
            method=ext.methods.get("shell"),
            declared=bool(ext.methods.get("shell")),
            availability="conditional" if ext.methods.get("shell") else "unsupported",
            enabled_by_default=False if ext.methods.get("shell") else None,
            config_key="A2A_ENABLE_SESSION_SHELL" if ext.methods.get("shell") else None,
        ),
    }
    return SessionQueryCapabilitySnapshot(
        status="supported",
        capability=ResolvedSessionQueryRuntimeCapability(
            ext=ext,
            negotiation_mode="declared_contract",
            compatibility_hints_applied=compatibility_hints_applied,
            control_methods=control_methods,
        ),
    )


def _binding_snapshot(
    *,
    status: str = "supported",
    ext=None,
    error: str | None = None,
    meta: dict | None = None,
) -> SessionBindingCapabilitySnapshot:
    return SessionBindingCapabilitySnapshot(
        status=status,
        ext=ext,
        error=error,
        meta=meta or {},
    )


def _invoke_metadata_snapshot(
    *,
    status: str = "supported",
    ext: ResolvedInvokeMetadataExtension | None = None,
    error: str | None = None,
    meta: dict | None = None,
) -> InvokeMetadataCapabilitySnapshot:
    return InvokeMetadataCapabilitySnapshot(
        status=status,
        ext=ext,
        error=error,
        meta=meta or {},
    )


def _interrupt_snapshot(
    *,
    status: str = "unsupported",
    ext: ResolvedInterruptCallbackExtension | None = None,
    jsonrpc_url: str | None = None,
    error: str | None = None,
) -> InterruptCallbackCapabilitySnapshot:
    return InterruptCallbackCapabilitySnapshot(
        status=status,
        ext=ext,
        jsonrpc_url=jsonrpc_url,
        error=error,
    )


def _provider_discovery_snapshot(
    *,
    status: str = "unsupported",
    ext: ResolvedProviderDiscoveryExtension | None = None,
    jsonrpc_url: str | None = None,
    error: str | None = None,
) -> ProviderDiscoveryCapabilitySnapshot:
    return ProviderDiscoveryCapabilitySnapshot(
        status=status,
        ext=ext,
        jsonrpc_url=jsonrpc_url,
        error=error,
    )


def _interrupt_recovery_snapshot(
    *,
    status: str = "unsupported",
    ext: ResolvedInterruptRecoveryExtension | None = None,
    jsonrpc_url: str | None = None,
    error: str | None = None,
) -> InterruptRecoveryCapabilitySnapshot:
    return InterruptRecoveryCapabilitySnapshot(
        status=status,
        ext=ext,
        jsonrpc_url=jsonrpc_url,
        error=error,
    )


def _model_selection_snapshot(
    *,
    status: str = "unsupported",
    ext: ResolvedModelSelectionExtension | None = None,
    error: str | None = None,
    meta: dict | None = None,
) -> ModelSelectionCapabilitySnapshot:
    return ModelSelectionCapabilitySnapshot(
        status=status,
        ext=ext,
        error=error,
        meta=meta or {},
    )


def _compatibility_profile_snapshot(
    *,
    status: str = "unsupported",
    ext: ResolvedCompatibilityProfileExtension | None = None,
    error: str | None = None,
) -> CompatibilityProfileCapabilitySnapshot:
    return CompatibilityProfileCapabilitySnapshot(
        status=status,
        ext=ext,
        error=error,
    )


def _wire_contract_snapshot(
    *,
    status: str = "unsupported",
    ext: ResolvedWireContractExtension | None = None,
    error: str | None = None,
) -> WireContractCapabilitySnapshot:
    return WireContractCapabilitySnapshot(
        status=status,
        ext=ext,
        error=error,
    )


def _capability_snapshot(
    *,
    session_query: SessionQueryCapabilitySnapshot,
    session_binding: SessionBindingCapabilitySnapshot | None = None,
    invoke_metadata: InvokeMetadataCapabilitySnapshot | None = None,
    request_execution_options: RequestExecutionOptionsCapabilitySnapshot | None = None,
    interrupt_callback: InterruptCallbackCapabilitySnapshot | None = None,
    interrupt_recovery: InterruptRecoveryCapabilitySnapshot | None = None,
    model_selection: ModelSelectionCapabilitySnapshot | None = None,
    provider_discovery: ProviderDiscoveryCapabilitySnapshot | None = None,
    stream_hints: StreamHintsCapabilitySnapshot | None = None,
    wire_contract: WireContractCapabilitySnapshot | None = None,
    compatibility_profile: CompatibilityProfileCapabilitySnapshot | None = None,
    codex_discovery: DeclaredMethodCollectionCapabilitySnapshot | None = None,
    codex_threads: DeclaredMethodCollectionCapabilitySnapshot | None = None,
    codex_turns: DeclaredMethodCollectionCapabilitySnapshot | None = None,
    codex_review: DeclaredMethodCollectionCapabilitySnapshot | None = None,
    codex_thread_watch: DeclaredSingleMethodCapabilitySnapshot | None = None,
    codex_exec: DeclaredMethodCollectionCapabilitySnapshot | None = None,
) -> ResolvedCapabilitySnapshot:
    return ResolvedCapabilitySnapshot(
        session_query=session_query,
        session_binding=session_binding or _binding_snapshot(status="unsupported"),
        invoke_metadata=invoke_metadata
        or _invoke_metadata_snapshot(status="unsupported"),
        request_execution_options=request_execution_options
        or RequestExecutionOptionsCapabilitySnapshot(
            status="unsupported",
            declared=False,
            consumed_by_hub=False,
        ),
        interrupt_callback=interrupt_callback or _interrupt_snapshot(),
        interrupt_recovery=interrupt_recovery or _interrupt_recovery_snapshot(),
        model_selection=model_selection or _model_selection_snapshot(),
        provider_discovery=provider_discovery or _provider_discovery_snapshot(),
        stream_hints=stream_hints
        or StreamHintsCapabilitySnapshot(status="unsupported", meta={}),
        wire_contract=wire_contract or _wire_contract_snapshot(),
        compatibility_profile=compatibility_profile
        or _compatibility_profile_snapshot(),
        codex_discovery=codex_discovery
        or DeclaredMethodCollectionCapabilitySnapshot(
            declared=False,
            consumed_by_hub=False,
            status="unsupported",
            methods={},
        ),
        codex_threads=codex_threads
        or DeclaredMethodCollectionCapabilitySnapshot(
            declared=False,
            consumed_by_hub=False,
            status="unsupported",
            methods={},
        ),
        codex_turns=codex_turns
        or DeclaredMethodCollectionCapabilitySnapshot(
            declared=False,
            consumed_by_hub=False,
            status="unsupported",
            methods={},
        ),
        codex_review=codex_review
        or DeclaredMethodCollectionCapabilitySnapshot(
            declared=False,
            consumed_by_hub=False,
            status="unsupported",
            methods={},
        ),
        codex_thread_watch=codex_thread_watch
        or DeclaredSingleMethodCapabilitySnapshot(
            declared=False,
            consumed_by_hub=False,
            status="unsupported",
        ),
        codex_exec=codex_exec
        or DeclaredMethodCollectionCapabilitySnapshot(
            declared=False,
            consumed_by_hub=False,
            status="unsupported",
            methods={},
        ),
    )


def _invoke_metadata_extension_fixture() -> ResolvedInvokeMetadataExtension:
    return ResolvedInvokeMetadataExtension(
        uri=INVOKE_METADATA_URI,
        required=False,
        provider="commonground",
        metadata_field=SHARED_INVOKE_FIELD,
        behavior="merge_bound_metadata_into_invoke",
        applies_to_methods=("message/send", "message/stream"),
        fields=(
            ResolvedInvokeMetadataField(
                name="project_id",
                required=True,
                description="Project scope.",
            ),
            ResolvedInvokeMetadataField(
                name="channel_id",
                required=True,
                description="Channel scope.",
            ),
        ),
        supported_metadata=(
            "shared.invoke.bindings.project_id",
            "shared.invoke.bindings.channel_id",
        ),
    )


def _resolved_extension(
    *,
    supports_offset: bool = False,
    supports_cursor: bool = False,
    session_list_filters: SessionListFiltersContract | None = None,
) -> ResolvedExtension:
    return ResolvedExtension(
        uri=SHARED_SESSION_QUERY_URI,
        required=False,
        provider="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={
            "list_sessions": "shared.sessions.list",
            "get_session": "shared.sessions.get",
            "get_session_children": "shared.sessions.children",
            "get_session_todo": "shared.sessions.todo",
            "get_session_diff": "shared.sessions.diff",
            "get_session_message": "shared.sessions.messages.get",
            "get_session_messages": "shared.sessions.messages.list",
            "prompt_async": "shared.sessions.prompt_async",
            "command": "shared.sessions.command",
            "fork": "shared.sessions.fork",
            "share": "shared.sessions.share",
            "unshare": "shared.sessions.unshare",
            "summarize": "shared.sessions.summarize",
            "revert": "shared.sessions.revert",
            "unrevert": "shared.sessions.unrevert",
            "shell": None,
        },
        pagination=PageSizePagination(
            mode="limit",
            default_size=20,
            max_size=100,
            params=("limit", "offset") if supports_offset else ("limit",),
            supports_offset=supports_offset,
        ),
        business_code_map={
            -32001: "session_not_found",
            -32005: "upstream_payload_error",
            -32006: "session_forbidden",
        },
        result_envelope=ResultEnvelopeMapping(),
        message_cursor_pagination=MessageCursorPaginationContract(
            cursor_param="before" if supports_cursor else None,
            result_cursor_field="next_cursor" if supports_cursor else None,
        ),
        session_list_filters=session_list_filters or SessionListFiltersContract(),
    )


def _interrupt_extension_fixture() -> ResolvedInterruptCallbackExtension:
    return ResolvedInterruptCallbackExtension(
        uri=SHARED_INTERRUPT_CALLBACK_URI,
        required=False,
        provider="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={
            "reply_permission": None,
            "reply_question": None,
            "reject_question": None,
            "reply_permissions": None,
            "reply_elicitation": None,
        },
        business_code_map={},
    )


def _compatibility_profile_extension_fixture() -> ResolvedCompatibilityProfileExtension:
    return ResolvedCompatibilityProfileExtension(
        uri=COMPATIBILITY_PROFILE_URI,
        required=False,
        extension_retention={
            SHARED_SESSION_QUERY_URI: CompatibilityRetentionEntry(
                surface="jsonrpc-extension",
                availability="always",
                retention="stable",
            )
        },
        method_retention={
            "opencode.sessions.command": CompatibilityRetentionEntry(
                surface="extension",
                availability="always",
                retention="stable",
                extension_uri=SHARED_SESSION_QUERY_URI,
            ),
            "opencode.sessions.shell": CompatibilityRetentionEntry(
                surface="extension",
                availability="disabled",
                retention="deployment-conditional",
                extension_uri=SHARED_SESSION_QUERY_URI,
                toggle="A2A_ENABLE_SESSION_SHELL",
            ),
        },
        service_behaviors={
            "classification": "stable-service-semantics",
            "methods": {"tasks/cancel": {"retention": "stable"}},
        },
        consumer_guidance=(
            "Treat opencode.sessions.shell as deployment-conditional.",
            "Treat opencode.sessions.* as provider-private operational surfaces.",
        ),
    )


def _provider_discovery_extension_fixture() -> ResolvedProviderDiscoveryExtension:
    return ResolvedProviderDiscoveryExtension(
        uri=PROVIDER_DISCOVERY_URI,
        required=False,
        provider="opencode",
        metadata_namespace="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={
            "list_providers": "providers.list",
            "list_models": "models.list",
        },
        business_code_map={},
    )


def _wire_contract_extension_fixture(
    *,
    all_jsonrpc_methods: tuple[str, ...] = (
        "shared.sessions.list",
        "shared.sessions.get",
        "shared.sessions.children",
        "shared.sessions.todo",
        "shared.sessions.diff",
        "shared.sessions.messages.get",
        "shared.sessions.messages.list",
        "shared.sessions.prompt_async",
        "shared.sessions.command",
        "shared.sessions.fork",
        "shared.sessions.share",
        "shared.sessions.unshare",
        "shared.sessions.summarize",
        "shared.sessions.revert",
        "shared.sessions.unrevert",
        "providers.list",
        "models.list",
    ),
    conditional_methods: dict[str, ResolvedConditionalMethodAvailability] | None = None,
) -> ResolvedWireContractExtension:
    return ResolvedWireContractExtension(
        uri=OPENCODE_WIRE_CONTRACT_URI,
        required=False,
        protocol_version="0.3.0",
        preferred_transport="HTTP+JSON",
        additional_transports=("JSON-RPC",),
        core_jsonrpc_methods=(
            "agent/getAuthenticatedExtendedCard",
            "tasks/pushNotificationConfig/get",
        ),
        core_http_endpoints=("GET /v1/tasks",),
        extension_jsonrpc_methods=(
            "shared.sessions.list",
            "shared.sessions.get",
            "shared.sessions.children",
            "shared.sessions.todo",
            "shared.sessions.diff",
            "shared.sessions.messages.get",
            "shared.sessions.messages.list",
            "shared.sessions.prompt_async",
            "shared.sessions.command",
            "shared.sessions.fork",
            "shared.sessions.share",
            "shared.sessions.unshare",
            "shared.sessions.summarize",
            "shared.sessions.revert",
            "shared.sessions.unrevert",
            "providers.list",
            "models.list",
        ),
        conditionally_available_methods=conditional_methods or {},
        extension_uris=(
            SHARED_SESSION_QUERY_URI,
            PROVIDER_DISCOVERY_URI,
        ),
        all_jsonrpc_methods=all_jsonrpc_methods,
        service_behaviors={"classification": "stable-service-semantics"},
        unsupported_method_error=ResolvedUnsupportedMethodErrorContract(
            code=-32601,
            type="METHOD_NOT_SUPPORTED",
            data_fields=("type", "method", "supported_methods", "protocol_version"),
        ),
    )


def _interrupt_recovery_extension_fixture() -> ResolvedInterruptRecoveryExtension:
    return ResolvedInterruptRecoveryExtension(
        uri=INTERRUPT_RECOVERY_URI,
        required=False,
        provider="opencode",
        jsonrpc=JsonRpcInterface(
            url="https://example.com/jsonrpc", fallback_used=False
        ),
        methods={
            "list": None,
            "list_permissions": "opencode.permissions.list",
            "list_questions": "opencode.questions.list",
        },
        business_code_map={},
        recovery_data_source="local_interrupt_binding_registry",
        identity_scope="current_authenticated_caller",
        implementation_scope="adapter-local",
        empty_result_when_identity_unavailable=True,
    )


def _stream_hints_snapshot(
    *,
    status: str = "supported",
    ext: ResolvedStreamHintsExtension | None = None,
    error: str | None = None,
    meta: dict | None = None,
) -> StreamHintsCapabilitySnapshot:
    return StreamHintsCapabilitySnapshot(
        status=status,
        ext=ext,
        error=error,
        meta=meta or {},
    )


def _stream_hints_extension_fixture() -> ResolvedStreamHintsExtension:
    return ResolvedStreamHintsExtension(
        uri=STREAM_HINTS_URI,
        required=False,
        provider="opencode",
        stream_field="metadata.shared.stream",
        usage_field="metadata.shared.usage",
        interrupt_field="metadata.shared.interrupt",
        session_field="metadata.shared.session",
    )


__all__ = [
    "A2AExtensionContractError",
    "A2AExtensionSupport",
    "A2AExtensionsService",
    "AgentCard",
    "Any",
    "COMPATIBILITY_PROFILE_URI",
    "CompatibilityRetentionEntry",
    "DeclaredMethodCapabilitySnapshot",
    "DeclaredMethodCollectionCapabilitySnapshot",
    "DeclaredSingleMethodCapabilitySnapshot",
    "ExtensionCallResult",
    "INTERRUPT_RECOVERY_URI",
    "INVOKE_METADATA_URI",
    "JsonRpcInterface",
    "OPENCODE_WIRE_CONTRACT_URI",
    "PROVIDER_DISCOVERY_URI",
    "ResolvedCompatibilityProfileExtension",
    "ResolvedConditionalMethodAvailability",
    "ResolvedExtension",
    "ResolvedInterruptCallbackExtension",
    "ResolvedInterruptRecoveryExtension",
    "ResultEnvelopeMapping",
    "SHARED_INTERRUPT_CALLBACK_URI",
    "SHARED_INVOKE_FIELD",
    "SHARED_SESSION_BINDING_URI",
    "SHARED_SESSION_ID_FIELD",
    "SHARED_SESSION_QUERY_URI",
    "SessionExtensionService",
    "SessionListFilterFieldContract",
    "SessionListFiltersContract",
    "SimpleNamespace",
    "_binding_snapshot",
    "_capability_snapshot",
    "_compatibility_profile_snapshot",
    "_interrupt_extension_fixture",
    "_interrupt_recovery_extension_fixture",
    "_interrupt_recovery_snapshot",
    "_interrupt_snapshot",
    "_provider_discovery_extension_fixture",
    "_provider_discovery_snapshot",
    "_resolved_extension",
    "_session_query_snapshot",
    "_wire_contract_extension_fixture",
    "_wire_contract_snapshot",
    "capability_snapshot_builder",
    "pytest",
]
