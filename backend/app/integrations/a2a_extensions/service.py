"""Service facade for A2A Agent Card extensions."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Literal, Optional

from app.core.logging import get_logger
from app.features.personal_agents.runtime import A2ARuntime
from app.integrations.a2a_extensions.capability_snapshot import (
    CapabilitySnapshotCacheEntry,
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
from app.integrations.a2a_extensions.capability_snapshot_builder import (
    build_codex_discovery_snapshot,
    build_codex_exec_snapshot,
    build_codex_review_snapshot,
    build_codex_thread_watch_snapshot,
    build_codex_threads_snapshot,
    build_codex_turns_snapshot,
    build_compatibility_profile_snapshot,
    build_declared_method_collection_snapshot,
    build_interrupt_callback_snapshot,
    build_interrupt_recovery_snapshot,
    build_invoke_metadata_snapshot,
    build_model_selection_snapshot,
    build_provider_discovery_snapshot,
    build_request_execution_options_snapshot,
    build_session_binding_snapshot,
    build_session_query_snapshot,
    build_stream_hints_snapshot,
    build_wire_contract_snapshot,
)
from app.integrations.a2a_extensions.codex_discovery_service import (
    CodexDiscoveryService,
)
from app.integrations.a2a_extensions.contract_utils import (
    as_dict,
    resolve_jsonrpc_interface,
)
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
    A2AExtensionUpstreamError,
)
from app.integrations.a2a_extensions.interrupt_extension_service import (
    InterruptExtensionService,
)
from app.integrations.a2a_extensions.interrupt_recovery_service import (
    InterruptRecoveryService,
)
from app.integrations.a2a_extensions.opencode_discovery_service import (
    OpencodeDiscoveryService,
)
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.session_extension_service import (
    SessionExtensionService,
)
from app.integrations.a2a_extensions.session_query_runtime_selection import (
    ResolvedSessionQueryRuntimeCapability,
)
from app.integrations.a2a_extensions.shared_support import (
    A2AExtensionSupport,
)
from app.integrations.a2a_extensions.types import (
    ResolvedConditionalMethodAvailability,
    ResolvedInterruptCallbackExtension,
    ResolvedInterruptRecoveryExtension,
    ResolvedInvokeMetadataExtension,
    ResolvedProviderDiscoveryExtension,
    ResolvedSessionBindingExtension,
    ResolvedWireContractExtension,
)

logger = get_logger(__name__)
_CAPABILITY_SNAPSHOT_CACHE_TTL_SECONDS = 300.0
_CODEX_DISCOVERY_METHODS = {
    "skillsList": "codex.discovery.skills.list",
    "appsList": "codex.discovery.apps.list",
    "pluginsList": "codex.discovery.plugins.list",
    "pluginsRead": "codex.discovery.plugins.read",
    "watch": "codex.discovery.watch",
}
_CODEX_TURNS_METHODS = {
    "steer": "codex.turns.steer",
}
_CODEX_TURN_CONTROL_URI = "urn:codex-a2a:codex-turn-control/v1"
_CODEX_TURN_CONTROL_BUSINESS_CODE_MAP = {
    -32007: "authorization_forbidden",
    -32012: "turn_not_steerable",
    -32013: "turn_forbidden",
}


class A2AExtensionsService:
    def __init__(self) -> None:
        self._support = A2AExtensionSupport()
        self._session_extensions = SessionExtensionService(self._support)
        self._interrupt_extensions = InterruptExtensionService(self._support)
        self._interrupt_recovery = InterruptRecoveryService(self._support)
        self._opencode_discovery = OpencodeDiscoveryService(self._support)
        self._codex_discovery = CodexDiscoveryService(self._support)
        self._capability_snapshot_cache_lock = asyncio.Lock()
        self._capability_snapshot_cache: dict[
            tuple[str, tuple[tuple[str, str], ...]],
            CapabilitySnapshotCacheEntry,
        ] = {}

    async def shutdown(self) -> None:
        await self._support.shutdown()
        async with self._capability_snapshot_cache_lock:
            self._capability_snapshot_cache.clear()

    @staticmethod
    def _capability_snapshot_cache_key(
        runtime: A2ARuntime,
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        resolved_headers = getattr(runtime.resolved, "headers", {}) or {}
        headers = tuple(sorted(resolved_headers.items()))
        return runtime.resolved.url, headers

    @staticmethod
    def _build_session_query_snapshot(card: Any) -> SessionQueryCapabilitySnapshot:
        return build_session_query_snapshot(card)

    @staticmethod
    def _build_session_binding_snapshot(card: Any) -> SessionBindingCapabilitySnapshot:
        return build_session_binding_snapshot(card)

    @staticmethod
    def _build_invoke_metadata_snapshot(card: Any) -> InvokeMetadataCapabilitySnapshot:
        return build_invoke_metadata_snapshot(card)

    @staticmethod
    def _normalize_optional_string_list(
        value: Any,
        *,
        field: str,
    ) -> tuple[str, ...]:
        from app.integrations.a2a_extensions.capability_snapshot_builder import (
            normalize_optional_string_list,
        )

        return normalize_optional_string_list(value, field=field)

    @classmethod
    def _build_request_execution_options_snapshot(
        cls,
        card: Any,
    ) -> RequestExecutionOptionsCapabilitySnapshot:
        return build_request_execution_options_snapshot(card)

    def _build_interrupt_callback_snapshot(
        self, card: Any
    ) -> InterruptCallbackCapabilitySnapshot:
        return build_interrupt_callback_snapshot(self._support, card)

    def _build_interrupt_recovery_snapshot(
        self, card: Any
    ) -> InterruptRecoveryCapabilitySnapshot:
        return build_interrupt_recovery_snapshot(self._support, card)

    def _build_provider_discovery_snapshot(
        self, card: Any
    ) -> ProviderDiscoveryCapabilitySnapshot:
        return build_provider_discovery_snapshot(self._support, card)

    @staticmethod
    def _build_model_selection_snapshot(card: Any) -> ModelSelectionCapabilitySnapshot:
        return build_model_selection_snapshot(card)

    @staticmethod
    def _build_stream_hints_snapshot(card: Any) -> StreamHintsCapabilitySnapshot:
        return build_stream_hints_snapshot(card)

    @staticmethod
    def _build_compatibility_profile_snapshot(
        card: Any,
    ) -> CompatibilityProfileCapabilitySnapshot:
        return build_compatibility_profile_snapshot(card)

    @staticmethod
    def _build_wire_contract_snapshot(
        card: Any,
    ) -> WireContractCapabilitySnapshot:
        return build_wire_contract_snapshot(card)

    @staticmethod
    def _declared_wire_contract_methods(
        snapshot: WireContractCapabilitySnapshot,
    ) -> frozenset[str]:
        from app.integrations.a2a_extensions.capability_snapshot_builder import (
            declared_wire_contract_methods,
        )

        return declared_wire_contract_methods(snapshot)

    @classmethod
    def _conditional_wire_contract_methods(
        cls,
        snapshot: WireContractCapabilitySnapshot,
    ) -> dict[str, ResolvedConditionalMethodAvailability]:
        from app.integrations.a2a_extensions.capability_snapshot_builder import (
            conditional_wire_contract_methods,
        )

        return conditional_wire_contract_methods(snapshot)

    @staticmethod
    def _compatibility_method_retention(
        snapshot: CompatibilityProfileCapabilitySnapshot,
    ) -> dict[str, Any]:
        from app.integrations.a2a_extensions.capability_snapshot_builder import (
            compatibility_method_retention,
        )

        return compatibility_method_retention(snapshot)

    @classmethod
    def _resolve_declared_method_snapshot(
        cls,
        *,
        wire_contract: WireContractCapabilitySnapshot,
        compatibility_profile: CompatibilityProfileCapabilitySnapshot,
        method_name: str,
        consumed_by_hub: bool,
    ) -> DeclaredMethodCapabilitySnapshot:
        from app.integrations.a2a_extensions.capability_snapshot_builder import (
            resolve_declared_method_snapshot,
        )

        return resolve_declared_method_snapshot(
            wire_contract=wire_contract,
            compatibility_profile=compatibility_profile,
            method_name=method_name,
            consumed_by_hub=consumed_by_hub,
        )

    @classmethod
    def _build_declared_method_collection_snapshot(
        cls,
        *,
        wire_contract: WireContractCapabilitySnapshot,
        compatibility_profile: CompatibilityProfileCapabilitySnapshot,
        method_map: dict[str, str],
        hub_consumption: dict[str, bool],
        unsupported_status_when_declared: Literal[
            "declared_not_consumed", "unsupported_by_design"
        ],
        jsonrpc_url: str | None,
        declaration_source: (
            Literal[
                "none",
                "wire_contract",
                "wire_contract_fallback",
                "extension_method_hint",
                "extension_uri_hint",
            ]
            | None
        ) = None,
        declaration_confidence: (
            Literal["none", "fallback", "authoritative"] | None
        ) = None,
        negotiation_state: (
            Literal["supported", "missing", "invalid", "unsupported"] | None
        ) = None,
        diagnostic_note: str | None = None,
    ) -> DeclaredMethodCollectionCapabilitySnapshot:
        return build_declared_method_collection_snapshot(
            wire_contract=wire_contract,
            compatibility_profile=compatibility_profile,
            method_map=method_map,
            hub_consumption=hub_consumption,
            unsupported_status_when_declared=unsupported_status_when_declared,
            jsonrpc_url=jsonrpc_url,
            declaration_source=declaration_source,
            declaration_confidence=declaration_confidence,
            negotiation_state=negotiation_state,
            diagnostic_note=diagnostic_note,
        )

    @classmethod
    def _build_codex_discovery_snapshot(
        cls,
        card: Any,
        wire_contract: WireContractCapabilitySnapshot,
        compatibility_profile: CompatibilityProfileCapabilitySnapshot,
        *,
        jsonrpc_url: str | None,
    ) -> DeclaredMethodCollectionCapabilitySnapshot:
        return build_codex_discovery_snapshot(
            card,
            wire_contract,
            compatibility_profile,
            jsonrpc_url=jsonrpc_url,
        )

    @classmethod
    def _build_codex_exec_snapshot(
        cls,
        wire_contract: WireContractCapabilitySnapshot,
        compatibility_profile: CompatibilityProfileCapabilitySnapshot,
        *,
        jsonrpc_url: str | None,
    ) -> DeclaredMethodCollectionCapabilitySnapshot:
        return build_codex_exec_snapshot(
            wire_contract,
            compatibility_profile,
            jsonrpc_url=jsonrpc_url,
        )

    @classmethod
    def _build_codex_threads_snapshot(
        cls,
        wire_contract: WireContractCapabilitySnapshot,
        compatibility_profile: CompatibilityProfileCapabilitySnapshot,
        *,
        jsonrpc_url: str | None,
    ) -> DeclaredMethodCollectionCapabilitySnapshot:
        return build_codex_threads_snapshot(
            wire_contract,
            compatibility_profile,
            jsonrpc_url=jsonrpc_url,
        )

    @classmethod
    def _build_codex_turns_snapshot(
        cls,
        wire_contract: WireContractCapabilitySnapshot,
        compatibility_profile: CompatibilityProfileCapabilitySnapshot,
        *,
        jsonrpc_url: str | None,
    ) -> DeclaredMethodCollectionCapabilitySnapshot:
        return build_codex_turns_snapshot(
            wire_contract,
            compatibility_profile,
            jsonrpc_url=jsonrpc_url,
        )

    @classmethod
    def _build_codex_review_snapshot(
        cls,
        wire_contract: WireContractCapabilitySnapshot,
        compatibility_profile: CompatibilityProfileCapabilitySnapshot,
        *,
        jsonrpc_url: str | None,
    ) -> DeclaredMethodCollectionCapabilitySnapshot:
        return build_codex_review_snapshot(
            wire_contract,
            compatibility_profile,
            jsonrpc_url=jsonrpc_url,
        )

    @classmethod
    def _build_codex_thread_watch_snapshot(
        cls,
        wire_contract: WireContractCapabilitySnapshot,
        *,
        jsonrpc_url: str | None,
    ) -> DeclaredSingleMethodCapabilitySnapshot:
        return build_codex_thread_watch_snapshot(
            wire_contract,
            jsonrpc_url=jsonrpc_url,
        )

    async def resolve_capability_snapshot(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ResolvedCapabilitySnapshot:
        cache_key = self._capability_snapshot_cache_key(runtime)
        now = time.monotonic()
        async with self._capability_snapshot_cache_lock:
            cached = self._capability_snapshot_cache.get(cache_key)
            if cached and cached.expires_at > now:
                return cached.snapshot

        card = await self._support.fetch_card(runtime)
        wire_contract = self._build_wire_contract_snapshot(card)
        jsonrpc_url = None
        try:
            jsonrpc_url = self._support.ensure_outbound_allowed(
                resolve_jsonrpc_interface(card).url,
                purpose="JSON-RPC interface URL",
            )
        except (A2AExtensionContractError, A2AExtensionUpstreamError):
            jsonrpc_url = None
        compatibility_profile = self._build_compatibility_profile_snapshot(card)
        snapshot = ResolvedCapabilitySnapshot(
            session_query=self._build_session_query_snapshot(card),
            session_binding=self._build_session_binding_snapshot(card),
            invoke_metadata=self._build_invoke_metadata_snapshot(card),
            request_execution_options=self._build_request_execution_options_snapshot(
                card
            ),
            interrupt_callback=self._build_interrupt_callback_snapshot(card),
            interrupt_recovery=self._build_interrupt_recovery_snapshot(card),
            model_selection=self._build_model_selection_snapshot(card),
            provider_discovery=self._build_provider_discovery_snapshot(card),
            stream_hints=self._build_stream_hints_snapshot(card),
            wire_contract=wire_contract,
            compatibility_profile=compatibility_profile,
            codex_discovery=self._build_codex_discovery_snapshot(
                card,
                wire_contract,
                compatibility_profile,
                jsonrpc_url=jsonrpc_url,
            ),
            codex_threads=self._build_codex_threads_snapshot(
                wire_contract,
                compatibility_profile,
                jsonrpc_url=jsonrpc_url,
            ),
            codex_turns=self._build_codex_turns_snapshot(
                wire_contract,
                compatibility_profile,
                jsonrpc_url=jsonrpc_url,
            ),
            codex_review=self._build_codex_review_snapshot(
                wire_contract,
                compatibility_profile,
                jsonrpc_url=jsonrpc_url,
            ),
            codex_thread_watch=self._build_codex_thread_watch_snapshot(
                wire_contract, jsonrpc_url=jsonrpc_url
            ),
            codex_exec=self._build_codex_exec_snapshot(
                wire_contract,
                compatibility_profile,
                jsonrpc_url=jsonrpc_url,
            ),
        )
        async with self._capability_snapshot_cache_lock:
            self._capability_snapshot_cache[cache_key] = CapabilitySnapshotCacheEntry(
                snapshot=snapshot,
                expires_at=now + _CAPABILITY_SNAPSHOT_CACHE_TTL_SECONDS,
            )
        return snapshot

    @staticmethod
    def _require_session_query_capability(
        snapshot: SessionQueryCapabilitySnapshot,
    ) -> ResolvedSessionQueryRuntimeCapability:
        if snapshot.capability is not None:
            return snapshot.capability
        if snapshot.status == "invalid":
            raise A2AExtensionContractError(
                snapshot.error or "Shared session query contract is invalid"
            )
        raise A2AExtensionNotSupportedError(
            snapshot.error or "Shared session query extension not supported by Hub"
        )

    @staticmethod
    def _require_interrupt_callback_capability(
        snapshot: InterruptCallbackCapabilitySnapshot,
    ) -> tuple[ResolvedInterruptCallbackExtension, str]:
        if snapshot.ext is not None and snapshot.jsonrpc_url is not None:
            return snapshot.ext, snapshot.jsonrpc_url
        if snapshot.status == "invalid":
            raise A2AExtensionContractError(
                snapshot.error or "Shared interrupt callback contract is invalid"
            )
        raise A2AExtensionNotSupportedError(
            snapshot.error or "Shared interrupt callback extension not found"
        )

    @staticmethod
    def _require_interrupt_recovery_capability(
        snapshot: InterruptRecoveryCapabilitySnapshot,
    ) -> tuple[ResolvedInterruptRecoveryExtension, str]:
        if snapshot.ext is not None and snapshot.jsonrpc_url is not None:
            return snapshot.ext, snapshot.jsonrpc_url
        if snapshot.status == "invalid":
            raise A2AExtensionContractError(
                snapshot.error or "Interrupt recovery contract is invalid"
            )
        raise A2AExtensionNotSupportedError(
            snapshot.error or "Interrupt recovery extension not found"
        )

    @staticmethod
    def _require_provider_discovery_capability(
        snapshot: ProviderDiscoveryCapabilitySnapshot,
    ) -> tuple[ResolvedProviderDiscoveryExtension, str]:
        if snapshot.ext is not None and snapshot.jsonrpc_url is not None:
            return snapshot.ext, snapshot.jsonrpc_url
        if snapshot.status == "invalid":
            raise A2AExtensionContractError(
                snapshot.error or "Provider discovery contract is invalid"
            )
        raise A2AExtensionNotSupportedError(
            snapshot.error or "Provider discovery extension not found"
        )

    @staticmethod
    def _require_declared_method_collection_capability(
        snapshot: DeclaredMethodCollectionCapabilitySnapshot,
        *,
        capability_name: str,
    ) -> tuple[DeclaredMethodCollectionCapabilitySnapshot, str]:
        if snapshot.declared and snapshot.jsonrpc_url:
            return snapshot, snapshot.jsonrpc_url
        if snapshot.declared:
            raise A2AExtensionContractError(
                f"{capability_name} is declared but no JSON-RPC interface URL is available"
            )
        raise A2AExtensionNotSupportedError(f"{capability_name} methods not declared")

    @staticmethod
    def _require_declared_method_capability(
        snapshot: DeclaredMethodCollectionCapabilitySnapshot,
        *,
        method_key: str,
        capability_name: str,
    ) -> DeclaredMethodCapabilitySnapshot:
        method = snapshot.methods[method_key]
        if method.declared and method.consumed_by_hub:
            return method
        if method.declared:
            raise A2AExtensionNotSupportedError(
                f"{capability_name} method {method_key} is declared but not consumed by Hub"
            )
        raise A2AExtensionNotSupportedError(
            f"{capability_name} method {method_key} is not declared"
        )

    @staticmethod
    def _build_wire_contract_preflight_error(
        *,
        error_code: Literal["method_disabled", "method_not_supported"],
        extension_uri: str,
        method_name: str,
        wire_contract: ResolvedWireContractExtension,
        conditional: ResolvedConditionalMethodAvailability | None = None,
    ) -> ExtensionCallResult:
        if conditional is not None:
            message = f"Method {method_name} is disabled by upstream deployment"
            upstream_error = {
                "message": message,
                "type": "METHOD_DISABLED",
                "method": method_name,
                "reason": conditional.reason,
            }
            if conditional.toggle:
                upstream_error["toggle"] = conditional.toggle
            return ExtensionCallResult(
                success=False,
                error_code=error_code,
                source="wire_contract",
                upstream_error=upstream_error,
                meta={
                    "extension_uri": extension_uri,
                    "wire_contract_uri": wire_contract.uri,
                    "wire_contract_preflight": "conditionally_available",
                    "method_name": method_name,
                },
            )

        unsupported = wire_contract.unsupported_method_error
        supported_methods = list(wire_contract.all_jsonrpc_methods)
        message = f"Unsupported method: {method_name}"
        return ExtensionCallResult(
            success=False,
            error_code=error_code,
            source="wire_contract",
            jsonrpc_code=unsupported.code,
            upstream_error={
                "message": message,
                "type": unsupported.type,
                "method": method_name,
                "supported_methods": supported_methods,
                "protocol_version": wire_contract.protocol_version,
            },
            meta={
                "extension_uri": extension_uri,
                "wire_contract_uri": wire_contract.uri,
                "wire_contract_preflight": "unsupported_method",
                "method_name": method_name,
            },
        )

    @classmethod
    def _preflight_wire_contract_method(
        cls,
        *,
        snapshot: WireContractCapabilitySnapshot,
        extension_uri: str,
        method_name: str | None,
    ) -> ExtensionCallResult | None:
        if not method_name or snapshot.ext is None or snapshot.status != "supported":
            return None

        wire_contract = snapshot.ext
        if method_name in wire_contract.all_jsonrpc_methods:
            return None

        conditional = wire_contract.conditionally_available_methods.get(method_name)
        if conditional is not None:
            return cls._build_wire_contract_preflight_error(
                error_code="method_disabled",
                extension_uri=extension_uri,
                method_name=method_name,
                wire_contract=wire_contract,
                conditional=conditional,
            )

        return cls._build_wire_contract_preflight_error(
            error_code="method_not_supported",
            extension_uri=extension_uri,
            method_name=method_name,
            wire_contract=wire_contract,
        )

    async def _resolve_session_extension_runtime(
        self,
        *,
        runtime: A2ARuntime,
    ) -> tuple[ResolvedCapabilitySnapshot, ResolvedSessionQueryRuntimeCapability]:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability = self._require_session_query_capability(snapshot.session_query)
        return snapshot, capability

    @staticmethod
    def _pick_optional_text(
        source: dict[str, Any],
        *,
        keys: tuple[str, ...],
    ) -> str | None:
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @classmethod
    def _resolve_shared_stream_turn_identity(
        cls,
        metadata: Dict[str, Any] | None,
    ) -> tuple[str | None, str | None]:
        normalized_metadata = as_dict(metadata)
        shared = as_dict(normalized_metadata.get("shared"))
        stream = as_dict(shared.get("stream"))

        thread_id = cls._pick_optional_text(
            stream,
            keys=("thread_id", "threadId"),
        )
        turn_id = cls._pick_optional_text(
            stream,
            keys=("turn_id", "turnId"),
        )
        return thread_id, turn_id

    @staticmethod
    def _strip_shared_metadata_for_upstream(
        metadata: Dict[str, Any] | None,
    ) -> Dict[str, Any] | None:
        normalized_metadata = as_dict(metadata)
        if not normalized_metadata:
            return None
        if "shared" not in normalized_metadata:
            return dict(normalized_metadata)
        sanitized_metadata = dict(normalized_metadata)
        sanitized_metadata.pop("shared", None)
        return sanitized_metadata or None

    def _prepare_codex_turn_steer(
        self,
        *,
        thread_id: str,
        turn_id: str,
        request_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        resolved_thread_id = (thread_id or "").strip()
        if not resolved_thread_id:
            raise ValueError("thread_id is required")
        resolved_turn_id = (turn_id or "").strip()
        if not resolved_turn_id:
            raise ValueError("expected_turn_id is required")
        if not isinstance(request_payload, dict):
            raise ValueError("request must be an object")

        parts = request_payload.get("parts")
        if not isinstance(parts, list) or len(parts) == 0:
            raise ValueError("request.parts must be a non-empty array")

        return {
            "thread_id": resolved_thread_id,
            "expected_turn_id": resolved_turn_id,
            "request": {
                "parts": list(parts),
            },
        }

    async def _steer_codex_turn(
        self,
        *,
        runtime: A2ARuntime,
        jsonrpc_url: str,
        session_id: str,
        thread_id: str,
        turn_id: str,
        request_payload: Dict[str, Any],
    ) -> ExtensionCallResult:
        method_name = _CODEX_TURNS_METHODS["steer"]
        params = self._prepare_codex_turn_steer(
            thread_id=thread_id,
            turn_id=turn_id,
            request_payload=request_payload,
        )
        resp = await self._support.perform_jsonrpc_call(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method_name,
            params=params,
        )

        metric_key = f"{_CODEX_TURN_CONTROL_URI}:{method_name}"
        meta = {
            "extension_uri": _CODEX_TURN_CONTROL_URI,
            "method_name": method_name,
            "control_method": "codex_turns_steer",
            "session_id": session_id,
            "thread_id": thread_id,
            "expected_turn_id": turn_id,
        }
        if resp.ok:
            self._support.record_extension_metric(
                metric_key,
                success=True,
                error_code=None,
            )
            result_payload = as_dict(resp.result)
            normalized_result = dict(result_payload)
            normalized_result.setdefault("ok", True)
            normalized_result.setdefault("session_id", session_id)
            normalized_result.setdefault("thread_id", thread_id)
            normalized_result.setdefault("turn_id", turn_id)
            return ExtensionCallResult(
                success=True,
                result=normalized_result,
                meta=meta,
            )

        error = resp.error or {}
        error_details = self._support.build_upstream_error_details(
            error=error,
            business_code_map=_CODEX_TURN_CONTROL_BUSINESS_CODE_MAP,
        )
        self._support.record_extension_metric(
            metric_key,
            success=False,
            error_code=error_details.error_code,
        )
        return ExtensionCallResult(
            success=False,
            error_code=error_details.error_code,
            source=error_details.source,
            jsonrpc_code=error_details.jsonrpc_code,
            missing_params=list(error_details.missing_params or []) or None,
            upstream_error=error_details.upstream_error,
            meta=meta,
        )

    async def resolve_session_binding(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ResolvedSessionBindingExtension:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        if snapshot.session_binding.ext is not None:
            return snapshot.session_binding.ext
        if snapshot.session_binding.status == "invalid":
            raise A2AExtensionContractError(
                snapshot.session_binding.error
                or "Shared session binding contract is invalid"
            )
        raise A2AExtensionNotSupportedError(
            snapshot.session_binding.error
            or "Shared session binding extension not found"
        )

    async def resolve_invoke_metadata(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ResolvedInvokeMetadataExtension:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        if snapshot.invoke_metadata.ext is not None:
            return snapshot.invoke_metadata.ext
        if snapshot.invoke_metadata.status == "invalid":
            raise A2AExtensionContractError(
                snapshot.invoke_metadata.error or "Invoke metadata contract is invalid"
            )
        raise A2AExtensionNotSupportedError(
            snapshot.invoke_metadata.error or "Invoke metadata extension not found"
        )

    async def list_sessions(
        self,
        *,
        runtime: A2ARuntime,
        page: int,
        size: Optional[int],
        query: Optional[Dict[str, Any]],
        filters: Optional[Dict[str, Any]] = None,
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("list_sessions"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.list_sessions(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            page=page,
            size=size,
            query=query,
            filters=filters,
            include_raw=include_raw,
        )

    async def get_session_messages(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        page: int,
        size: Optional[int],
        before: str | None,
        query: Optional[Dict[str, Any]],
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("get_session_messages"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.get_session_messages(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            page=page,
            size=size,
            before=before,
            query=query,
            include_raw=include_raw,
        )

    async def continue_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
    ) -> ExtensionCallResult:
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("get_session_messages"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.continue_session(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            binding_meta=dict(snapshot.session_binding.meta or {}),
            session_id=session_id,
        )

    async def prompt_session_async(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_prompt_session_async(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("prompt_async"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.prompt_session_async(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )

    async def append_session_control(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        if not isinstance(request_payload, dict):
            raise ValueError("request must be an object")

        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        thread_id, turn_id = self._resolve_shared_stream_turn_identity(metadata)
        metadata_for_upstream = self._strip_shared_metadata_for_upstream(metadata)
        steer_capability = snapshot.codex_turns.methods.get("steer")

        if (
            steer_capability is not None
            and steer_capability.declared
            and steer_capability.consumed_by_hub
            and steer_capability.method
            and snapshot.codex_turns.jsonrpc_url
            and thread_id
            and turn_id
        ):
            preflight = self._preflight_wire_contract_method(
                snapshot=snapshot.wire_contract,
                extension_uri=_CODEX_TURN_CONTROL_URI,
                method_name=steer_capability.method,
            )
            if preflight is not None:
                return preflight
            return await self._steer_codex_turn(
                runtime=runtime,
                jsonrpc_url=snapshot.codex_turns.jsonrpc_url,
                session_id=session_id,
                thread_id=thread_id,
                turn_id=turn_id,
                request_payload=request_payload,
            )

        capability = self._require_session_query_capability(snapshot.session_query)
        self._session_extensions.prepare_prompt_session_async(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata_for_upstream,
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("prompt_async"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.prompt_session_async(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata_for_upstream,
        )

    async def command_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_command(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("command"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.command_session(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )

    async def get_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_lookup(session_id=session_id)
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("get_session"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.get_session(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            include_raw=include_raw,
        )

    async def get_session_children(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_lookup(session_id=session_id)
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("get_session_children"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.get_session_children(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            include_raw=include_raw,
        )

    async def get_session_todo(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_lookup(session_id=session_id)
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("get_session_todo"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.get_session_todo(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            include_raw=include_raw,
        )

    async def get_session_diff(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        message_id: str | None = None,
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_lookup(session_id=session_id)
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("get_session_diff"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.get_session_diff(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            message_id=message_id,
            include_raw=include_raw,
        )

    async def get_session_message(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        message_id: str,
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_message_lookup(
            session_id=session_id,
            message_id=message_id,
        )
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("get_session_message"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.get_session_message(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            message_id=message_id,
            include_raw=include_raw,
        )

    async def fork_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        request_payload: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_action(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("fork"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.fork_session(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )

    async def share_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_action(
            session_id=session_id,
            metadata=metadata,
        )
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("share"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.share_session(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            metadata=metadata,
        )

    async def unshare_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_action(
            session_id=session_id,
            metadata=metadata,
        )
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("unshare"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.unshare_session(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            metadata=metadata,
        )

    async def summarize_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        request_payload: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_summarize(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("summarize"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.summarize_session(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )

    async def revert_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_revert(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("revert"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.revert_session(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )

    async def unrevert_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_action(
            session_id=session_id,
            metadata=metadata,
        )
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("unrevert"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.unrevert_session(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            metadata=metadata,
        )

    async def list_model_providers(
        self,
        *,
        runtime: A2ARuntime,
        session_metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_provider_discovery_capability(
            snapshot.provider_discovery
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=ext.uri,
            method_name=ext.methods.get("list_providers"),
        )
        if preflight is not None:
            return preflight
        return await self._opencode_discovery.list_model_providers(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            session_metadata=session_metadata,
        )

    async def list_models(
        self,
        *,
        runtime: A2ARuntime,
        provider_id: str | None = None,
        session_metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_provider_discovery_capability(
            snapshot.provider_discovery
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=ext.uri,
            method_name=ext.methods.get("list_models"),
        )
        if preflight is not None:
            return preflight
        return await self._opencode_discovery.list_models(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            provider_id=provider_id,
            session_metadata=session_metadata,
        )

    async def list_codex_skills(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability, jsonrpc_url = self._require_declared_method_collection_capability(
            snapshot.codex_discovery,
            capability_name="Codex discovery",
        )
        method = self._require_declared_method_capability(
            capability,
            method_key="skillsList",
            capability_name="Codex discovery",
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=(
                snapshot.wire_contract.ext.uri
                if snapshot.wire_contract.ext is not None
                else "wire_contract"
            ),
            method_name=method.method,
        )
        if preflight is not None:
            return preflight
        return await self._codex_discovery.list_skills(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method.method or _CODEX_DISCOVERY_METHODS["skillsList"],
            meta={
                "extension_uri": (
                    snapshot.wire_contract.ext.uri
                    if snapshot.wire_contract.ext is not None
                    else None
                ),
                "capability_area": "codex_discovery",
                "method_name": method.method,
            },
        )

    async def list_codex_apps(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability, jsonrpc_url = self._require_declared_method_collection_capability(
            snapshot.codex_discovery,
            capability_name="Codex discovery",
        )
        method = self._require_declared_method_capability(
            capability,
            method_key="appsList",
            capability_name="Codex discovery",
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=(
                snapshot.wire_contract.ext.uri
                if snapshot.wire_contract.ext is not None
                else "wire_contract"
            ),
            method_name=method.method,
        )
        if preflight is not None:
            return preflight
        return await self._codex_discovery.list_apps(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method.method or _CODEX_DISCOVERY_METHODS["appsList"],
            meta={
                "extension_uri": (
                    snapshot.wire_contract.ext.uri
                    if snapshot.wire_contract.ext is not None
                    else None
                ),
                "capability_area": "codex_discovery",
                "method_name": method.method,
            },
        )

    async def list_codex_plugins(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability, jsonrpc_url = self._require_declared_method_collection_capability(
            snapshot.codex_discovery,
            capability_name="Codex discovery",
        )
        method = self._require_declared_method_capability(
            capability,
            method_key="pluginsList",
            capability_name="Codex discovery",
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=(
                snapshot.wire_contract.ext.uri
                if snapshot.wire_contract.ext is not None
                else "wire_contract"
            ),
            method_name=method.method,
        )
        if preflight is not None:
            return preflight
        return await self._codex_discovery.list_plugins(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method.method or _CODEX_DISCOVERY_METHODS["pluginsList"],
            meta={
                "extension_uri": (
                    snapshot.wire_contract.ext.uri
                    if snapshot.wire_contract.ext is not None
                    else None
                ),
                "capability_area": "codex_discovery",
                "method_name": method.method,
            },
        )

    async def read_codex_plugin(
        self,
        *,
        runtime: A2ARuntime,
        marketplace_path: str,
        plugin_name: str,
    ) -> ExtensionCallResult:
        resolved_marketplace_path = marketplace_path.strip()
        resolved_plugin_name = plugin_name.strip()
        if not resolved_marketplace_path:
            raise ValueError("marketplace_path must be a non-empty string")
        if not resolved_plugin_name:
            raise ValueError("plugin_name must be a non-empty string")
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability, jsonrpc_url = self._require_declared_method_collection_capability(
            snapshot.codex_discovery,
            capability_name="Codex discovery",
        )
        method = self._require_declared_method_capability(
            capability,
            method_key="pluginsRead",
            capability_name="Codex discovery",
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=(
                snapshot.wire_contract.ext.uri
                if snapshot.wire_contract.ext is not None
                else "wire_contract"
            ),
            method_name=method.method,
        )
        if preflight is not None:
            return preflight
        return await self._codex_discovery.read_plugin(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method.method or _CODEX_DISCOVERY_METHODS["pluginsRead"],
            marketplace_path=resolved_marketplace_path,
            plugin_name=resolved_plugin_name,
            meta={
                "extension_uri": (
                    snapshot.wire_contract.ext.uri
                    if snapshot.wire_contract.ext is not None
                    else None
                ),
                "capability_area": "codex_discovery",
                "method_name": method.method,
                "marketplace_path": resolved_marketplace_path,
                "plugin_name": resolved_plugin_name,
            },
        )

    async def reply_permission_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        reply: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        (
            resolved_request_id,
            resolved_reply,
            normalized_metadata,
        ) = self._interrupt_extensions.prepare_reply_permission_interrupt(
            request_id=request_id,
            reply=reply,
            metadata=metadata,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_interrupt_callback_capability(
            snapshot.interrupt_callback
        )
        return await self._interrupt_extensions.reply_permission_interrupt(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            request_id=resolved_request_id,
            reply=resolved_reply,
            metadata=normalized_metadata,
        )

    async def reply_question_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        answers: list[list[str]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        (
            resolved_request_id,
            resolved_answers,
            normalized_metadata,
        ) = self._interrupt_extensions.prepare_reply_question_interrupt(
            request_id=request_id,
            answers=answers,
            metadata=metadata,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_interrupt_callback_capability(
            snapshot.interrupt_callback
        )
        return await self._interrupt_extensions.reply_question_interrupt(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            request_id=resolved_request_id,
            answers=resolved_answers,
            metadata=normalized_metadata,
        )

    async def reject_question_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        (
            resolved_request_id,
            normalized_metadata,
        ) = self._interrupt_extensions.prepare_reject_question_interrupt(
            request_id=request_id,
            metadata=metadata,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_interrupt_callback_capability(
            snapshot.interrupt_callback
        )
        return await self._interrupt_extensions.reject_question_interrupt(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            request_id=resolved_request_id,
            metadata=normalized_metadata,
        )

    async def recover_interrupts(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str | None = None,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_interrupt_recovery_capability(
            snapshot.interrupt_recovery
        )
        return await self._interrupt_recovery.recover_interrupts(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            session_id=session_id,
        )

    async def reply_permissions_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        permissions: Dict[str, Any],
        scope: str | None = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        (
            resolved_request_id,
            resolved_permissions,
            resolved_scope,
            normalized_metadata,
        ) = self._interrupt_extensions.prepare_reply_permissions_interrupt(
            request_id=request_id,
            permissions=permissions,
            scope=scope,
            metadata=metadata,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_interrupt_callback_capability(
            snapshot.interrupt_callback
        )
        return await self._interrupt_extensions.reply_permissions_interrupt(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            request_id=resolved_request_id,
            permissions=resolved_permissions,
            scope=resolved_scope,
            metadata=normalized_metadata,
        )

    async def reply_elicitation_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        action: str,
        content: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        (
            resolved_request_id,
            resolved_action,
            resolved_content,
            normalized_metadata,
        ) = self._interrupt_extensions.prepare_reply_elicitation_interrupt(
            request_id=request_id,
            action=action,
            content=content,
            metadata=metadata,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_interrupt_callback_capability(
            snapshot.interrupt_callback
        )
        return await self._interrupt_extensions.reply_elicitation_interrupt(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            request_id=resolved_request_id,
            action=resolved_action,
            content=resolved_content,
            metadata=normalized_metadata,
        )


_service_instance: Optional[A2AExtensionsService] = None


def get_a2a_extensions_service() -> A2AExtensionsService:
    global _service_instance
    if _service_instance is None:
        _service_instance = A2AExtensionsService()
        logger.info("A2A extensions service initialised")
    return _service_instance


async def shutdown_a2a_extensions_service() -> None:
    global _service_instance
    if _service_instance is None:
        return
    await _service_instance.shutdown()
    _service_instance = None
