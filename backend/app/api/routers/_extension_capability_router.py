"""Shared capability routes for session query and interrupt callbacks.

The hub catalog and user-managed agents expose the same shared extension
surface area but require different runtime builders and error semantics.
This module centralises the route implementations to avoid drift.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, Optional, Type
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.error_codes import status_code_for_extension_error_code
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.integrations.a2a_extensions import get_a2a_extensions_service
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
    A2AExtensionUpstreamError,
)
from app.schemas.a2a_extension import (
    A2AExtensionCapabilitiesResponse,
    A2AExtensionPermissionReplyRequest,
    A2AExtensionPromptAsyncRequest,
    A2AExtensionQueryRequest,
    A2AExtensionQueryResponse,
    A2AExtensionQuestionRejectRequest,
    A2AExtensionQuestionReplyRequest,
    A2AExtensionResponse,
    A2AModelDiscoveryRequest,
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
        try:
            return await build_runtime(db, user_id=current_user.id, agent_id=agent_id)
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
            upstream_error=result.upstream_error,
            meta=result.meta or {},
        )

    def _to_extension_error_response(
        *,
        error_code: str,
        message: str,
        upstream_error: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> JSONResponse:
        payload = A2AExtensionResponse(
            success=False,
            result=None,
            error_code=error_code,
            upstream_error=(
                upstream_error if upstream_error is not None else {"message": message}
            ),
            meta=meta or {},
        )
        status_code = status_code_for_extension_error_code(error_code)
        return JSONResponse(
            status_code=status_code,
            content=payload.model_dump(),
        )

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

        from app.integrations.a2a_extensions.opencode_provider_discovery import (
            resolve_opencode_provider_discovery,
        )

        try:
            resolve_opencode_provider_discovery(runtime.resolved)
            model_selection = True
        except A2AExtensionNotSupportedError:
            model_selection = False

        return A2AExtensionCapabilitiesResponse(model_selection=model_selection)

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
            get_a2a_extensions_service().list_model_providers(
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
            get_a2a_extensions_service().list_models(
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
                upstream_error=exc.upstream_error,
                meta={},
            )
            status_code = status_code_for_extension_error_code(response.error_code)
            if status_code == status.HTTP_200_OK:
                return response
            return JSONResponse(
                status_code=status_code,
                content=response.model_dump(),
            )
        response = _to_extension_response(result)
        status_code = status_code_for_extension_error_code(response.error_code)
        if response.success or status_code == status.HTTP_200_OK:
            return response
        return JSONResponse(
            status_code=status_code,
            content=response.model_dump(),
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
    ) -> A2AExtensionResponse:
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
            get_a2a_extensions_service().list_sessions(
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
    ) -> A2AExtensionResponse:
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
            get_a2a_extensions_service().continue_session(
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
    ) -> A2AExtensionResponse:
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
            get_a2a_extensions_service().prompt_session_async(
                runtime=runtime,
                session_id=session_id,
                request_payload=payload.request,
                metadata=payload.metadata,
            )
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
    ) -> A2AExtensionResponse:
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
            get_a2a_extensions_service().reply_permission_interrupt(
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
    ) -> A2AExtensionResponse:
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
            get_a2a_extensions_service().reply_question_interrupt(
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
    ) -> A2AExtensionResponse:
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
            get_a2a_extensions_service().reject_question_interrupt(
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
    ) -> A2AExtensionResponse:
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
            get_a2a_extensions_service().list_sessions(
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
    ) -> A2AExtensionResponse:
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
            get_a2a_extensions_service().get_session_messages(
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
    ) -> A2AExtensionResponse:
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
            get_a2a_extensions_service().get_session_messages(
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
