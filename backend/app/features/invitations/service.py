"""Invitation feature service encapsulating invitation lifecycle operations."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional, cast
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.invitation import Invitation, InvitationStatus
from app.db.models.user import User
from app.db.transaction import commit_safely, rollback_safely

logger = logging.getLogger(__name__)


class InvitationError(Exception):
    """Base class for invitation related errors."""


class InvitationConflictError(InvitationError):
    """Raised when an invitation already exists for the same creator and email."""


class InvitationNotFoundError(InvitationError):
    """Raised when an invitation cannot be located."""


class InvitationUsageError(InvitationError):
    """Raised when an invitation cannot be used for registration."""


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _build_invitation_query(
    *,
    creator_user_id: Optional[UUID] = None,
    target_email: Optional[str] = None,
) -> Any:
    stmt = select(Invitation)
    if creator_user_id is not None:
        stmt = stmt.where(Invitation.creator_user_id == creator_user_id)
    if target_email is not None:
        stmt = stmt.where(Invitation.target_email == _normalize_email(target_email))
    return stmt


def _generate_code(candidate_length: int) -> str:
    token = secrets.token_urlsafe(candidate_length)
    return token[:candidate_length]


async def _ensure_unique_code(db: AsyncSession, *, max_attempts: int = 5) -> str:
    length = settings.invitation_code_length
    for _ in range(max_attempts):
        code = _generate_code(length)
        exists = (
            await db.execute(select(Invitation.id).where(Invitation.code == code))
        ).scalar_one_or_none()
        if exists is None:
            return code
    raise InvitationError("Failed to generate unique invitation code")


@dataclass(slots=True)
class InvitationCreateResult:
    id: UUID
    code: str
    creator_user_id: UUID
    target_email: str
    status: InvitationStatus
    memo: str | None
    created_at: object
    updated_at: object
    deleted_at: object | None

    @classmethod
    def from_invitation(cls, invitation: Invitation) -> InvitationCreateResult:
        return cls(
            id=cast(UUID, invitation.id),
            code=cast(str, invitation.code),
            creator_user_id=cast(UUID, invitation.creator_user_id),
            target_email=cast(str, invitation.target_email),
            status=cast(InvitationStatus, invitation.status),
            memo=cast(str | None, invitation.memo),
            created_at=cast(object, invitation.created_at),
            updated_at=cast(object, invitation.updated_at),
            deleted_at=cast(object | None, invitation.deleted_at),
        )


async def create_invitation(
    db: AsyncSession,
    *,
    creator_user_id: UUID,
    target_email: str,
    memo: Optional[str] = None,
) -> InvitationCreateResult:
    """Create a new invitation for the provided email."""

    normalized_email = _normalize_email(target_email)

    # Check for existing revoked invitation to restore
    existing_revoked = (
        await db.execute(
            select(Invitation).where(
                and_(
                    Invitation.creator_user_id == creator_user_id,
                    Invitation.target_email == normalized_email,
                    Invitation.status == InvitationStatus.REVOKED,
                )
            )
        )
    ).scalar_one_or_none()

    if existing_revoked:
        # Auto-restore revoked invitation
        await restore_invitation(
            db,
            invitation=existing_revoked,
            reason="Auto-restored during new invitation creation",
        )

        # Update memo if new one provided
        if memo:
            existing_memo = cast(str | None, existing_revoked.memo)
            setattr(
                existing_revoked,
                "memo",
                f"{existing_memo}\nNew memo: {memo}" if existing_memo else memo,
            )

        logger.info(
            "Revoked invitation auto-restored instead of creating new",
            extra={
                "creator_user_id": str(creator_user_id),
                "target_email": normalized_email,
                "invitation_id": str(existing_revoked.id),
            },
        )

        return InvitationCreateResult.from_invitation(existing_revoked)

    # If no revoked invitation exists, execute original uniqueness check
    await ensure_invitation_unique_for_creator(
        db,
        creator_user_id=creator_user_id,
        target_email=normalized_email,
    )

    # Disallow inviting existing active users
    existing_user = (
        await db.execute(
            select(User.id).where(
                and_(
                    func.lower(User.email) == normalized_email,
                    User.disabled_at.is_(None),
                )
            )
        )
    ).scalar_one_or_none()
    if existing_user is not None:
        raise InvitationConflictError("Email already registered")

    code = await _ensure_unique_code(db)

    invitation = Invitation(
        code=code,
        creator_user_id=creator_user_id,
        target_email=normalized_email,
        memo=memo,
    )

    db.add(invitation)
    try:
        await commit_safely(db)
    except IntegrityError as exc:
        await rollback_safely(db)
        raise InvitationConflictError(
            "Invitation already exists for this email"
        ) from exc

    logger.info(
        "Invitation created",
        extra={
            "creator_user_id": str(creator_user_id),
            "target_email": normalized_email,
            "invitation_id": str(invitation.id),
        },
    )

    return InvitationCreateResult.from_invitation(invitation)


async def get_invitation_by_code(db: AsyncSession, *, code: str) -> Invitation:
    invitation = (
        await db.execute(select(Invitation).where(Invitation.code == code))
    ).scalar_one_or_none()
    if invitation is None:
        raise InvitationNotFoundError("Invitation not found")
    return invitation


async def validate_invitation_for_registration(
    db: AsyncSession,
    *,
    code: str,
    email: str,
) -> Invitation:
    normalized_email = _normalize_email(email)

    invitation = (
        await db.execute(select(Invitation).where(Invitation.code == code))
    ).scalar_one_or_none()
    if invitation is None:
        raise InvitationUsageError("Invitation is invalid or revoked")

    deleted_at = cast(datetime | None, invitation.deleted_at)
    if deleted_at is not None:
        raise InvitationUsageError("Invitation is invalid or revoked")

    if invitation.status != InvitationStatus.PENDING:
        raise InvitationUsageError("Invitation is no longer available")

    if invitation.target_email != normalized_email:
        raise InvitationUsageError("Invitation does not match the provided email")

    expires_at = cast(datetime | None, invitation.expires_at)
    if expires_at is not None:
        now = await db.scalar(select(func.now()))
        if now is not None and now >= expires_at:
            invitation.mark_expired()
            await commit_safely(db)
            raise InvitationUsageError("Invitation has expired")

    return invitation


async def mark_invitation_registered(
    db: AsyncSession,
    *,
    invitation: Invitation,
    user_id: UUID,
    memo: Optional[str] = None,
) -> None:
    invitation.mark_registered(user_id, reason=memo)
    await commit_safely(db)

    logger.info(
        "Invitation marked as registered",
        extra={
            "invitation_id": str(invitation.id),
            "target_user_id": str(user_id),
        },
    )


async def revoke_invitation(
    db: AsyncSession,
    *,
    invitation: Invitation,
    reason: Optional[str] = None,
) -> None:
    invitation.mark_revoked(reason=reason)
    await commit_safely(db)

    logger.info(
        "Invitation revoked",
        extra={
            "invitation_id": str(invitation.id),
            "creator_user_id": str(invitation.creator_user_id),
            "reason": reason,
        },
    )


async def restore_invitation(
    db: AsyncSession,
    *,
    invitation: Invitation,
    reason: Optional[str] = None,
) -> None:
    """Restore a revoked invitation back to pending status."""
    if invitation.status != InvitationStatus.REVOKED:
        raise InvitationError("Only revoked invitations can be restored")

    # Restore status and clear revocation markers
    setattr(invitation, "status", InvitationStatus.PENDING)
    setattr(invitation, "deleted_at", None)
    setattr(invitation, "revoked_at", None)
    if reason:
        existing_memo = cast(str | None, invitation.memo)
        setattr(
            invitation,
            "memo",
            (
                f"{existing_memo}\nRestored: {reason}"
                if existing_memo
                else f"Restored: {reason}"
            ),
        )

    await commit_safely(db)

    # Ensure server-generated columns (e.g. updated_at) are loaded before
    # returning the ORM instance to API layers that may serialize it.
    await db.refresh(invitation)

    logger.info(
        "Invitation restored",
        extra={
            "invitation_id": str(invitation.id),
            "creator_user_id": str(invitation.creator_user_id),
            "target_email": invitation.target_email,
            "reason": reason,
        },
    )


async def revoke_other_invitations_for_email(
    db: AsyncSession,
    *,
    email: str,
    exclude_invitation_id: UUID,
    memo: str,
) -> List[Invitation]:
    normalized_email = _normalize_email(email)

    stmt = select(Invitation).where(
        and_(
            Invitation.target_email == normalized_email,
            Invitation.id != exclude_invitation_id,
            Invitation.status == InvitationStatus.PENDING,
            Invitation.deleted_at.is_(None),
        )
    )
    invitations = list((await db.execute(stmt)).scalars())

    if not invitations:
        return []

    for invite in invitations:
        invite.mark_revoked(reason=memo)

    await commit_safely(db)

    logger.info(
        "Revoked %d additional invitations for email",
        len(invitations),
        extra={
            "email": normalized_email,
            "exclude_invitation_id": str(exclude_invitation_id),
        },
    )

    return invitations


async def list_created_invitations_with_total(
    db: AsyncSession,
    *,
    creator_user_id: UUID,
    offset: int = 0,
    limit: int = 100,
) -> tuple[List[Invitation], int]:
    stmt = _build_invitation_query(creator_user_id=creator_user_id)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    stmt = stmt.order_by(Invitation.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    total = await db.scalar(count_stmt)
    return list(result.scalars()), int(total or 0)


async def list_invitations_targeting_user_with_total(
    db: AsyncSession,
    *,
    user_email: str,
    offset: int = 0,
    limit: int = 100,
) -> tuple[List[Invitation], int]:
    stmt = _build_invitation_query(target_email=user_email)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    stmt = stmt.order_by(Invitation.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    total = await db.scalar(count_stmt)
    return list(result.scalars()), int(total or 0)


async def ensure_invitation_unique_for_creator(
    db: AsyncSession,
    *,
    creator_user_id: UUID,
    target_email: str,
) -> None:
    normalized_email = _normalize_email(target_email)

    # Only check for active invitations (pending, registered), ignore revoked ones
    existing = (
        await db.execute(
            select(Invitation.id).where(
                and_(
                    Invitation.creator_user_id == creator_user_id,
                    Invitation.target_email == normalized_email,
                    Invitation.deleted_at.is_(None),
                    Invitation.status.in_(
                        [InvitationStatus.PENDING, InvitationStatus.REGISTERED]
                    ),
                )
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise InvitationConflictError("Invitation already exists for this email")
