"""Service facade for A2A Agent Card extensions."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any, Dict, Optional

from a2a.types import AgentCard

from app.core.logging import get_logger
from app.features.agents.personal.runtime import A2ARuntime
from app.integrations.a2a_extensions.capability_snapshot import (
    ResolvedCapabilitySnapshot,
)
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.interrupt_extension_service import (
    InterruptExtensionService,
)
from app.integrations.a2a_extensions.interrupt_recovery_service import (
    InterruptRecoveryService,
)
from app.integrations.a2a_extensions.provider_discovery_service import (
    ProviderDiscoveryService,
)
from app.integrations.a2a_extensions.service_capabilities import (
    UPSTREAM_DISCOVERY_METHODS,
    A2AExtensionCapabilityService,
)
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.service_session_ops import (
    A2AExtensionSessionOperations,
)
from app.integrations.a2a_extensions.session_extension_service import (
    SessionExtensionService,
)
from app.integrations.a2a_extensions.session_query_runtime_selection import (
    ResolvedSessionQueryRuntimeCapability,
)
from app.integrations.a2a_extensions.shared_support import A2AExtensionSupport
from app.integrations.a2a_extensions.types import (
    ResolvedInvokeMetadataExtension,
    ResolvedSessionBindingExtension,
)
from app.integrations.a2a_extensions.upstream_discovery_service import (
    UpstreamDiscoveryService,
)

logger = get_logger(__name__)


class A2AExtensionsService:
    def __init__(self) -> None:
        self._support = A2AExtensionSupport()
        self._session_extensions = SessionExtensionService(self._support)
        self._interrupt_extensions = InterruptExtensionService(self._support)
        self._interrupt_recovery = InterruptRecoveryService(self._support)
        self._provider_discovery = ProviderDiscoveryService(self._support)
        self._upstream_discovery = UpstreamDiscoveryService(self._support)
        self._capabilities = A2AExtensionCapabilityService(
            support=self._support,
            time_module=time,
        )
        self._session_ops = A2AExtensionSessionOperations(
            support=self._support,
            session_extensions=self._session_extensions,
            capabilities=self._capabilities,
        )

    async def shutdown(self) -> None:
        await self._support.shutdown()
        await self._capabilities.shutdown()

    async def resolve_capability_snapshot(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ResolvedCapabilitySnapshot:
        return await self._capabilities.resolve_capability_snapshot(runtime=runtime)

    def build_capability_snapshot_from_card(
        self,
        *,
        card: AgentCard,
    ) -> ResolvedCapabilitySnapshot:
        return self._capabilities.build_capability_snapshot_from_card(card=card)

    @staticmethod
    def _require_session_binding_extension(
        snapshot: ResolvedCapabilitySnapshot,
    ) -> ResolvedSessionBindingExtension:
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

    @staticmethod
    def _require_invoke_metadata_extension(
        snapshot: ResolvedCapabilitySnapshot,
    ) -> ResolvedInvokeMetadataExtension:
        if snapshot.invoke_metadata.ext is not None:
            return snapshot.invoke_metadata.ext
        if snapshot.invoke_metadata.status == "invalid":
            raise A2AExtensionContractError(
                snapshot.invoke_metadata.error or "Invoke metadata contract is invalid"
            )
        raise A2AExtensionNotSupportedError(
            snapshot.invoke_metadata.error or "Invoke metadata extension not found"
        )

    async def _run_upstream_discovery(
        self,
        *,
        runtime: A2ARuntime,
        snapshot: ResolvedCapabilitySnapshot,
        method_key: str,
        delegate: Callable[..., Awaitable[ExtensionCallResult]],
        capability_name: str = "Upstream discovery",
        meta_extra: dict[str, Any] | None = None,
        delegate_kwargs: dict[str, Any] | None = None,
    ) -> ExtensionCallResult:
        discovery_capability = self._capabilities.resolve_upstream_method_family(
            snapshot,
            "discovery",
        )
        capability, jsonrpc_url = (
            self._capabilities.require_declared_method_collection_capability(
                discovery_capability,
                capability_name=capability_name,
            )
        )
        method = self._capabilities.require_declared_method_capability(
            capability,
            method_key=method_key,
            capability_name=capability_name,
        )
        preflight = self._capabilities.preflight_wire_contract_method(
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

        meta = {
            "extension_uri": (
                snapshot.wire_contract.ext.uri
                if snapshot.wire_contract.ext is not None
                else None
            ),
            "capability_area": "upstream_discovery",
            "method_name": method.method,
        }
        if meta_extra:
            meta.update(meta_extra)
        kwargs = dict(delegate_kwargs or {})
        kwargs.update(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method.method or UPSTREAM_DISCOVERY_METHODS[method_key],
            meta=meta,
        )
        return await delegate(**kwargs)

    async def _resolve_session_extension_runtime(
        self,
        *,
        runtime: A2ARuntime,
    ) -> tuple[ResolvedCapabilitySnapshot, ResolvedSessionQueryRuntimeCapability]:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability = self._capabilities.require_session_query_capability(
            snapshot.session_query
        )
        return snapshot, capability

    async def resolve_session_binding(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ResolvedSessionBindingExtension:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return self._require_session_binding_extension(snapshot)

    async def resolve_invoke_metadata(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ResolvedInvokeMetadataExtension:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return self._require_invoke_metadata_extension(snapshot)

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
        return await self._session_ops.list_sessions(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
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
        return await self._session_ops.get_session_messages(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
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
        return await self._session_ops.continue_session(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
            session_id=session_id,
        )

    async def prompt_session_async(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        working_directory: str | None = None,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_prompt_session_async(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        return await self._session_ops.prompt_session_async(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
            working_directory=working_directory,
        )

    async def append_session_control(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        working_directory: str | None = None,
    ) -> ExtensionCallResult:
        if not isinstance(request_payload, dict):
            raise ValueError("request must be an object")
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return await self._session_ops.append_session_control(
            runtime=runtime,
            snapshot=snapshot,
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
            working_directory=working_directory,
        )

    async def command_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        working_directory: str | None = None,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_command(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        return await self._session_ops.command_session(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
            working_directory=working_directory,
        )

    async def get_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        return await self._session_ops.get_session(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
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
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        return await self._session_ops.get_session_children(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
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
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        return await self._session_ops.get_session_todo(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
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
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        return await self._session_ops.get_session_diff(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
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
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        return await self._session_ops.get_session_message(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
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
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        return await self._session_ops.fork_session(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
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
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        return await self._session_ops.share_session(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
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
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        return await self._session_ops.unshare_session(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
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
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        return await self._session_ops.summarize_session(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
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
        return await self._session_ops.revert_session(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
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
        snapshot, capability = await self._resolve_session_extension_runtime(
            runtime=runtime
        )
        return await self._session_ops.unrevert_session(
            runtime=runtime,
            snapshot=snapshot,
            capability=capability,
            session_id=session_id,
            metadata=metadata,
        )

    async def list_model_providers(
        self,
        *,
        runtime: A2ARuntime,
        session_metadata: Optional[Dict[str, Any]] = None,
        working_directory: str | None = None,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._capabilities.require_provider_discovery_capability(
            snapshot.provider_discovery
        )
        preflight = self._capabilities.preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=ext.uri,
            method_name=ext.methods.get("list_providers"),
        )
        if preflight is not None:
            return preflight
        return await self._provider_discovery.list_model_providers(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            session_metadata=session_metadata,
            working_directory=working_directory,
        )

    async def list_models(
        self,
        *,
        runtime: A2ARuntime,
        provider_id: str | None = None,
        session_metadata: Optional[Dict[str, Any]] = None,
        working_directory: str | None = None,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._capabilities.require_provider_discovery_capability(
            snapshot.provider_discovery
        )
        preflight = self._capabilities.preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=ext.uri,
            method_name=ext.methods.get("list_models"),
        )
        if preflight is not None:
            return preflight
        return await self._provider_discovery.list_models(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            provider_id=provider_id,
            session_metadata=session_metadata,
            working_directory=working_directory,
        )

    async def list_upstream_skills(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return await self._run_upstream_discovery(
            runtime=runtime,
            snapshot=snapshot,
            method_key="skillsList",
            delegate=self._upstream_discovery.list_skills,
        )

    async def list_upstream_apps(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return await self._run_upstream_discovery(
            runtime=runtime,
            snapshot=snapshot,
            method_key="appsList",
            delegate=self._upstream_discovery.list_apps,
        )

    async def list_upstream_plugins(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return await self._run_upstream_discovery(
            runtime=runtime,
            snapshot=snapshot,
            method_key="pluginsList",
            delegate=self._upstream_discovery.list_plugins,
        )

    async def read_upstream_plugin(
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
        return await self._run_upstream_discovery(
            runtime=runtime,
            snapshot=snapshot,
            method_key="pluginsRead",
            delegate=self._upstream_discovery.read_plugin,
            meta_extra={
                "marketplace_path": resolved_marketplace_path,
                "plugin_name": resolved_plugin_name,
            },
            delegate_kwargs={
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
        working_directory: str | None = None,
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
        ext, jsonrpc_url = self._capabilities.require_interrupt_callback_capability(
            snapshot.interrupt_callback
        )
        return await self._interrupt_extensions.reply_permission_interrupt(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            request_id=resolved_request_id,
            reply=resolved_reply,
            metadata=normalized_metadata,
            working_directory=working_directory,
        )

    async def reply_question_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        answers: list[list[str]],
        metadata: Optional[Dict[str, Any]] = None,
        working_directory: str | None = None,
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
        ext, jsonrpc_url = self._capabilities.require_interrupt_callback_capability(
            snapshot.interrupt_callback
        )
        return await self._interrupt_extensions.reply_question_interrupt(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            request_id=resolved_request_id,
            answers=resolved_answers,
            metadata=normalized_metadata,
            working_directory=working_directory,
        )

    async def reject_question_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        working_directory: str | None = None,
    ) -> ExtensionCallResult:
        (
            resolved_request_id,
            normalized_metadata,
        ) = self._interrupt_extensions.prepare_reject_question_interrupt(
            request_id=request_id,
            metadata=metadata,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._capabilities.require_interrupt_callback_capability(
            snapshot.interrupt_callback
        )
        return await self._interrupt_extensions.reject_question_interrupt(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            request_id=resolved_request_id,
            metadata=normalized_metadata,
            working_directory=working_directory,
        )

    async def recover_interrupts(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str | None = None,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._capabilities.require_interrupt_recovery_capability(
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
        working_directory: str | None = None,
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
        ext, jsonrpc_url = self._capabilities.require_interrupt_callback_capability(
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
            working_directory=working_directory,
        )

    async def reply_elicitation_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        action: str,
        content: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
        working_directory: str | None = None,
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
        ext, jsonrpc_url = self._capabilities.require_interrupt_callback_capability(
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
            working_directory=working_directory,
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
