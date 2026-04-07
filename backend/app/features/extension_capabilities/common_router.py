"""Shared capability routes for session query and interrupt callbacks.

The hub catalog and user-managed agents expose the same shared extension
surface area but require different runtime builders and error semantics.
This module centralises the route implementations to avoid drift.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, Literal, Optional, Type, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.error_codes import status_code_for_extension_error_code
from app.api.error_handlers import build_error_detail, build_error_response
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.db.transaction import load_for_external_call
from app.integrations.a2a_extensions import get_a2a_extensions_service
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
    A2AExtensionUpstreamError,
)
from app.integrations.a2a_runtime_status_contract import (
    runtime_status_contract_payload,
)
from app.schemas.a2a_compatibility_profile import (
    A2ACompatibilityProfileDiagnostic,
    A2ACompatibilityProfileEntry,
)
from app.schemas.a2a_extension import (
    A2ACodexDiscoveryAppsListResponse,
    A2ACodexDiscoveryPluginReadRequest,
    A2ACodexDiscoveryPluginReadResponse,
    A2ACodexDiscoveryPluginsListResponse,
    A2ACodexDiscoverySkillsListResponse,
    A2ADeclaredMethodCapabilityResponse,
    A2ADeclaredMethodCollectionCapabilitiesResponse,
    A2ADeclaredSingleMethodCapabilitiesResponse,
    A2AExtensionCapabilitiesResponse,
    A2AExtensionElicitationReplyRequest,
    A2AExtensionInterruptRecoveryRequest,
    A2AExtensionPermissionReplyRequest,
    A2AExtensionPermissionsReplyRequest,
    A2AExtensionPromptAsyncRequest,
    A2AExtensionQueryResponse,
    A2AExtensionQuestionRejectRequest,
    A2AExtensionQuestionReplyRequest,
    A2AExtensionResponse,
    A2AExtensionSessionCommandRequest,
    A2AExtensionSessionListQueryRequest,
    A2AExtensionSessionMessagesQueryRequest,
    A2AExtensionSessionMutationRequest,
    A2AInterruptRecoveryCapabilitiesResponse,
    A2AInterruptRecoveryResponse,
    A2AInvokeMetadataCapabilitiesResponse,
    A2AInvokeMetadataFieldResponse,
    A2AModelDiscoveryRequest,
    A2ARequestExecutionOptionsCapabilitiesResponse,
    A2ARuntimeStatusContractResponse,
    A2ASessionControlCapabilitiesResponse,
    A2ASessionControlMethodResponse,
    A2AStreamHintsCapabilitiesResponse,
    A2AWireContractCapabilitiesResponse,
    A2AWireContractConditionalMethodResponse,
    A2AWireContractUnsupportedMethodErrorResponse,
)
from app.utils.logging_redaction import redact_url_for_logging

logger = get_logger(__name__)

BuildRuntimeFn = Callable[..., Awaitable[Any]]


def _parse_query_param(value: Optional[str]) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    try:
        parsed = json.loads(trimmed)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="query must be valid JSON") from exc
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="query must be a JSON object")
    return dict(parsed)


def _summarize_query_object(query: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not query:
        return {"keys": [], "size": 0}
    keys = sorted(str(k) for k in query.keys())[:20]
    return {"keys": keys, "size": len(query)}


def _summarize_metadata_keys(metadata: Optional[Dict[str, Any]]) -> list[str]:
    if not metadata:
        return []
    return sorted(str(k) for k in metadata.keys())[:20]


def _summarize_object_keys(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not value:
        return {"keys": [], "size": 0}
    return {
        "keys": sorted(str(key) for key in value.keys())[:20],
        "size": len(value),
    }


def _build_session_list_filters(
    *,
    directory: Optional[str] = None,
    roots: Optional[bool] = None,
    start: Optional[int] = None,
    search: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    filters: Dict[str, Any] = {}
    if directory is not None:
        filters["directory"] = directory
    if roots is not None:
        filters["roots"] = roots
    if start is not None:
        filters["start"] = start
    if search is not None:
        filters["search"] = search
    return filters or None


def _summarize_session_list_filters(
    filters: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not filters:
        return {"keys": [], "size": 0}
    return {
        "keys": sorted(str(key) for key in filters.keys())[:20],
        "size": len(filters),
    }


_SESSION_CONTROL_HUB_CONSUMPTION = {
    "prompt_async": True,
    "command": True,
    "shell": False,
}


def _build_session_control_response(
    snapshot: Any,
) -> A2ASessionControlCapabilitiesResponse:
    resolved_methods = {}
    capability = getattr(snapshot.session_query, "capability", None)
    if capability is not None:
        resolved_methods = dict(getattr(capability, "control_methods", {}) or {})

    def _build_method(method_key: str) -> A2ASessionControlMethodResponse:
        resolved = resolved_methods.get(method_key)
        availability: Literal["always", "conditional", "unsupported"] = cast(
            Literal["always", "conditional", "unsupported"],
            getattr(resolved, "availability", "unsupported"),
        )
        return A2ASessionControlMethodResponse(
            declared=bool(getattr(resolved, "declared", False)),
            consumedByHub=_SESSION_CONTROL_HUB_CONSUMPTION[method_key],
            availability=availability,
            method=getattr(resolved, "method", None),
            enabledByDefault=getattr(resolved, "enabled_by_default", None),
            configKey=getattr(resolved, "config_key", None),
        )

    return A2ASessionControlCapabilitiesResponse(
        promptAsync=_build_method("prompt_async"),
        command=_build_method("command"),
        shell=_build_method("shell"),
    )


def _build_compatibility_profile_response(
    snapshot: Any,
) -> A2ACompatibilityProfileDiagnostic:
    compatibility_snapshot = getattr(snapshot, "compatibility_profile", None)
    status = cast(
        Literal["supported", "unsupported", "invalid"],
        getattr(compatibility_snapshot, "status", "unsupported"),
    )
    error = getattr(compatibility_snapshot, "error", None)
    ext = getattr(compatibility_snapshot, "ext", None)
    if ext is None:
        return A2ACompatibilityProfileDiagnostic(
            declared=status != "unsupported",
            status=status,
            error=error,
        )

    return A2ACompatibilityProfileDiagnostic(
        declared=True,
        status=status,
        uri=getattr(ext, "uri", None),
        extensionRetention={
            name: A2ACompatibilityProfileEntry.model_validate(entry)
            for name, entry in dict(getattr(ext, "extension_retention", {})).items()
        },
        methodRetention={
            name: A2ACompatibilityProfileEntry.model_validate(entry)
            for name, entry in dict(getattr(ext, "method_retention", {})).items()
        },
        serviceBehaviors=dict(getattr(ext, "service_behaviors", {}) or {}),
        consumerGuidance=list(getattr(ext, "consumer_guidance", ()) or ()),
        error=error,
    )


def _build_invoke_metadata_response(
    snapshot: Any,
) -> A2AInvokeMetadataCapabilitiesResponse:
    invoke_snapshot = getattr(snapshot, "invoke_metadata", None)
    ext = getattr(invoke_snapshot, "ext", None)
    fields = list(getattr(ext, "fields", ()) or ())
    return A2AInvokeMetadataCapabilitiesResponse(
        declared=bool(
            getattr(
                invoke_snapshot,
                "meta",
                {},
            ).get("invoke_metadata_declared", ext is not None)
        ),
        consumedByHub=True,
        status=cast(
            Literal["supported", "unsupported", "invalid"],
            getattr(invoke_snapshot, "status", "unsupported"),
        ),
        metadataField=getattr(ext, "metadata_field", None),
        appliesToMethods=list(getattr(ext, "applies_to_methods", ()) or ()),
        fields=[
            A2AInvokeMetadataFieldResponse(
                name=item.name,
                required=item.required,
                description=item.description,
            )
            for item in fields
        ],
        error=getattr(invoke_snapshot, "error", None),
    )


def _build_request_execution_options_response(
    snapshot: Any,
) -> A2ARequestExecutionOptionsCapabilitiesResponse:
    capability = getattr(snapshot, "request_execution_options", None)
    return A2ARequestExecutionOptionsCapabilitiesResponse(
        declared=bool(getattr(capability, "declared", False)),
        consumedByHub=bool(getattr(capability, "consumed_by_hub", False)),
        status=cast(
            Literal["unsupported", "declared_not_consumed", "invalid"],
            getattr(capability, "status", "unsupported"),
        ),
        metadataField=getattr(capability, "metadata_field", None),
        fields=list(getattr(capability, "fields", ()) or ()),
        persistsForThread=getattr(capability, "persists_for_thread", None),
        sourceExtensions=list(getattr(capability, "source_extensions", ()) or ()),
        notes=list(getattr(capability, "notes", ()) or ()),
        error=getattr(capability, "error", None),
    )


def _build_stream_hints_response(
    snapshot: Any,
) -> A2AStreamHintsCapabilitiesResponse:
    capability = getattr(snapshot, "stream_hints", None)
    ext = getattr(capability, "ext", None)
    meta = dict(getattr(capability, "meta", {}) or {})
    return A2AStreamHintsCapabilitiesResponse(
        declared=bool(meta.get("stream_hints_declared", ext is not None)),
        consumedByHub=ext is not None,
        status=cast(
            Literal["supported", "unsupported", "invalid"],
            getattr(capability, "status", "unsupported"),
        ),
        streamField=getattr(ext, "stream_field", None),
        usageField=getattr(ext, "usage_field", None),
        interruptField=getattr(ext, "interrupt_field", None),
        sessionField=getattr(ext, "session_field", None),
        mode=cast(Optional[str], meta.get("stream_hints_mode")),
        fallbackUsed=cast(Optional[bool], meta.get("stream_hints_fallback_used")),
        error=getattr(capability, "error", None),
    )


def _build_interrupt_recovery_details_response(
    snapshot: Any,
) -> A2AInterruptRecoveryCapabilitiesResponse:
    capability = getattr(snapshot, "interrupt_recovery", None)
    ext = getattr(capability, "ext", None)
    compatibility = getattr(
        getattr(snapshot, "compatibility_profile", None), "ext", None
    )

    extension_entry = None
    if compatibility is not None:
        extension_entry = dict(
            getattr(compatibility, "extension_retention", {}) or {}
        ).get(getattr(ext, "uri", None))

    methods = dict(getattr(ext, "methods", {}) or {})
    non_null_methods = {
        key: value for key, value in methods.items() if isinstance(value, str) and value
    }
    method_entries = []
    if compatibility is not None:
        retention_map = dict(getattr(compatibility, "method_retention", {}) or {})
        method_entries = [
            retention_map.get(method_name)
            for method_name in non_null_methods.values()
            if retention_map.get(method_name) is not None
        ]

    implementation_scope = getattr(ext, "implementation_scope", None) or getattr(
        extension_entry, "implementation_scope", None
    )
    identity_scope = getattr(ext, "identity_scope", None) or getattr(
        extension_entry, "identity_scope", None
    )
    if identity_scope is None:
        for entry in method_entries:
            if getattr(entry, "identity_scope", None):
                identity_scope = getattr(entry, "identity_scope", None)
                break
    if implementation_scope is None:
        for entry in method_entries:
            if getattr(entry, "implementation_scope", None):
                implementation_scope = getattr(entry, "implementation_scope", None)
                break

    return A2AInterruptRecoveryCapabilitiesResponse(
        declared=ext is not None,
        consumedByHub=ext is not None,
        status=cast(
            Literal["supported", "unsupported", "invalid"],
            getattr(capability, "status", "unsupported"),
        ),
        provider=getattr(ext, "provider", None),
        methods=non_null_methods,
        recoveryDataSource=getattr(ext, "recovery_data_source", None),
        identityScope=identity_scope,
        implementationScope=implementation_scope,
        emptyResultWhenIdentityUnavailable=getattr(
            ext, "empty_result_when_identity_unavailable", None
        ),
        error=getattr(capability, "error", None),
    )


def _build_wire_contract_response(
    snapshot: Any,
) -> A2AWireContractCapabilitiesResponse:
    wire_snapshot = getattr(snapshot, "wire_contract", None)
    ext = getattr(wire_snapshot, "ext", None)
    status = cast(
        Literal["supported", "unsupported", "invalid"],
        getattr(wire_snapshot, "status", "unsupported"),
    )
    error = getattr(wire_snapshot, "error", None)
    if ext is None:
        return A2AWireContractCapabilitiesResponse(
            declared=status != "unsupported",
            consumedByHub=True,
            status=status,
            error=error,
        )

    return A2AWireContractCapabilitiesResponse(
        declared=True,
        consumedByHub=True,
        status=status,
        protocolVersion=ext.protocol_version,
        preferredTransport=ext.preferred_transport,
        additionalTransports=list(ext.additional_transports),
        allJsonrpcMethods=list(ext.all_jsonrpc_methods),
        extensionUris=list(ext.extension_uris),
        conditionalMethods={
            name: A2AWireContractConditionalMethodResponse(
                reason=item.reason,
                toggle=item.toggle,
            )
            for name, item in dict(ext.conditionally_available_methods).items()
        },
        unsupportedMethodError=A2AWireContractUnsupportedMethodErrorResponse(
            code=ext.unsupported_method_error.code,
            type=ext.unsupported_method_error.type,
            dataFields=list(ext.unsupported_method_error.data_fields),
        ),
        error=error,
    )


def _build_declared_method_capability_response(
    capability: Any,
) -> A2ADeclaredMethodCapabilityResponse:
    raw_availability = getattr(capability, "availability", None)
    return A2ADeclaredMethodCapabilityResponse(
        declared=bool(getattr(capability, "declared", False)),
        consumedByHub=bool(getattr(capability, "consumed_by_hub", False)),
        method=getattr(capability, "method", None),
        availability=cast(
            Literal["always", "enabled", "disabled", "unsupported"],
            (
                raw_availability
                if raw_availability is not None
                else (
                    "always"
                    if bool(getattr(capability, "declared", False))
                    else "unsupported"
                )
            ),
        ),
        configKey=getattr(capability, "config_key", None),
        reason=getattr(capability, "reason", None),
        retention=getattr(capability, "retention", None),
    )


def _build_declared_method_collection_response(
    capability: Any,
) -> A2ADeclaredMethodCollectionCapabilitiesResponse:
    methods = dict(getattr(capability, "methods", {}) or {})
    status = cast(
        Literal[
            "unsupported",
            "declared_not_consumed",
            "partially_consumed",
            "supported",
            "unsupported_by_design",
        ],
        getattr(capability, "status", "unsupported"),
    )
    return A2ADeclaredMethodCollectionCapabilitiesResponse(
        declared=bool(getattr(capability, "declared", False)),
        consumedByHub=bool(getattr(capability, "consumed_by_hub", False)),
        status=status,
        methods={
            name: _build_declared_method_capability_response(item)
            for name, item in methods.items()
        },
        declarationSource=getattr(capability, "declaration_source", None),
        declarationConfidence=getattr(capability, "declaration_confidence", None),
        negotiationState=getattr(capability, "negotiation_state", None),
        diagnosticNote=getattr(capability, "diagnostic_note", None),
    )


def _build_declared_single_method_response(
    capability: Any,
) -> A2ADeclaredSingleMethodCapabilitiesResponse:
    status = cast(
        Literal["unsupported", "unsupported_by_design"],
        getattr(capability, "status", "unsupported"),
    )
    return A2ADeclaredSingleMethodCapabilitiesResponse(
        declared=bool(getattr(capability, "declared", False)),
        consumedByHub=bool(getattr(capability, "consumed_by_hub", False)),
        status=status,
        method=getattr(capability, "method", None),
    )


def create_extension_capability_router(
    *,
    prefix: str,
    build_runtime: BuildRuntimeFn,
    runtime_not_found_error: Type[Exception],
    runtime_validation_error: Type[Exception],
    runtime_validation_status_code: int,
    log_scope: str,
) -> StrictAPIRouter:
    router = StrictAPIRouter(prefix=prefix, tags=["a2a-extensions"])

    def _scope_message(message: str) -> str:
        return f"{log_scope} {message}".strip()

    async def _get_runtime(db: AsyncSession, current_user: User, agent_id: UUID) -> Any:
        current_user_id = cast(UUID, current_user.id)
        try:
            return await build_runtime(db, user_id=current_user_id, agent_id=agent_id)
        except runtime_not_found_error as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except runtime_validation_error as exc:
            raise HTTPException(
                status_code=runtime_validation_status_code, detail=str(exc)
            ) from exc

    async def _get_runtime_for_external_call(
        db: AsyncSession,
        current_user: User,
        agent_id: UUID,
    ) -> Any:
        return await load_for_external_call(
            db,
            lambda session: _get_runtime(session, current_user, agent_id),
        )

    def _to_extension_response(result: Any) -> A2AExtensionResponse:
        return A2AExtensionResponse(
            success=result.success,
            result=result.result,
            error_code=result.error_code,
            source=result.source,
            jsonrpc_code=result.jsonrpc_code,
            missing_params=result.missing_params,
            upstream_error=result.upstream_error,
            meta=result.meta or {},
        )

    def _to_extension_error_response(
        *,
        error_code: str,
        message: str,
        source: Optional[str] = None,
        jsonrpc_code: Optional[int] = None,
        missing_params: Optional[list[dict[str, Any]]] = None,
        upstream_error: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> JSONResponse:
        return build_error_response(
            status_code=status_code_for_extension_error_code(error_code),
            detail=build_error_detail(
                message=message,
                error_code=error_code,
                source=source,
                jsonrpc_code=jsonrpc_code,
                missing_params=missing_params,
                upstream_error=(
                    upstream_error
                    if upstream_error is not None
                    else {"message": message}
                ),
                meta=meta or {},
            ),
        )

    def _extensions_service() -> Any:
        return cast(Any, get_a2a_extensions_service())

    @router.get(
        "/{agent_id}/extensions/capabilities",
        response_model=A2AExtensionCapabilitiesResponse,
        status_code=status.HTTP_200_OK,
    )
    async def get_extension_capabilities(
        *,
        agent_id: UUID,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionCapabilitiesResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        snapshot = await _extensions_service().resolve_capability_snapshot(
            runtime=runtime
        )
        model_selection = snapshot.model_selection.status == "supported"
        provider_discovery = snapshot.provider_discovery.status == "supported"
        interrupt_recovery = snapshot.interrupt_recovery.status == "supported"
        session_control = _build_session_control_response(snapshot)
        session_prompt_async = (
            session_control.prompt_async.declared
            and session_control.prompt_async.consumed_by_hub
        )

        return A2AExtensionCapabilitiesResponse(
            modelSelection=model_selection,
            providerDiscovery=provider_discovery,
            interruptRecovery=interrupt_recovery,
            interruptRecoveryDetails=_build_interrupt_recovery_details_response(
                snapshot
            ),
            sessionPromptAsync=session_prompt_async,
            sessionControl=session_control,
            invokeMetadata=_build_invoke_metadata_response(snapshot),
            requestExecutionOptions=_build_request_execution_options_response(snapshot),
            streamHints=_build_stream_hints_response(snapshot),
            wireContract=_build_wire_contract_response(snapshot),
            compatibilityProfile=_build_compatibility_profile_response(snapshot),
            codexDiscovery=_build_declared_method_collection_response(
                getattr(snapshot, "codex_discovery", None)
            ),
            codexThreads=_build_declared_method_collection_response(
                getattr(snapshot, "codex_threads", None)
            ),
            codexTurns=_build_declared_method_collection_response(
                getattr(snapshot, "codex_turns", None)
            ),
            codexReview=_build_declared_method_collection_response(
                getattr(snapshot, "codex_review", None)
            ),
            codexThreadWatch=_build_declared_single_method_response(
                getattr(snapshot, "codex_thread_watch", None)
            ),
            codexExec=_build_declared_method_collection_response(
                getattr(snapshot, "codex_exec", None)
            ),
            runtimeStatus=A2ARuntimeStatusContractResponse.model_validate(
                runtime_status_contract_payload()
            ),
        )

    @router.post(
        "/{agent_id}/extensions/models/providers:list",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def list_model_providers(
        *,
        agent_id: UUID,
        payload: A2AModelDiscoveryRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Generic model provider discovery requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_metadata_keys": _summarize_metadata_keys(
                    payload.session_metadata
                ),
            },
        )
        return await _run_extension_call(
            _extensions_service().list_model_providers(
                runtime=runtime,
                session_metadata=payload.session_metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/models:list",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def list_models(
        *,
        agent_id: UUID,
        payload: A2AModelDiscoveryRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Generic model discovery requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "provider_id": payload.provider_id,
                "session_metadata_keys": _summarize_metadata_keys(
                    payload.session_metadata
                ),
            },
        )
        return await _run_extension_call(
            _extensions_service().list_models(
                runtime=runtime,
                provider_id=payload.provider_id,
                session_metadata=payload.session_metadata,
            )
        )

    @router.get(
        "/{agent_id}/extensions/codex/skills",
        response_model=A2ACodexDiscoverySkillsListResponse,
        status_code=status.HTTP_200_OK,
    )
    async def list_codex_skills(
        *,
        agent_id: UUID,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Codex discovery skills list requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
            },
        )
        return await _run_extension_call(
            _extensions_service().list_codex_skills(runtime=runtime)
        )

    @router.get(
        "/{agent_id}/extensions/codex/apps",
        response_model=A2ACodexDiscoveryAppsListResponse,
        status_code=status.HTTP_200_OK,
    )
    async def list_codex_apps(
        *,
        agent_id: UUID,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Codex discovery apps list requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
            },
        )
        return await _run_extension_call(
            _extensions_service().list_codex_apps(runtime=runtime)
        )

    @router.get(
        "/{agent_id}/extensions/codex/plugins",
        response_model=A2ACodexDiscoveryPluginsListResponse,
        status_code=status.HTTP_200_OK,
    )
    async def list_codex_plugins(
        *,
        agent_id: UUID,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Codex discovery plugins list requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
            },
        )
        return await _run_extension_call(
            _extensions_service().list_codex_plugins(runtime=runtime)
        )

    @router.post(
        "/{agent_id}/extensions/codex/plugins:read",
        response_model=A2ACodexDiscoveryPluginReadResponse,
        status_code=status.HTTP_200_OK,
    )
    async def read_codex_plugin(
        *,
        agent_id: UUID,
        payload: A2ACodexDiscoveryPluginReadRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Codex discovery plugin read requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "marketplace_path": payload.marketplace_path,
                "plugin_name": payload.plugin_name,
            },
        )
        return await _run_extension_call(
            _extensions_service().read_codex_plugin(
                runtime=runtime,
                marketplace_path=payload.marketplace_path,
                plugin_name=payload.plugin_name,
            )
        )

    async def _run_extension_call(
        call: Awaitable[Any],
    ) -> A2AExtensionResponse | JSONResponse:
        try:
            result = await call
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (A2AExtensionNotSupportedError, A2AExtensionContractError) as exc:
            error_code = (
                "not_supported"
                if isinstance(exc, A2AExtensionNotSupportedError)
                else "extension_contract_error"
            )
            return _to_extension_error_response(
                error_code=error_code,
                message=str(exc),
            )
        except A2AExtensionUpstreamError as exc:
            response = A2AExtensionResponse(
                success=False,
                error_code=exc.error_code,
                source=exc.source,
                jsonrpc_code=exc.jsonrpc_code,
                missing_params=exc.missing_params,
                upstream_error=exc.upstream_error,
                meta={},
            )
            status_code = status_code_for_extension_error_code(response.error_code)
            if status_code == status.HTTP_200_OK:
                return response
            detail_message = (
                str(response.upstream_error.get("message"))
                if isinstance(response.upstream_error, dict)
                and isinstance(response.upstream_error.get("message"), str)
                else str(exc)
            )
            return build_error_response(
                status_code=status_code,
                detail=build_error_detail(
                    message=detail_message,
                    error_code=response.error_code,
                    source=response.source,
                    jsonrpc_code=response.jsonrpc_code,
                    missing_params=response.missing_params,
                    upstream_error=response.upstream_error,
                    meta=response.meta or {},
                ),
            )
        response = _to_extension_response(result)
        status_code = status_code_for_extension_error_code(response.error_code)
        if response.success or status_code == status.HTTP_200_OK:
            return response
        detail_message = (
            str(response.upstream_error.get("message"))
            if isinstance(response.upstream_error, dict)
            and isinstance(response.upstream_error.get("message"), str)
            else str(response.error_code or "Extension call failed")
        )
        return build_error_response(
            status_code=status_code,
            detail=build_error_detail(
                message=detail_message,
                error_code=response.error_code,
                source=response.source,
                jsonrpc_code=response.jsonrpc_code,
                missing_params=response.missing_params,
                upstream_error=response.upstream_error,
                meta=response.meta or {},
            ),
        )

    @router.get(
        "/{agent_id}/extensions/sessions",
        response_model=A2AExtensionQueryResponse,
        status_code=status.HTTP_200_OK,
        response_model_exclude_none=True,
    )
    async def list_external_sessions(
        *,
        agent_id: UUID,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
        page: int = Query(1, ge=1, description="Page number (1-indexed)"),
        size: Optional[int] = Query(
            None, ge=1, description="Page size (uses card default when omitted)"
        ),
        include_raw: bool = Query(
            False,
            description="Whether to include the upstream raw payload in the response",
        ),
        directory: Optional[str] = Query(
            None,
            min_length=1,
            description="Optional Hub session list directory filter",
        ),
        roots: Optional[bool] = Query(
            None,
            description="Optional Hub roots-only filter for session list",
        ),
        start: Optional[int] = Query(
            None,
            ge=0,
            description="Optional Hub session list start offset filter",
        ),
        search: Optional[str] = Query(
            None,
            min_length=1,
            description="Optional Hub session list search filter",
        ),
        query: Optional[str] = Query(
            None, description="Optional JSON object encoded as a string"
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        query_obj = _parse_query_param(query)
        filter_obj = _build_session_list_filters(
            directory=directory,
            roots=roots,
            start=start,
            search=search,
        )
        logger.info(
            _scope_message("Shared extension sessions list requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "page": page,
                "size": size,
                "include_raw": include_raw,
                "filter_meta": _summarize_session_list_filters(filter_obj),
                "query_meta": _summarize_query_object(query_obj),
            },
        )

        return await _run_extension_call(
            _extensions_service().list_sessions(
                runtime=runtime,
                page=page,
                size=size,
                include_raw=include_raw,
                query=query_obj,
                filters=filter_obj,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:continue",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def continue_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session continue requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
            },
        )

        return await _run_extension_call(
            _extensions_service().continue_session(
                runtime=runtime,
                session_id=session_id,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:prompt-async",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def prompt_external_session_async(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionPromptAsyncRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        request_keys = sorted(payload.request.keys())[:20]
        metadata_keys = _summarize_metadata_keys(payload.metadata)
        logger.info(
            _scope_message("Shared extension session prompt_async requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "request_keys": request_keys,
                "request_parts_count": (
                    len(payload.request.get("parts", []))
                    if isinstance(payload.request.get("parts"), list)
                    else None
                ),
                "metadata_keys": metadata_keys,
            },
        )

        return await _run_extension_call(
            _extensions_service().prompt_session_async(
                runtime=runtime,
                session_id=session_id,
                request_payload=payload.request,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:command",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def command_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionCommandRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        request_keys = sorted(payload.request.keys())[:20]
        metadata_keys = _summarize_metadata_keys(payload.metadata)
        logger.info(
            _scope_message("Shared extension session command requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "request_keys": request_keys,
                "metadata_keys": metadata_keys,
            },
        )

        return await _run_extension_call(
            _extensions_service().command_session(
                runtime=runtime,
                session_id=session_id,
                request_payload=payload.request,
                metadata=payload.metadata,
            )
        )

    @router.get(
        "/{agent_id}/extensions/sessions/{session_id}",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def get_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
        include_raw: bool = Query(
            False,
            description="Whether to include the upstream raw payload in the response",
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session detail requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "include_raw": include_raw,
            },
        )

        return await _run_extension_call(
            _extensions_service().get_session(
                runtime=runtime,
                session_id=session_id,
                include_raw=include_raw,
            )
        )

    @router.get(
        "/{agent_id}/extensions/sessions/{session_id}/children",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def get_external_session_children(
        *,
        agent_id: UUID,
        session_id: str,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
        include_raw: bool = Query(
            False,
            description="Whether to include the upstream raw payload in the response",
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session children requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "include_raw": include_raw,
            },
        )

        return await _run_extension_call(
            _extensions_service().get_session_children(
                runtime=runtime,
                session_id=session_id,
                include_raw=include_raw,
            )
        )

    @router.get(
        "/{agent_id}/extensions/sessions/{session_id}/todo",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def get_external_session_todo(
        *,
        agent_id: UUID,
        session_id: str,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
        include_raw: bool = Query(
            False,
            description="Whether to include the upstream raw payload in the response",
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session todo requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "include_raw": include_raw,
            },
        )

        return await _run_extension_call(
            _extensions_service().get_session_todo(
                runtime=runtime,
                session_id=session_id,
                include_raw=include_raw,
            )
        )

    @router.get(
        "/{agent_id}/extensions/sessions/{session_id}/diff",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def get_external_session_diff(
        *,
        agent_id: UUID,
        session_id: str,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
        message_id: Optional[str] = Query(
            None,
            alias="messageId",
            min_length=1,
            description="Optional message id used to narrow the diff lookup",
        ),
        include_raw: bool = Query(
            False,
            description="Whether to include the upstream raw payload in the response",
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session diff requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "message_id": message_id,
                "include_raw": include_raw,
            },
        )

        return await _run_extension_call(
            _extensions_service().get_session_diff(
                runtime=runtime,
                session_id=session_id,
                message_id=message_id,
                include_raw=include_raw,
            )
        )

    @router.get(
        "/{agent_id}/extensions/sessions/{session_id}/messages/{message_id}",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def get_external_session_message(
        *,
        agent_id: UUID,
        session_id: str,
        message_id: str,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
        include_raw: bool = Query(
            False,
            description="Whether to include the upstream raw payload in the response",
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session message requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "message_id": message_id,
                "include_raw": include_raw,
            },
        )

        return await _run_extension_call(
            _extensions_service().get_session_message(
                runtime=runtime,
                session_id=session_id,
                message_id=message_id,
                include_raw=include_raw,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:fork",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def fork_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionMutationRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session fork requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "request_keys": sorted((payload.request or {}).keys())[:20],
                "metadata_keys": _summarize_metadata_keys(payload.metadata),
            },
        )

        return await _run_extension_call(
            _extensions_service().fork_session(
                runtime=runtime,
                session_id=session_id,
                request_payload=payload.request,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:share",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def share_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionMutationRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session share requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "metadata_keys": _summarize_metadata_keys(payload.metadata),
            },
        )

        return await _run_extension_call(
            _extensions_service().share_session(
                runtime=runtime,
                session_id=session_id,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:unshare",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def unshare_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionMutationRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session unshare requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "metadata_keys": _summarize_metadata_keys(payload.metadata),
            },
        )

        return await _run_extension_call(
            _extensions_service().unshare_session(
                runtime=runtime,
                session_id=session_id,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:summarize",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def summarize_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionMutationRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session summarize requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "request_keys": sorted((payload.request or {}).keys())[:20],
                "metadata_keys": _summarize_metadata_keys(payload.metadata),
            },
        )

        return await _run_extension_call(
            _extensions_service().summarize_session(
                runtime=runtime,
                session_id=session_id,
                request_payload=payload.request,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:revert",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def revert_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionMutationRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session revert requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "request_keys": sorted((payload.request or {}).keys())[:20],
                "metadata_keys": _summarize_metadata_keys(payload.metadata),
            },
        )

        return await _run_extension_call(
            _extensions_service().revert_session(
                runtime=runtime,
                session_id=session_id,
                request_payload=payload.request or {},
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:unrevert",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def unrevert_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionMutationRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session unrevert requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "metadata_keys": _summarize_metadata_keys(payload.metadata),
            },
        )

        return await _run_extension_call(
            _extensions_service().unrevert_session(
                runtime=runtime,
                session_id=session_id,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/interrupts:recover",
        response_model=A2AInterruptRecoveryResponse,
        status_code=status.HTTP_200_OK,
        response_model_exclude_none=True,
    )
    async def recover_interrupts(
        *,
        agent_id: UUID,
        payload: A2AExtensionInterruptRecoveryRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AInterruptRecoveryResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension interrupt recovery requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": payload.session_id,
            },
        )

        result = await _run_extension_call(
            _extensions_service().recover_interrupts(
                runtime=runtime,
                session_id=payload.session_id,
            )
        )
        if isinstance(result, JSONResponse):
            return result
        resolved_result = (
            result.result if isinstance(result.result, dict) else {"items": []}
        )
        items = resolved_result.get("items")
        return A2AInterruptRecoveryResponse.model_validate(
            {"items": items if isinstance(items, list) else []}
        )

    @router.post(
        "/{agent_id}/extensions/interrupts/permission:reply",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def reply_permission_interrupt(
        *,
        agent_id: UUID,
        payload: A2AExtensionPermissionReplyRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension permission interrupt reply requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "request_id": payload.request_id,
                "reply": payload.reply,
                "metadata_keys": _summarize_metadata_keys(payload.metadata),
            },
        )
        return await _run_extension_call(
            _extensions_service().reply_permission_interrupt(
                runtime=runtime,
                request_id=payload.request_id,
                reply=payload.reply,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/interrupts/question:reply",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def reply_question_interrupt(
        *,
        agent_id: UUID,
        payload: A2AExtensionQuestionReplyRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension question interrupt reply requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "request_id": payload.request_id,
                "answers_count": len(payload.answers),
                "metadata_keys": _summarize_metadata_keys(payload.metadata),
            },
        )
        return await _run_extension_call(
            _extensions_service().reply_question_interrupt(
                runtime=runtime,
                request_id=payload.request_id,
                answers=payload.answers,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/interrupts/question:reject",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def reject_question_interrupt(
        *,
        agent_id: UUID,
        payload: A2AExtensionQuestionRejectRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension question interrupt reject requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "request_id": payload.request_id,
                "metadata_keys": _summarize_metadata_keys(payload.metadata),
            },
        )
        return await _run_extension_call(
            _extensions_service().reject_question_interrupt(
                runtime=runtime,
                request_id=payload.request_id,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/interrupts/permissions:reply",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def reply_permissions_interrupt(
        *,
        agent_id: UUID,
        payload: A2AExtensionPermissionsReplyRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension permissions interrupt reply requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "request_id": payload.request_id,
                "scope": payload.scope,
                "permissions_meta": _summarize_object_keys(payload.permissions),
                "metadata_keys": _summarize_metadata_keys(payload.metadata),
            },
        )
        return await _run_extension_call(
            _extensions_service().reply_permissions_interrupt(
                runtime=runtime,
                request_id=payload.request_id,
                permissions=payload.permissions,
                scope=payload.scope,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/interrupts/elicitation:reply",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def reply_elicitation_interrupt(
        *,
        agent_id: UUID,
        payload: A2AExtensionElicitationReplyRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension elicitation interrupt reply requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "request_id": payload.request_id,
                "action": payload.action,
                "has_content": payload.content is not None,
                "metadata_keys": _summarize_metadata_keys(payload.metadata),
            },
        )
        return await _run_extension_call(
            _extensions_service().reply_elicitation_interrupt(
                runtime=runtime,
                request_id=payload.request_id,
                action=payload.action,
                content=payload.content,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions:query",
        response_model=A2AExtensionQueryResponse,
        status_code=status.HTTP_200_OK,
        response_model_exclude_none=True,
    )
    async def query_external_sessions(
        *,
        agent_id: UUID,
        payload: A2AExtensionSessionListQueryRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        filters = (
            payload.filters.model_dump(exclude_none=True)
            if payload.filters is not None
            else None
        )
        logger.info(
            _scope_message("Shared extension sessions list requested (POST)"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "page": payload.page,
                "size": payload.size,
                "include_raw": payload.include_raw,
                "filter_meta": _summarize_session_list_filters(filters),
                "query_meta": _summarize_query_object(payload.query),
            },
        )

        return await _run_extension_call(
            _extensions_service().list_sessions(
                runtime=runtime,
                page=payload.page,
                size=payload.size,
                include_raw=payload.include_raw,
                query=payload.query,
                filters=filters,
            )
        )

    @router.get(
        "/{agent_id}/extensions/sessions/{session_id}/messages",
        response_model=A2AExtensionQueryResponse,
        status_code=status.HTTP_200_OK,
        response_model_exclude_none=True,
    )
    async def list_external_session_messages(
        *,
        agent_id: UUID,
        session_id: str,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
        page: int = Query(1, ge=1, description="Page number (1-indexed)"),
        size: Optional[int] = Query(
            None, ge=1, description="Page size (uses card default when omitted)"
        ),
        before: Optional[str] = Query(
            None,
            min_length=1,
            description=(
                "Opaque cursor for loading older session messages when supported "
                "by the runtime contract"
            ),
        ),
        include_raw: bool = Query(
            False,
            description="Whether to include the upstream raw payload in the response",
        ),
        query: Optional[str] = Query(
            None, description="Optional JSON object encoded as a string"
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        query_obj = _parse_query_param(query)
        logger.info(
            _scope_message("Shared extension session messages requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "page": page,
                "size": size,
                "before": before,
                "include_raw": include_raw,
                "query_meta": _summarize_query_object(query_obj),
            },
        )

        return await _run_extension_call(
            _extensions_service().get_session_messages(
                runtime=runtime,
                session_id=session_id,
                page=page,
                size=size,
                before=before,
                include_raw=include_raw,
                query=query_obj,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}/messages:query",
        response_model=A2AExtensionQueryResponse,
        status_code=status.HTTP_200_OK,
        response_model_exclude_none=True,
    )
    async def query_external_session_messages(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionMessagesQueryRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session messages requested (POST)"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "page": payload.page,
                "size": payload.size,
                "before": payload.before,
                "include_raw": payload.include_raw,
                "query_meta": _summarize_query_object(payload.query),
            },
        )

        return await _run_extension_call(
            _extensions_service().get_session_messages(
                runtime=runtime,
                session_id=session_id,
                page=payload.page,
                size=payload.size,
                before=payload.before,
                include_raw=payload.include_raw,
                query=payload.query,
            )
        )

    return router


__all__ = ["create_extension_capability_router"]
