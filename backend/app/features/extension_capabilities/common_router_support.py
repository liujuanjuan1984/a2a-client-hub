"""Shared helpers for extension capability routers."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Dict, Literal, Optional, cast

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse

from app.api.error_codes import status_code_for_extension_error_code
from app.api.error_handlers import build_error_detail, build_error_response
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
    A2AExtensionUpstreamError,
)
from app.integrations.a2a_runtime_status_contract import runtime_status_contract_payload
from app.schemas.a2a_compatibility_profile import (
    A2ACompatibilityProfileDiagnostic,
)
from app.schemas.a2a_extension import (
    A2ADeclaredMethodCapabilityResponse,
    A2ADeclaredMethodCollectionCapabilitiesResponse,
    A2ADeclaredSingleMethodCapabilitiesResponse,
    A2AExtensionCapabilitiesResponse,
    A2AExtensionResponse,
    A2AInterruptRecoveryCapabilitiesResponse,
    A2AInvokeMetadataCapabilitiesResponse,
    A2AInvokeMetadataFieldResponse,
    A2ARequestExecutionOptionsCapabilitiesResponse,
    A2ARuntimeStatusContractResponse,
    A2ASessionAppendCapabilitiesResponse,
    A2ASessionControlCapabilitiesResponse,
    A2ASessionControlMethodResponse,
    A2AStreamHintsCapabilitiesResponse,
    A2AUpstreamMethodFamiliesResponse,
    A2AWireContractCapabilitiesResponse,
    A2AWireContractConditionalMethodResponse,
    A2AWireContractUnsupportedMethodErrorResponse,
)

_SESSION_CONTROL_HUB_CONSUMPTION = {
    "prompt_async": True,
    "command": True,
    "shell": False,
}


def parse_query_param(value: Optional[str]) -> Optional[Dict[str, Any]]:
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


def summarize_query_object(query: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not query:
        return {"keys": [], "size": 0}
    keys = sorted(str(key) for key in query.keys())[:20]
    return {"keys": keys, "size": len(query)}


def summarize_metadata_keys(metadata: Optional[Dict[str, Any]]) -> list[str]:
    if not metadata:
        return []
    return sorted(str(key) for key in metadata.keys())[:20]


def summarize_object_keys(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not value:
        return {"keys": [], "size": 0}
    return {
        "keys": sorted(str(key) for key in value.keys())[:20],
        "size": len(value),
    }


def build_session_list_filters(
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


def summarize_session_list_filters(
    filters: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not filters:
        return {"keys": [], "size": 0}
    return {
        "keys": sorted(str(key) for key in filters.keys())[:20],
        "size": len(filters),
    }


def is_session_control_method_supported(
    method: A2ASessionControlMethodResponse,
) -> bool:
    return (
        method.declared
        and method.consumed_by_hub
        and method.availability != "unsupported"
    )


def build_session_append_response(
    snapshot: Any,
    prompt_async: A2ASessionControlMethodResponse,
) -> A2ASessionAppendCapabilitiesResponse:
    codex_turns = getattr(snapshot, "codex_turns", None)
    turn_methods = dict(getattr(codex_turns, "methods", {}) or {})
    steer = turn_methods.get("steer")
    steer_declared = bool(getattr(steer, "declared", False))
    steer_consumed = bool(getattr(steer, "consumed_by_hub", False))
    raw_steer_availability = getattr(steer, "availability", None)
    steer_availability = cast(
        Literal["always", "enabled", "disabled", "unsupported"],
        (
            raw_steer_availability
            if raw_steer_availability is not None
            else ("always" if steer_declared else "unsupported")
        ),
    )
    turn_steer_supported = (
        steer_declared
        and steer_consumed
        and steer_availability not in {"disabled", "unsupported"}
    )
    prompt_async_supported = is_session_control_method_supported(prompt_async)

    if prompt_async_supported and turn_steer_supported:
        return A2ASessionAppendCapabilitiesResponse(
            declared=True,
            consumedByHub=True,
            status="supported",
            routeMode="hybrid",
            requiresStreamIdentity=False,
        )
    if prompt_async_supported:
        return A2ASessionAppendCapabilitiesResponse(
            declared=True,
            consumedByHub=True,
            status="supported",
            routeMode="prompt_async",
            requiresStreamIdentity=False,
        )
    if turn_steer_supported:
        return A2ASessionAppendCapabilitiesResponse(
            declared=True,
            consumedByHub=True,
            status="supported",
            routeMode="turn_steer",
            requiresStreamIdentity=True,
        )
    return A2ASessionAppendCapabilitiesResponse(
        declared=bool(prompt_async.declared or steer_declared),
        consumedByHub=bool(prompt_async.consumed_by_hub or steer_consumed),
        status="unsupported",
        routeMode="unsupported",
        requiresStreamIdentity=False,
    )


def build_session_control_response(
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

    prompt_async = _build_method("prompt_async")
    return A2ASessionControlCapabilitiesResponse(
        promptAsync=prompt_async,
        command=_build_method("command"),
        shell=_build_method("shell"),
        append=build_session_append_response(snapshot, prompt_async),
    )


def build_compatibility_profile_response(
    snapshot: Any,
) -> A2ACompatibilityProfileDiagnostic:
    compatibility_snapshot = getattr(snapshot, "compatibility_profile", None)
    status_value = cast(
        Literal["supported", "unsupported", "invalid"],
        getattr(compatibility_snapshot, "status", "unsupported"),
    )
    error = getattr(compatibility_snapshot, "error", None)
    ext = getattr(compatibility_snapshot, "ext", None)
    if ext is None:
        return A2ACompatibilityProfileDiagnostic(
            declared=status_value != "unsupported",
            status=status_value,
            error=error,
        )

    return A2ACompatibilityProfileDiagnostic(
        declared=True,
        status=status_value,
        uri=getattr(ext, "uri", None),
        extensionRetentionCount=len(
            dict(getattr(ext, "extension_retention", {}) or {})
        ),
        methodRetentionCount=len(dict(getattr(ext, "method_retention", {}) or {})),
        serviceBehaviorKeys=sorted(
            str(key) for key in dict(getattr(ext, "service_behaviors", {}) or {})
        ),
        consumerGuidance=list(getattr(ext, "consumer_guidance", ()) or ()),
        error=error,
    )


def build_invoke_metadata_response(
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


def build_request_execution_options_response(
    snapshot: Any,
) -> A2ARequestExecutionOptionsCapabilitiesResponse:
    capability = getattr(snapshot, "request_execution_options", None)
    return A2ARequestExecutionOptionsCapabilitiesResponse(
        declared=bool(getattr(capability, "declared", False)),
        consumedByHub=bool(getattr(capability, "consumed_by_hub", False)),
        status=cast(
            Literal["supported", "unsupported", "declared_not_consumed", "invalid"],
            getattr(capability, "status", "unsupported"),
        ),
        metadataField=getattr(capability, "metadata_field", None),
        fields=list(getattr(capability, "fields", ()) or ()),
        persistsForThread=getattr(capability, "persists_for_thread", None),
        sourceExtensions=list(getattr(capability, "source_extensions", ()) or ()),
        notes=list(getattr(capability, "notes", ()) or ()),
        error=getattr(capability, "error", None),
    )


def build_stream_hints_response(snapshot: Any) -> A2AStreamHintsCapabilitiesResponse:
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


def build_interrupt_recovery_details_response(
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


def build_wire_contract_response(snapshot: Any) -> A2AWireContractCapabilitiesResponse:
    wire_snapshot = getattr(snapshot, "wire_contract", None)
    ext = getattr(wire_snapshot, "ext", None)
    status_value = cast(
        Literal["supported", "unsupported", "invalid"],
        getattr(wire_snapshot, "status", "unsupported"),
    )
    error = getattr(wire_snapshot, "error", None)
    if ext is None:
        return A2AWireContractCapabilitiesResponse(
            declared=status_value != "unsupported",
            consumedByHub=True,
            status=status_value,
            error=error,
        )

    return A2AWireContractCapabilitiesResponse(
        declared=True,
        consumedByHub=True,
        status=status_value,
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


def build_declared_method_capability_response(
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


def build_declared_method_collection_response(
    capability: Any,
) -> A2ADeclaredMethodCollectionCapabilitiesResponse:
    methods = dict(getattr(capability, "methods", {}) or {})
    status_value = cast(
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
        status=status_value,
        methods={
            name: build_declared_method_capability_response(item)
            for name, item in methods.items()
        },
        declarationSource=getattr(capability, "declaration_source", None),
        declarationConfidence=getattr(capability, "declaration_confidence", None),
        negotiationState=getattr(capability, "negotiation_state", None),
        diagnosticNote=getattr(capability, "diagnostic_note", None),
    )


def build_declared_single_method_response(
    capability: Any,
) -> A2ADeclaredSingleMethodCapabilitiesResponse:
    status_value = cast(
        Literal["unsupported", "unsupported_by_design"],
        getattr(capability, "status", "unsupported"),
    )
    return A2ADeclaredSingleMethodCapabilitiesResponse(
        declared=bool(getattr(capability, "declared", False)),
        consumedByHub=bool(getattr(capability, "consumed_by_hub", False)),
        status=status_value,
        method=getattr(capability, "method", None),
    )


def build_upstream_method_families_response(
    snapshot: Any,
) -> A2AUpstreamMethodFamiliesResponse:
    families = getattr(snapshot, "upstream_method_families", None)
    if not isinstance(families, dict):
        families = {
            "discovery": getattr(snapshot, "codex_discovery", None),
            "threads": getattr(snapshot, "codex_threads", None),
            "turns": getattr(snapshot, "codex_turns", None),
            "review": getattr(snapshot, "codex_review", None),
            "exec": getattr(snapshot, "codex_exec", None),
        }
    return A2AUpstreamMethodFamiliesResponse(
        discovery=build_declared_method_collection_response(families.get("discovery")),
        threads=build_declared_method_collection_response(families.get("threads")),
        turns=build_declared_method_collection_response(families.get("turns")),
        review=build_declared_method_collection_response(families.get("review")),
        exec=build_declared_method_collection_response(families.get("exec")),
    )


def build_extension_capabilities_response(
    snapshot: Any,
) -> A2AExtensionCapabilitiesResponse:
    model_selection = snapshot.model_selection.status == "supported"
    provider_discovery = snapshot.provider_discovery.status == "supported"
    interrupt_recovery = snapshot.interrupt_recovery.status == "supported"
    session_control = build_session_control_response(snapshot)
    session_prompt_async = (
        session_control.prompt_async.declared
        and session_control.prompt_async.consumed_by_hub
    )

    return A2AExtensionCapabilitiesResponse(
        modelSelection=model_selection,
        providerDiscovery=provider_discovery,
        interruptRecovery=interrupt_recovery,
        interruptRecoveryDetails=build_interrupt_recovery_details_response(snapshot),
        sessionPromptAsync=session_prompt_async,
        sessionControl=session_control,
        invokeMetadata=build_invoke_metadata_response(snapshot),
        requestExecutionOptions=build_request_execution_options_response(snapshot),
        streamHints=build_stream_hints_response(snapshot),
        wireContract=build_wire_contract_response(snapshot),
        compatibilityProfile=build_compatibility_profile_response(snapshot),
        upstreamMethodFamilies=build_upstream_method_families_response(snapshot),
        runtimeStatus=A2ARuntimeStatusContractResponse.model_validate(
            runtime_status_contract_payload()
        ),
    )


def to_extension_response(result: Any) -> A2AExtensionResponse:
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


def to_extension_error_response(
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
                upstream_error if upstream_error is not None else {"message": message}
            ),
            meta=meta or {},
        ),
    )


async def run_extension_call(
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
        return to_extension_error_response(
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
    response = to_extension_response(result)
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
