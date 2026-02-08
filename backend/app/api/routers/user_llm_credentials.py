"""
REST endpoints for user-configured LLM credentials (BYOT).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.schemas.user_llm_credential import (
    UserLlmCredentialCreate,
    UserLlmCredentialListResponse,
    UserLlmCredentialResponse,
    UserLlmCredentialTestRequest,
    UserLlmCredentialTestResponse,
    UserLlmCredentialUpdate,
)
from app.services.user_llm_credentials import (
    UserLlmCredentialDisabledError,
    UserLlmCredentialNotFoundError,
    UserLlmCredentialValidationError,
    user_llm_credential_service,
)

logger = get_logger(__name__)
router = StrictAPIRouter(prefix="/me/llm-credentials", tags=["llm"])


def _ensure_feature_enabled() -> None:
    if not user_llm_credential_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User-provided LLM credentials are disabled",
        )


@router.get("", response_model=UserLlmCredentialListResponse)
async def list_credentials(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=200, description="Page size"),
) -> UserLlmCredentialListResponse:
    _ensure_feature_enabled()
    items = await user_llm_credential_service.list_credentials(
        db, user_id=current_user.id
    )
    total = len(items)
    pages = (total + size - 1) // size if size else 0
    offset = (page - 1) * size
    page_items = items[offset : offset + size]
    return UserLlmCredentialListResponse(
        items=page_items,
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={"provider": None},
    )


@router.post("", response_model=UserLlmCredentialResponse, status_code=201)
async def create_credential(
    *,
    payload: UserLlmCredentialCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    _ensure_feature_enabled()
    try:
        credential = await user_llm_credential_service.create_credential(
            db,
            user_id=current_user.id,
            provider=payload.provider,
            api_key=payload.api_key,
            display_name=payload.display_name,
            api_base=payload.api_base,
            model_override=payload.model_override,
            make_default=payload.make_default,
        )
        return credential
    except UserLlmCredentialValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{credential_id}", response_model=UserLlmCredentialResponse)
async def update_credential(
    *,
    credential_id: UUID,
    payload: UserLlmCredentialUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    _ensure_feature_enabled()
    try:
        credential = await user_llm_credential_service.update_credential(
            db,
            user_id=current_user.id,
            credential_id=credential_id,
            provider=payload.provider,
            api_key=payload.api_key,
            display_name=payload.display_name,
            api_base=payload.api_base,
            model_override=payload.model_override,
            make_default=payload.make_default,
        )
        return credential
    except UserLlmCredentialValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UserLlmCredentialNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{credential_id}/default",
    response_model=UserLlmCredentialResponse,
    status_code=200,
)
async def set_default_credential(
    *,
    credential_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    _ensure_feature_enabled()
    try:
        credential = await user_llm_credential_service.set_default(
            db,
            user_id=current_user.id,
            credential_id=credential_id,
        )
        return credential
    except UserLlmCredentialNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/test",
    response_model=UserLlmCredentialTestResponse,
    status_code=200,
)
async def test_credential(
    *,
    payload: UserLlmCredentialTestRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> UserLlmCredentialTestResponse:
    _ensure_feature_enabled()
    success, message = user_llm_credential_service.test_credential(
        provider=payload.provider,
        api_key=payload.api_key,
        api_base=payload.api_base,
        model_override=payload.model_override,
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return UserLlmCredentialTestResponse(success=True, message=message)


@router.delete(
    "/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_credential(
    *,
    credential_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    _ensure_feature_enabled()
    try:
        await user_llm_credential_service.delete_credential(
            db,
            user_id=current_user.id,
            credential_id=credential_id,
        )
    except UserLlmCredentialNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UserLlmCredentialDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
