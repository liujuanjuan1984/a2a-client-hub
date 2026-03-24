"""Invitation feature API."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_admin_user, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.invitation import Invitation, InvitationStatus
from app.db.models.user import User
from app.features.invitations import service as invitation_service
from app.features.invitations.schemas import (
    InvitationCreateRequest,
    InvitationListMeta,
    InvitationListResponse,
    InvitationLookupResponse,
    InvitationResponse,
    InvitationStatusEnum,
    InvitationWithCreatorListResponse,
    InvitationWithCreatorResponse,
)
from app.utils.pagination import build_pagination_meta, compute_offset

router = StrictAPIRouter(prefix="/invitations", tags=["invitations"])


def _serialize_invitation_result(
    result: invitation_service.InvitationCreateResult,
) -> InvitationResponse:
    return InvitationResponse(
        id=result.id,
        code=result.code,
        creator_user_id=result.creator_user_id,
        target_email=result.target_email,
        status=InvitationStatusEnum(result.status.value),
        target_user_id=None,
        memo=result.memo,
        created_at=cast(datetime, result.created_at),
        updated_at=cast(datetime, result.updated_at),
        deleted_at=cast(datetime | None, result.deleted_at),
        registered_at=None,
        revoked_at=None,
    )


def _serialize_invitation_with_creator(
    invitation: Invitation,
) -> InvitationWithCreatorResponse:
    creator_email = (
        cast(str, invitation.creator.email) if invitation.creator is not None else None
    )
    creator_name = (
        cast(str, invitation.creator.name) if invitation.creator is not None else None
    )
    base = InvitationWithCreatorResponse.model_validate(invitation)
    return base.model_copy(
        update={
            "creator_email": creator_email,
            "creator_name": creator_name,
        }
    )


@router.post(
    "/",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    request: InvitationCreateRequest,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_async_db),
) -> InvitationResponse:
    try:
        current_admin_id = cast(UUID, current_admin.id)
        result = await invitation_service.create_invitation(
            db,
            creator_user_id=current_admin_id,
            target_email=request.email,
            memo=request.memo,
        )
    except invitation_service.InvitationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return _serialize_invitation_result(result)


router.add_api_route(
    "",
    create_invitation,
    methods=["POST"],
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)


@router.get("/mine", response_model=InvitationListResponse)
async def list_my_invitations(
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> InvitationListResponse:
    offset = compute_offset(page=page, size=size)
    current_user_id = cast(UUID, current_user.id)
    invitations, total = await invitation_service.list_created_invitations_with_total(
        db,
        creator_user_id=current_user_id,
        offset=offset,
        limit=size,
    )
    items = [
        InvitationResponse.model_validate(invitation) for invitation in invitations
    ]
    return InvitationListResponse(
        items=items,
        pagination=build_pagination_meta(total=total, page=page, size=size),
        meta=InvitationListMeta(
            scope="created",
            creator_user_id=current_user_id,
            target_email=None,
        ),
    )


@router.get("/invited-me", response_model=InvitationWithCreatorListResponse)
async def list_invitations_for_me(
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> InvitationWithCreatorListResponse:
    offset = compute_offset(page=page, size=size)
    current_user_email = cast(str, current_user.email)
    (
        invitations,
        total,
    ) = await invitation_service.list_invitations_targeting_user_with_total(
        db,
        user_email=current_user_email,
        offset=offset,
        limit=size,
    )
    items = [
        _serialize_invitation_with_creator(invitation) for invitation in invitations
    ]
    return InvitationWithCreatorListResponse(
        items=items,
        pagination=build_pagination_meta(total=total, page=page, size=size),
        meta=InvitationListMeta(
            scope="invited",
            creator_user_id=None,
            target_email=current_user_email,
        ),
    )


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> None:
    invitation = await db.get(Invitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    creator_user_id = cast(UUID, invitation.creator_user_id)
    current_user_id = cast(UUID, current_user.id)
    if creator_user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot revoke invitations created by other users",
        )
    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending invitations can be revoked",
        )
    deleted_at = cast(datetime | None, invitation.deleted_at)
    if deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation already revoked",
        )

    await invitation_service.revoke_invitation(
        db,
        invitation=invitation,
        reason="Revoked manually by creator",
    )


@router.post("/{invitation_id}/restore", response_model=InvitationResponse)
async def restore_invitation(
    invitation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> InvitationResponse:
    invitation = await db.get(Invitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    creator_user_id = cast(UUID, invitation.creator_user_id)
    current_user_id = cast(UUID, current_user.id)
    if creator_user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot restore invitations created by other users",
        )
    try:
        await invitation_service.restore_invitation(
            db,
            invitation=invitation,
            reason="Restored manually by creator",
        )
    except invitation_service.InvitationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return InvitationResponse.model_validate(invitation)


@router.get("/lookup/{code}", response_model=InvitationLookupResponse)
async def lookup_invitation(
    code: str, db: AsyncSession = Depends(get_async_db)
) -> InvitationLookupResponse:
    try:
        invitation = await invitation_service.get_invitation_by_code(db, code=code)
    except invitation_service.InvitationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    deleted_at = cast(datetime | None, invitation.deleted_at)
    if deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    creator_email = (
        cast(str, invitation.creator.email) if invitation.creator is not None else None
    )
    creator_name = (
        cast(str, invitation.creator.name) if invitation.creator is not None else None
    )

    return InvitationLookupResponse(
        code=cast(str, invitation.code),
        target_email=cast(str, invitation.target_email),
        status=invitation.status.value,
        creator_email=creator_email,
        creator_name=creator_name,
        memo=cast(str | None, invitation.memo),
    )
