"""Discovery and interrupt helper operations for A2A extension services."""

from __future__ import annotations

from typing import Any, Dict, Optional, cast

from app.features.agents.personal.runtime import A2ARuntime
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
    CODEX_DISCOVERY_METHODS,
    A2AExtensionCapabilityService,
)
from app.integrations.a2a_extensions.service_common import ExtensionCallResult


class A2AExtensionOperations:
    """Runs non-session extension operations against resolved capabilities."""

    def __init__(
        self,
        *,
        capabilities: A2AExtensionCapabilityService,
        opencode_discovery: OpencodeDiscoveryService,
        codex_discovery: CodexDiscoveryService,
        interrupt_extensions: InterruptExtensionService,
        interrupt_recovery: InterruptRecoveryService,
    ) -> None:
        self._capabilities = capabilities
        self._opencode_discovery = opencode_discovery
        self._codex_discovery = codex_discovery
        self._interrupt_extensions = interrupt_extensions
        self._interrupt_recovery = interrupt_recovery

    async def list_model_providers(
        self,
        *,
        runtime: A2ARuntime,
        snapshot: Any,
        session_metadata: Optional[Dict[str, Any]],
        working_directory: str | None = None,
    ) -> ExtensionCallResult:
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
        return await self._opencode_discovery.list_model_providers(
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
        snapshot: Any,
        provider_id: str | None,
        session_metadata: Optional[Dict[str, Any]],
        working_directory: str | None = None,
    ) -> ExtensionCallResult:
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
        return await self._opencode_discovery.list_models(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            provider_id=provider_id,
            session_metadata=session_metadata,
            working_directory=working_directory,
        )

    async def run_codex_discovery(
        self,
        *,
        runtime: A2ARuntime,
        snapshot: Any,
        method_key: str,
        delegate_name: str,
        capability_name: str = "Codex discovery",
        meta_extra: dict[str, Any] | None = None,
        delegate_kwargs: dict[str, Any] | None = None,
    ) -> ExtensionCallResult:
        capability, jsonrpc_url = (
            self._capabilities.require_declared_method_collection_capability(
                snapshot.codex_discovery,
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
        delegate = getattr(self._codex_discovery, delegate_name)
        meta = {
            "extension_uri": (
                snapshot.wire_contract.ext.uri
                if snapshot.wire_contract.ext is not None
                else None
            ),
            "capability_area": "codex_discovery",
            "method_name": method.method,
        }
        if meta_extra:
            meta.update(meta_extra)
        kwargs = dict(delegate_kwargs or {})
        kwargs.update(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method.method or CODEX_DISCOVERY_METHODS[method_key],
            meta=meta,
        )
        return cast(ExtensionCallResult, await delegate(**kwargs))

    async def reply_permission_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        snapshot: Any,
        request_id: str,
        reply: str,
        metadata: Optional[Dict[str, Any]],
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
        snapshot: Any,
        request_id: str,
        answers: list[list[str]],
        metadata: Optional[Dict[str, Any]],
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
        snapshot: Any,
        request_id: str,
        metadata: Optional[Dict[str, Any]],
        working_directory: str | None = None,
    ) -> ExtensionCallResult:
        (
            resolved_request_id,
            normalized_metadata,
        ) = self._interrupt_extensions.prepare_reject_question_interrupt(
            request_id=request_id,
            metadata=metadata,
        )
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
        snapshot: Any,
        session_id: str | None,
    ) -> ExtensionCallResult:
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
        snapshot: Any,
        request_id: str,
        permissions: Dict[str, Any],
        scope: str | None,
        metadata: Optional[Dict[str, Any]],
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
        snapshot: Any,
        request_id: str,
        action: str,
        content: Any,
        metadata: Optional[Dict[str, Any]],
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
