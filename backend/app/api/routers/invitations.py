"""Invitation management API."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_admin_user, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.invitation import Invitation, InvitationStatus
from app.db.models.user import User
from app.handlers import invitations as invitation_handler
from app.schemas.invitations import (
    InvitationCreateRequest,
    InvitationListResponse,
    InvitationLookupResponse,
    InvitationResponse,
    InvitationWithCreatorListResponse,
    InvitationWithCreatorResponse,
)

router = StrictAPIRouter(prefix="/invitations", tags=["invitations"])


def _serialize_invitation_with_creator(
    invitation: Invitation,
) -> InvitationWithCreatorResponse:
    creator_email = invitation.creator.email if invitation.creator else None
    creator_name = invitation.creator.name if invitation.creator else None
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
        result = await invitation_handler.create_invitation(
            db,
            creator_user_id=current_admin.id,
            target_email=request.email,
            memo=request.memo,
        )
    except invitation_handler.InvitationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return InvitationResponse.model_validate(result.invitation)


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
    offset = (page - 1) * size
    invitations, total = await invitation_handler.list_created_invitations_with_total(
        db,
        creator_user_id=current_user.id,
        offset=offset,
        limit=size,
    )
    items = [
        InvitationResponse.model_validate(invitation) for invitation in invitations
    ]
    pages = (total + size - 1) // size if size else 0
    return InvitationListResponse(
        items=items,
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={
            "scope": "created",
            "creator_user_id": current_user.id,
        },
    )


@router.get("/invited-me", response_model=InvitationWithCreatorListResponse)
async def list_invitations_for_me(
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> InvitationWithCreatorListResponse:
    offset = (page - 1) * size
    (
        invitations,
        total,
    ) = await invitation_handler.list_invitations_targeting_user_with_total(
        db,
        user_email=current_user.email,
        offset=offset,
        limit=size,
    )
    items = [
        _serialize_invitation_with_creator(invitation) for invitation in invitations
    ]
    pages = (total + size - 1) // size if size else 0
    return InvitationWithCreatorListResponse(
        items=items,
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={
            "scope": "invited",
            "target_email": current_user.email,
        },
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
    if invitation.creator_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot revoke invitations created by other users",
        )
    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending invitations can be revoked",
        )
    if invitation.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation already revoked",
        )

    await invitation_handler.revoke_invitation(
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
    if invitation.creator_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot restore invitations created by other users",
        )
    try:
        await invitation_handler.restore_invitation(
            db,
            invitation=invitation,
            reason="Restored manually by creator",
        )
    except invitation_handler.InvitationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return InvitationResponse.model_validate(invitation)


@router.get("/lookup/{code}", response_model=InvitationLookupResponse)
async def lookup_invitation(
    code: str, db: AsyncSession = Depends(get_async_db)
) -> InvitationLookupResponse:
    try:
        invitation = await invitation_handler.get_invitation_by_code(db, code=code)
    except invitation_handler.InvitationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    if invitation.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    creator_email = invitation.creator.email if invitation.creator else None
    creator_name = invitation.creator.name if invitation.creator else None

    return InvitationLookupResponse(
        code=invitation.code,
        target_email=invitation.target_email,
        status=invitation.status.value,
        creator_email=creator_email,
        creator_name=creator_name,
        memo=invitation.memo,
    )
