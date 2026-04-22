"""Session-oriented helper operations for A2A extension services."""

from __future__ import annotations

from typing import Any, Dict, Optional, cast

from app.features.agents.personal.runtime import A2ARuntime
from app.integrations.a2a_extensions.contract_utils import as_dict
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.service_capabilities import (
    CODEX_TURN_CONTROL_BUSINESS_CODE_MAP,
    CODEX_TURN_CONTROL_URI,
    CODEX_TURNS_METHODS,
    A2AExtensionCapabilityService,
)
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.session_extension_service import (
    SessionExtensionService,
)
from app.integrations.a2a_extensions.shared_support import A2AExtensionSupport
from app.integrations.a2a_extensions.types import (
    ResolvedInvokeMetadataExtension,
    ResolvedSessionBindingExtension,
)


class A2AExtensionSessionOperations:
    """Runs session-oriented extension methods with shared preflight checks."""

    def __init__(
        self,
        *,
        support: A2AExtensionSupport,
        session_extensions: SessionExtensionService,
        capabilities: A2AExtensionCapabilityService,
    ) -> None:
        self._support = support
        self._session_extensions = session_extensions
        self._capabilities = capabilities

    @staticmethod
    def pick_optional_text(
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
    def resolve_shared_stream_turn_identity(
        cls,
        metadata: Dict[str, Any] | None,
    ) -> tuple[str | None, str | None]:
        normalized_metadata = as_dict(metadata)
        shared = as_dict(normalized_metadata.get("shared"))
        stream = as_dict(shared.get("stream"))
        thread_id = cls.pick_optional_text(stream, keys=("thread_id", "threadId"))
        turn_id = cls.pick_optional_text(stream, keys=("turn_id", "turnId"))
        return thread_id, turn_id

    @staticmethod
    def strip_shared_metadata_for_upstream(
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

    def prepare_codex_turn_steer(
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
            "request": {"parts": list(parts)},
        }

    async def steer_codex_turn(
        self,
        *,
        runtime: A2ARuntime,
        jsonrpc_url: str,
        session_id: str,
        thread_id: str,
        turn_id: str,
        request_payload: Dict[str, Any],
    ) -> ExtensionCallResult:
        method_name = CODEX_TURNS_METHODS["steer"]
        params = self.prepare_codex_turn_steer(
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

        metric_key = f"{CODEX_TURN_CONTROL_URI}:{method_name}"
        meta = {
            "extension_uri": CODEX_TURN_CONTROL_URI,
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
            business_code_map=CODEX_TURN_CONTROL_BUSINESS_CODE_MAP,
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
        snapshot: Any,
    ) -> ResolvedSessionBindingExtension:
        if snapshot.session_binding.ext is not None:
            return cast(ResolvedSessionBindingExtension, snapshot.session_binding.ext)
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
        snapshot: Any,
    ) -> ResolvedInvokeMetadataExtension:
        if snapshot.invoke_metadata.ext is not None:
            return cast(ResolvedInvokeMetadataExtension, snapshot.invoke_metadata.ext)
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
        snapshot: Any,
        capability: Any,
        page: int,
        size: Optional[int],
        query: Optional[Dict[str, Any]],
        filters: Optional[Dict[str, Any]],
        include_raw: bool,
    ) -> ExtensionCallResult:
        preflight = self._capabilities.preflight_wire_contract_method(
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
        snapshot: Any,
        capability: Any,
        session_id: str,
        page: int,
        size: Optional[int],
        before: str | None,
        query: Optional[Dict[str, Any]],
        include_raw: bool,
    ) -> ExtensionCallResult:
        preflight = self._capabilities.preflight_wire_contract_method(
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
        snapshot: Any,
        capability: Any,
        session_id: str,
    ) -> ExtensionCallResult:
        preflight = self._capabilities.preflight_wire_contract_method(
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
        snapshot: Any,
        capability: Any,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]],
        working_directory: str | None = None,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_prompt_session_async(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
            working_directory=working_directory,
        )
        preflight = self._capabilities.preflight_wire_contract_method(
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
            working_directory=working_directory,
        )

    async def append_session_control(
        self,
        *,
        runtime: A2ARuntime,
        snapshot: Any,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]],
        working_directory: str | None = None,
    ) -> ExtensionCallResult:
        if not isinstance(request_payload, dict):
            raise ValueError("request must be an object")

        thread_id, turn_id = self.resolve_shared_stream_turn_identity(metadata)
        metadata_for_upstream = self.strip_shared_metadata_for_upstream(metadata)
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
            preflight = self._capabilities.preflight_wire_contract_method(
                snapshot=snapshot.wire_contract,
                extension_uri=CODEX_TURN_CONTROL_URI,
                method_name=steer_capability.method,
            )
            if preflight is not None:
                return preflight
            return await self.steer_codex_turn(
                runtime=runtime,
                jsonrpc_url=snapshot.codex_turns.jsonrpc_url,
                session_id=session_id,
                thread_id=thread_id,
                turn_id=turn_id,
                request_payload=request_payload,
            )

        capability = self._capabilities.require_session_query_capability(
            snapshot.session_query
        )
        self._session_extensions.prepare_prompt_session_async(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata_for_upstream,
            working_directory=working_directory,
        )
        preflight = self._capabilities.preflight_wire_contract_method(
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
            working_directory=working_directory,
        )

    async def command_session(
        self,
        *,
        runtime: A2ARuntime,
        snapshot: Any,
        capability: Any,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]],
        working_directory: str | None = None,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_command(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
            working_directory=working_directory,
        )
        preflight = self._capabilities.preflight_wire_contract_method(
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
            working_directory=working_directory,
        )

    async def get_session(
        self,
        *,
        runtime: A2ARuntime,
        snapshot: Any,
        capability: Any,
        session_id: str,
        include_raw: bool,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_lookup(session_id=session_id)
        preflight = self._capabilities.preflight_wire_contract_method(
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
        snapshot: Any,
        capability: Any,
        session_id: str,
        include_raw: bool,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_lookup(session_id=session_id)
        preflight = self._capabilities.preflight_wire_contract_method(
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
        snapshot: Any,
        capability: Any,
        session_id: str,
        include_raw: bool,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_lookup(session_id=session_id)
        preflight = self._capabilities.preflight_wire_contract_method(
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
        snapshot: Any,
        capability: Any,
        session_id: str,
        message_id: str | None,
        include_raw: bool,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_lookup(session_id=session_id)
        preflight = self._capabilities.preflight_wire_contract_method(
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
        snapshot: Any,
        capability: Any,
        session_id: str,
        message_id: str,
        include_raw: bool,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_message_lookup(
            session_id=session_id,
            message_id=message_id,
        )
        preflight = self._capabilities.preflight_wire_contract_method(
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
        snapshot: Any,
        capability: Any,
        session_id: str,
        request_payload: Optional[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]],
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_action(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )
        preflight = self._capabilities.preflight_wire_contract_method(
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
        snapshot: Any,
        capability: Any,
        session_id: str,
        metadata: Optional[Dict[str, Any]],
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_action(
            session_id=session_id,
            metadata=metadata,
        )
        preflight = self._capabilities.preflight_wire_contract_method(
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
        snapshot: Any,
        capability: Any,
        session_id: str,
        metadata: Optional[Dict[str, Any]],
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_action(
            session_id=session_id,
            metadata=metadata,
        )
        preflight = self._capabilities.preflight_wire_contract_method(
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
        snapshot: Any,
        capability: Any,
        session_id: str,
        request_payload: Optional[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]],
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_summarize(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )
        preflight = self._capabilities.preflight_wire_contract_method(
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
        snapshot: Any,
        capability: Any,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]],
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_revert(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )
        preflight = self._capabilities.preflight_wire_contract_method(
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
        snapshot: Any,
        capability: Any,
        session_id: str,
        metadata: Optional[Dict[str, Any]],
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_action(
            session_id=session_id,
            metadata=metadata,
        )
        preflight = self._capabilities.preflight_wire_contract_method(
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
