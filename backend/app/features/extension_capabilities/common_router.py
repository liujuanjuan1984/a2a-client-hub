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
from app.integrations.a2a_extensions import get_a2a_extensions_service
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
    A2AExtensionUpstreamError,
)
from app.integrations.a2a_runtime_status_contract import (
    runtime_status_contract_payload,
)
from app.schemas.a2a_extension import (
    A2AExtensionCapabilitiesResponse,
    A2AExtensionInterruptRecoveryRequest,
    A2AExtensionPermissionReplyRequest,
    A2AExtensionPromptAsyncRequest,
    A2AExtensionQueryRequest,
    A2AExtensionQueryResponse,
    A2AExtensionQuestionRejectRequest,
    A2AExtensionQuestionReplyRequest,
    A2AExtensionResponse,
    A2AExtensionSessionCommandRequest,
    A2AInterruptRecoveryResponse,
    A2AModelDiscoveryRequest,
    A2ARuntimeStatusContractResponse,
    A2ASessionControlCapabilitiesResponse,
    A2ASessionControlMethodResponse,
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
        runtime = await _get_runtime(db, current_user, agent_id)
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
            sessionPromptAsync=session_prompt_async,
            sessionControl=session_control,
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
        runtime = await _get_runtime(db, current_user, agent_id)
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
        runtime = await _get_runtime(db, current_user, agent_id)
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
        query: Optional[str] = Query(
            None, description="Optional JSON object encoded as a string"
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime(db, current_user, agent_id)
        query_obj = _parse_query_param(query)
        logger.info(
            _scope_message("Shared extension sessions list requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "page": page,
                "size": size,
                "include_raw": include_raw,
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

        runtime = await _get_runtime(db, current_user, agent_id)
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

        runtime = await _get_runtime(db, current_user, agent_id)
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

        runtime = await _get_runtime(db, current_user, agent_id)
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

        runtime = await _get_runtime(db, current_user, agent_id)
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

        runtime = await _get_runtime(db, current_user, agent_id)
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

        runtime = await _get_runtime(db, current_user, agent_id)
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

        runtime = await _get_runtime(db, current_user, agent_id)
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
        "/{agent_id}/extensions/sessions:query",
        response_model=A2AExtensionQueryResponse,
        status_code=status.HTTP_200_OK,
        response_model_exclude_none=True,
    )
    async def query_external_sessions(
        *,
        agent_id: UUID,
        payload: A2AExtensionQueryRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension sessions list requested (POST)"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "page": payload.page,
                "size": payload.size,
                "include_raw": payload.include_raw,
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
        include_raw: bool = Query(
            False,
            description="Whether to include the upstream raw payload in the response",
        ),
        query: Optional[str] = Query(
            None, description="Optional JSON object encoded as a string"
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime(db, current_user, agent_id)
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
        payload: A2AExtensionQueryRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session messages requested (POST)"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "page": payload.page,
                "size": payload.size,
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
                include_raw=payload.include_raw,
                query=payload.query,
            )
        )

    return router


__all__ = ["create_extension_capability_router"]
