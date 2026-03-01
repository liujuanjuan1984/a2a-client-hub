"""Service helpers for issuing and consuming short-lived WS tickets."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.locking import is_postgres_lock_not_available_error
from app.db.models.ws_ticket import WsTicket
from app.db.transaction import commit_safely
from app.utils.timezone_util import utc_now


class WsTicketError(RuntimeError):
    """Base error for WS ticket operations."""


class WsTicketNotFoundError(WsTicketError):
    """Raised when a WS ticket cannot be located."""


class WsTicketExpiredError(WsTicketError):
    """Raised when a WS ticket has expired."""


class WsTicketUsedError(WsTicketError):
    """Raised when a WS ticket has already been consumed."""


class WsTicketScopeError(WsTicketError):
    """Raised when a WS ticket does not match the expected scope."""


class WsTicketConflictError(WsTicketError):
    """Raised when a WS ticket row is locked by another transaction."""


@dataclass(frozen=True)
class WsTicketIssueResult:
    token: str
    expires_at: datetime
    expires_in: int


class WsTicketService:
    """Issue and consume short-lived, one-time WS tickets."""

    def __init__(self) -> None:
        self._secret_key = settings.ws_ticket_secret_key

    def _hash_token(self, token: str) -> str:
        if not self._secret_key:
            raise WsTicketError("WS ticket secret key is missing")
        return hmac.new(
            self._secret_key.encode("utf-8"),
            token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _generate_token(self) -> str:
        candidate_length = settings.ws_ticket_length
        token = secrets.token_urlsafe(candidate_length)
        return token[:candidate_length]

    async def issue_ticket(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        scope_type: str,
        scope_id: UUID,
    ) -> WsTicketIssueResult:
        now = utc_now()
        expires_in = settings.ws_ticket_ttl_seconds
        expires_at = now + timedelta(seconds=expires_in)

        token = self._generate_token()
        token_hash = self._hash_token(token)

        ticket = WsTicket(
            user_id=user_id,
            scope_type=(scope_type or "").strip() or None,
            scope_id=scope_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db.add(ticket)
        await commit_safely(db)

        return WsTicketIssueResult(
            token=token,
            expires_at=expires_at,
            expires_in=expires_in,
        )

    async def consume_ticket(
        self,
        db: AsyncSession,
        *,
        token: str,
        scope_type: str,
        scope_id: UUID,
    ) -> WsTicket:
        token_hash = self._hash_token(token)
        now = utc_now()

        stmt = (
            select(WsTicket)
            .where(WsTicket.token_hash == token_hash)
            .with_for_update(nowait=True)
        )
        try:
            ticket = await db.scalar(stmt)
        except DBAPIError as exc:
            if is_postgres_lock_not_available_error(exc):
                raise WsTicketConflictError(
                    "Ticket is being consumed by another request"
                ) from exc
            raise
        if ticket is None:
            raise WsTicketNotFoundError("Invalid or expired ticket")
        if ticket.used_at is not None:
            raise WsTicketUsedError("Ticket has already been used")
        if ticket.expires_at <= now:
            raise WsTicketExpiredError("Ticket has expired")

        # Strict scope matching (including type)
        expected_type = (scope_type or "").strip() or None
        if ticket.scope_id != scope_id or ticket.scope_type != expected_type:
            raise WsTicketScopeError("Ticket scope mismatch")

        ticket.used_at = now
        await commit_safely(db)
        return ticket

    async def cleanup_tickets(self, db: AsyncSession) -> int:
        """
        Delete expired or old used tickets to prevent table growth.

        Conditions for deletion:
        1. Expired tickets (regardless of used_at status)
        2. Used tickets older than the retention window
        3. Tickets with NULL scope_type (legacy/invalid)
        """
        from sqlalchemy import delete, or_

        now = utc_now()
        retention_days = max(settings.ws_ticket_retention_days, 0)
        retention_cutoff = now - timedelta(days=retention_days)

        stmt = delete(WsTicket).where(
            or_(
                WsTicket.expires_at < now,
                WsTicket.used_at < retention_cutoff,
                WsTicket.scope_type.is_(None),
            )
        )
        result = await db.execute(stmt)
        await commit_safely(db)
        return result.rowcount


async def cleanup_ws_tickets_job() -> None:
    """Scheduled job to clean up WS tickets."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        deleted = await ws_ticket_service.cleanup_tickets(db)

    if deleted > 0:
        from app.core.logging import get_logger

        logger = get_logger(__name__)
        logger.info("Cleaned up %d WS ticket(s).", deleted)


def ensure_ws_ticket_cleanup_job() -> None:
    """Register the WS ticket cleanup job with the shared scheduler."""
    from app.services.scheduler import get_scheduler

    scheduler = get_scheduler()
    job_id = "ws-ticket-cleanup-daily"
    if scheduler.get_job(job_id):
        return

    # Run daily at 3:00 AM
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(
        cleanup_ws_tickets_job,
        trigger=CronTrigger(hour=3, minute=0),
        id=job_id,
        replace_existing=True,
        coalesce=True,
    )
    from app.core.logging import get_logger

    logger = get_logger(__name__)
    logger.info("Registered daily WS ticket cleanup job.")


ws_ticket_service = WsTicketService()

__all__ = [
    "WsTicketError",
    "WsTicketConflictError",
    "WsTicketExpiredError",
    "WsTicketIssueResult",
    "WsTicketNotFoundError",
    "WsTicketScopeError",
    "WsTicketService",
    "WsTicketUsedError",
    "ws_ticket_service",
    "cleanup_ws_tickets_job",
    "ensure_ws_ticket_cleanup_job",
]
