"""Shared OpenCode extension routes.

The hub catalog and user-managed agents expose the same OpenCode extension
surface area but require different runtime builders and error semantics.
This module centralises the route implementations to avoid drift.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, Optional, Type
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.integrations.a2a_extensions import get_a2a_extensions_service
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
    A2AExtensionUpstreamError,
)
from app.schemas.a2a_extension import A2AExtensionQueryRequest, A2AExtensionResponse
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


def create_opencode_extension_router(
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

    @router.get(
        "/{agent_id}/extensions/opencode/sessions",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def opencode_list_sessions(
        *,
        agent_id: UUID,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
        page: int = Query(1, ge=1, description="Page number (1-indexed)"),
        size: Optional[int] = Query(
            None, ge=1, description="Page size (uses card default when omitted)"
        ),
        query: Optional[str] = Query(
            None, description="Optional JSON object encoded as a string"
        ),
    ) -> A2AExtensionResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime(db, current_user, agent_id)
        query_obj = _parse_query_param(query)
        logger.info(
            _scope_message("OpenCode sessions list requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "page": page,
                "size": size,
                "query_meta": _summarize_query_object(query_obj),
            },
        )

        try:
            result = await get_a2a_extensions_service().opencode_list_sessions(
                runtime=runtime,
                page=page,
                size=size,
                query=query_obj,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except A2AExtensionNotSupportedError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except A2AExtensionContractError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except A2AExtensionUpstreamError as exc:
            return A2AExtensionResponse(
                success=False,
                error_code=exc.error_code,
                upstream_error=exc.upstream_error,
                meta={},
            )

        return A2AExtensionResponse(
            success=result.success,
            result=result.result,
            error_code=result.error_code,
            upstream_error=result.upstream_error,
            meta=result.meta or {},
        )

    @router.post(
        "/{agent_id}/extensions/opencode/sessions/{session_id}:continue",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def opencode_continue_session(
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
            _scope_message("OpenCode session continue requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
            },
        )

        try:
            result = await get_a2a_extensions_service().opencode_continue_session(
                runtime=runtime,
                session_id=session_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except A2AExtensionNotSupportedError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except A2AExtensionContractError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except A2AExtensionUpstreamError as exc:
            return A2AExtensionResponse(
                success=False,
                error_code=exc.error_code,
                upstream_error=exc.upstream_error,
                meta={},
            )

        return A2AExtensionResponse(
            success=result.success,
            result=result.result,
            error_code=result.error_code,
            upstream_error=result.upstream_error,
            meta=result.meta or {},
        )

    @router.post(
        "/{agent_id}/extensions/opencode/sessions:query",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def opencode_list_sessions_post(
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
            _scope_message("OpenCode sessions list requested (POST)"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "page": payload.page,
                "size": payload.size,
                "query_meta": _summarize_query_object(payload.query),
            },
        )

        try:
            result = await get_a2a_extensions_service().opencode_list_sessions(
                runtime=runtime,
                page=payload.page,
                size=payload.size,
                query=payload.query,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except A2AExtensionNotSupportedError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except A2AExtensionContractError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except A2AExtensionUpstreamError as exc:
            return A2AExtensionResponse(
                success=False,
                error_code=exc.error_code,
                upstream_error=exc.upstream_error,
                meta={},
            )

        return A2AExtensionResponse(
            success=result.success,
            result=result.result,
            error_code=result.error_code,
            upstream_error=result.upstream_error,
            meta=result.meta or {},
        )

    @router.get(
        "/{agent_id}/extensions/opencode/sessions/{session_id}/messages",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def opencode_list_session_messages(
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
        query: Optional[str] = Query(
            None, description="Optional JSON object encoded as a string"
        ),
    ) -> A2AExtensionResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime(db, current_user, agent_id)
        query_obj = _parse_query_param(query)
        logger.info(
            _scope_message("OpenCode session messages requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "page": page,
                "size": size,
                "query_meta": _summarize_query_object(query_obj),
            },
        )

        try:
            result = await get_a2a_extensions_service().opencode_get_session_messages(
                runtime=runtime,
                session_id=session_id,
                page=page,
                size=size,
                query=query_obj,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except A2AExtensionNotSupportedError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except A2AExtensionContractError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except A2AExtensionUpstreamError as exc:
            return A2AExtensionResponse(
                success=False,
                error_code=exc.error_code,
                upstream_error=exc.upstream_error,
                meta={},
            )

        return A2AExtensionResponse(
            success=result.success,
            result=result.result,
            error_code=result.error_code,
            upstream_error=result.upstream_error,
            meta=result.meta or {},
        )

    @router.post(
        "/{agent_id}/extensions/opencode/sessions/{session_id}/messages:query",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def opencode_list_session_messages_post(
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
            _scope_message("OpenCode session messages requested (POST)"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "page": payload.page,
                "size": payload.size,
                "query_meta": _summarize_query_object(payload.query),
            },
        )

        try:
            result = await get_a2a_extensions_service().opencode_get_session_messages(
                runtime=runtime,
                session_id=session_id,
                page=payload.page,
                size=payload.size,
                query=payload.query,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except A2AExtensionNotSupportedError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except A2AExtensionContractError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except A2AExtensionUpstreamError as exc:
            return A2AExtensionResponse(
                success=False,
                error_code=exc.error_code,
                upstream_error=exc.upstream_error,
                meta={},
            )

        return A2AExtensionResponse(
            success=result.success,
            result=result.result,
            error_code=result.error_code,
            upstream_error=result.upstream_error,
            meta=result.meta or {},
        )

    return router


__all__ = ["create_opencode_extension_router"]
