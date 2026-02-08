"""A2A extension endpoints for OpenCode session query."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
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
from app.services.a2a_runtime import (
    A2ARuntimeNotFoundError,
    A2ARuntimeValidationError,
    a2a_runtime_builder,
)

router = StrictAPIRouter(prefix="/me/a2a/agents", tags=["a2a-extensions"])
logger = get_logger(__name__)


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

    try:
        runtime = await a2a_runtime_builder.build(
            db, user_id=current_user.id, agent_id=agent_id
        )
    except A2ARuntimeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except A2ARuntimeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    query_obj = _parse_query_param(query)
    logger.info(
        "OpenCode sessions list requested",
        extra={
            "user_id": str(current_user.id),
            "agent_id": str(agent_id),
            "agent_url": runtime.resolved.url,
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
    try:
        runtime = await a2a_runtime_builder.build(
            db, user_id=current_user.id, agent_id=agent_id
        )
    except A2ARuntimeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except A2ARuntimeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "OpenCode sessions list requested (POST)",
        extra={
            "user_id": str(current_user.id),
            "agent_id": str(agent_id),
            "agent_url": runtime.resolved.url,
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

    try:
        runtime = await a2a_runtime_builder.build(
            db, user_id=current_user.id, agent_id=agent_id
        )
    except A2ARuntimeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except A2ARuntimeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    query_obj = _parse_query_param(query)
    logger.info(
        "OpenCode session messages list requested",
        extra={
            "user_id": str(current_user.id),
            "agent_id": str(agent_id),
            "agent_url": runtime.resolved.url,
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
    try:
        runtime = await a2a_runtime_builder.build(
            db, user_id=current_user.id, agent_id=agent_id
        )
    except A2ARuntimeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except A2ARuntimeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "OpenCode session messages list requested (POST)",
        extra={
            "user_id": str(current_user.id),
            "agent_id": str(agent_id),
            "agent_url": runtime.resolved.url,
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


__all__ = ["router"]
