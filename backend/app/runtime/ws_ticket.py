"""Service helpers for issuing and consuming short-lived WS tickets."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.locking import (
    set_postgres_local_timeouts,
    to_retryable_db_lock_error,
    to_retryable_db_query_timeout_error,
)
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


@dataclass(frozen=True)
class WsTicketIssueResult:
    token: str
    expires_at: datetime
    expires_in: int


class WsTicketService:
    """Issue and consume short-lived, one-time WS tickets."""

    _default_write_lock_timeout_ms = 500
    _default_write_statement_timeout_ms = 5000

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

    async def _apply_default_write_timeouts(self, db: AsyncSession) -> None:
        await set_postgres_local_timeouts(
            db,
            lock_timeout_ms=self._default_write_lock_timeout_ms,
            statement_timeout_ms=self._default_write_statement_timeout_ms,
        )

    async def _apply_nowait_write_timeouts(self, db: AsyncSession) -> None:
        """Apply only statement timeout for NOWAIT row-lock workflows."""

        await set_postgres_local_timeouts(
            db,
            statement_timeout_ms=self._default_write_statement_timeout_ms,
        )

    async def issue_ticket(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        scope_type: str,
        scope_id: UUID,
    ) -> WsTicketIssueResult:
        await self._apply_default_write_timeouts(db)
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
        try:
            await commit_safely(db)
        except DBAPIError as exc:
            retryable_lock_error = to_retryable_db_lock_error(
                exc,
                lock_message=(
                    "WS ticket issuance is currently locked by another operation; retry shortly."
                ),
            )
            if retryable_lock_error is not None:
                raise retryable_lock_error from exc
            retryable_timeout_error = to_retryable_db_query_timeout_error(
                exc,
                timeout_message="WS ticket issuance timed out; service busy, retry shortly.",
            )
            if retryable_timeout_error is not None:
                raise retryable_timeout_error from exc
            raise

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
        await self._apply_nowait_write_timeouts(db)
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
            retryable_lock_error = to_retryable_db_lock_error(
                exc,
                lock_message="Ticket is being consumed by another request",
            )
            if retryable_lock_error is not None:
                raise retryable_lock_error from exc
            retryable_timeout_error = to_retryable_db_query_timeout_error(
                exc,
                timeout_message="Ticket verification timed out; service busy, retry shortly.",
            )
            if retryable_timeout_error is not None:
                raise retryable_timeout_error from exc
            raise
        if ticket is None:
            raise WsTicketNotFoundError("Invalid or expired ticket")
        used_at = cast(datetime | None, ticket.used_at)
        if used_at is not None:
            raise WsTicketUsedError("Ticket has already been used")
        expires_at = cast(datetime, ticket.expires_at)
        if expires_at <= now:
            raise WsTicketExpiredError("Ticket has expired")

        # Strict scope matching (including type)
        expected_type = (scope_type or "").strip() or None
        if ticket.scope_id != scope_id or ticket.scope_type != expected_type:
            raise WsTicketScopeError("Ticket scope mismatch")

        setattr(ticket, "used_at", now)
        try:
            await commit_safely(db)
        except DBAPIError as exc:
            retryable_lock_error = to_retryable_db_lock_error(
                exc,
                lock_message=(
                    "Ticket is being consumed by another request; retry shortly."
                ),
            )
            if retryable_lock_error is not None:
                raise retryable_lock_error from exc
            retryable_timeout_error = to_retryable_db_query_timeout_error(
                exc,
                timeout_message="Ticket consume timed out; service busy, retry shortly.",
            )
            if retryable_timeout_error is not None:
                raise retryable_timeout_error from exc
            raise
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

        await self._apply_default_write_timeouts(db)
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
        result = cast(CursorResult[Any], await db.execute(stmt))
        await commit_safely(db)
        return result.rowcount or 0


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
    from app.runtime.scheduler import get_scheduler

    scheduler = get_scheduler()
    job_id = "ws-ticket-cleanup-daily"
    if scheduler.get_job(job_id):
        return

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
