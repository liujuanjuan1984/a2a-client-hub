"""Service facade for A2A Agent Card extensions."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from app.core.logging import get_logger
from app.features.agents.personal.runtime import A2ARuntime
from app.integrations.a2a_extensions.capability_snapshot import (
    ResolvedCapabilitySnapshot,
)
from app.integrations.a2a_extensions.codex_discovery_service import (
    CodexDiscoveryService,
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
from app.integrations.a2a_extensions.service_capabilities import (
    A2AExtensionCapabilityService,
)
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.service_extension_ops import (
    A2AExtensionOperations,
)
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

logger = get_logger(__name__)


class A2AExtensionsService:
    def __init__(self) -> None:
        self._support = A2AExtensionSupport()
        self._session_extensions = SessionExtensionService(self._support)
        self._interrupt_extensions = InterruptExtensionService(self._support)
        self._interrupt_recovery = InterruptRecoveryService(self._support)
        self._opencode_discovery = OpencodeDiscoveryService(self._support)
        self._codex_discovery = CodexDiscoveryService(self._support)
        self._capabilities = A2AExtensionCapabilityService(
            support=self._support,
            time_module=time,
        )
        self._session_ops = A2AExtensionSessionOperations(
            support=self._support,
            session_extensions=self._session_extensions,
            capabilities=self._capabilities,
        )
        self._extension_ops = A2AExtensionOperations(
            capabilities=self._capabilities,
            opencode_discovery=self._opencode_discovery,
            codex_discovery=self._codex_discovery,
            interrupt_extensions=self._interrupt_extensions,
            interrupt_recovery=self._interrupt_recovery,
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
        return await self._session_ops.resolve_session_binding(snapshot=snapshot)

    async def resolve_invoke_metadata(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ResolvedInvokeMetadataExtension:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return await self._session_ops.resolve_invoke_metadata(snapshot=snapshot)

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
            working_directory=working_directory,
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
            working_directory=working_directory,
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
        return await self._extension_ops.list_model_providers(
            runtime=runtime,
            snapshot=snapshot,
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
        return await self._extension_ops.list_models(
            runtime=runtime,
            snapshot=snapshot,
            provider_id=provider_id,
            session_metadata=session_metadata,
            working_directory=working_directory,
        )

    async def list_codex_skills(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return await self._extension_ops.run_codex_discovery(
            runtime=runtime,
            snapshot=snapshot,
            method_key="skillsList",
            delegate_name="list_skills",
        )

    async def list_codex_apps(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return await self._extension_ops.run_codex_discovery(
            runtime=runtime,
            snapshot=snapshot,
            method_key="appsList",
            delegate_name="list_apps",
        )

    async def list_codex_plugins(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return await self._extension_ops.run_codex_discovery(
            runtime=runtime,
            snapshot=snapshot,
            method_key="pluginsList",
            delegate_name="list_plugins",
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
        return await self._extension_ops.run_codex_discovery(
            runtime=runtime,
            snapshot=snapshot,
            method_key="pluginsRead",
            delegate_name="read_plugin",
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
        self._interrupt_extensions.prepare_reply_permission_interrupt(
            request_id=request_id,
            reply=reply,
            metadata=metadata,
            working_directory=working_directory,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return await self._extension_ops.reply_permission_interrupt(
            runtime=runtime,
            snapshot=snapshot,
            request_id=request_id,
            reply=reply,
            metadata=metadata,
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
        self._interrupt_extensions.prepare_reply_question_interrupt(
            request_id=request_id,
            answers=answers,
            metadata=metadata,
            working_directory=working_directory,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return await self._extension_ops.reply_question_interrupt(
            runtime=runtime,
            snapshot=snapshot,
            request_id=request_id,
            answers=answers,
            metadata=metadata,
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
        self._interrupt_extensions.prepare_reject_question_interrupt(
            request_id=request_id,
            metadata=metadata,
            working_directory=working_directory,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return await self._extension_ops.reject_question_interrupt(
            runtime=runtime,
            snapshot=snapshot,
            request_id=request_id,
            metadata=metadata,
            working_directory=working_directory,
        )

    async def recover_interrupts(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str | None = None,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return await self._extension_ops.recover_interrupts(
            runtime=runtime,
            snapshot=snapshot,
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
        self._interrupt_extensions.prepare_reply_permissions_interrupt(
            request_id=request_id,
            permissions=permissions,
            scope=scope,
            metadata=metadata,
            working_directory=working_directory,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return await self._extension_ops.reply_permissions_interrupt(
            runtime=runtime,
            snapshot=snapshot,
            request_id=request_id,
            permissions=permissions,
            scope=scope,
            metadata=metadata,
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
        self._interrupt_extensions.prepare_reply_elicitation_interrupt(
            request_id=request_id,
            action=action,
            content=content,
            metadata=metadata,
            working_directory=working_directory,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        return await self._extension_ops.reply_elicitation_interrupt(
            runtime=runtime,
            snapshot=snapshot,
            request_id=request_id,
            action=action,
            content=content,
            metadata=metadata,
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
