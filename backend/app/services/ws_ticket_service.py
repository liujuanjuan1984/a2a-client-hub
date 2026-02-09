"""Service helpers for issuing and consuming short-lived WS tickets."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
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

    def __init__(self) -> None:
        self._secret_key = settings.ws_ticket_secret_key or settings.jwt_secret_key

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
            select(WsTicket).where(WsTicket.token_hash == token_hash).with_for_update()
        )
        ticket = await db.scalar(stmt)
        if ticket is None:
            raise WsTicketNotFoundError("Invalid or expired ticket")
        if ticket.used_at is not None:
            raise WsTicketUsedError("Ticket has already been used")
        if ticket.expires_at <= now:
            raise WsTicketExpiredError("Ticket has expired")
        if ticket.scope_id != scope_id:
            raise WsTicketScopeError("Ticket scope mismatch")
        expected_type = (scope_type or "").strip() or None
        if ticket.scope_type is not None and ticket.scope_type != expected_type:
            raise WsTicketScopeError("Ticket scope mismatch")

        ticket.used_at = now
        await commit_safely(db)
        return ticket


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
]
