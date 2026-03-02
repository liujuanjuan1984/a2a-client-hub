from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.db.locking import (
    DbLockFailureKind,
    RetryableDbLockError,
    RetryableDbQueryTimeoutError,
)
from app.db.models.ws_ticket import WsTicket
from app.services.ws_ticket_service import (
    WsTicketExpiredError,
    WsTicketUsedError,
    ws_ticket_service,
)
from app.utils.timezone_util import utc_now
from tests.utils import create_user


@pytest.mark.asyncio
async def test_consume_ticket_expired(async_db_session):
    user = await create_user(async_db_session)
    scope_id = uuid4()
    issued = await ws_ticket_service.issue_ticket(
        async_db_session, user_id=user.id, scope_type="test_scope", scope_id=scope_id
    )

    token_hash = ws_ticket_service._hash_token(issued.token)
    ticket = await async_db_session.scalar(
        select(WsTicket).where(WsTicket.token_hash == token_hash)
    )
    assert ticket is not None
    ticket.expires_at = utc_now() - timedelta(seconds=1)
    await async_db_session.commit()

    with pytest.raises(WsTicketExpiredError):
        await ws_ticket_service.consume_ticket(
            async_db_session,
            token=issued.token,
            scope_type="test_scope",
            scope_id=scope_id,
        )


@pytest.mark.asyncio
async def test_consume_ticket_used(async_db_session):
    user = await create_user(async_db_session)
    scope_id = uuid4()
    issued = await ws_ticket_service.issue_ticket(
        async_db_session, user_id=user.id, scope_type="test_scope", scope_id=scope_id
    )

    await ws_ticket_service.consume_ticket(
        async_db_session,
        token=issued.token,
        scope_type="test_scope",
        scope_id=scope_id,
    )

    with pytest.raises(WsTicketUsedError):
        await ws_ticket_service.consume_ticket(
            async_db_session,
            token=issued.token,
            scope_type="test_scope",
            scope_id=scope_id,
        )


@pytest.mark.asyncio
async def test_consume_ticket_returns_conflict_when_row_locked(
    async_db_session,
    monkeypatch,
):
    user = await create_user(async_db_session)
    scope_id = uuid4()
    issued = await ws_ticket_service.issue_ticket(
        async_db_session, user_id=user.id, scope_type="test_scope", scope_id=scope_id
    )

    class _LockNotAvailableError(Exception):
        sqlstate = "55P03"

    async def _raise_lock_not_available(*_args, **_kwargs):
        raise DBAPIError(
            statement="SELECT ... FOR UPDATE NOWAIT",
            params={},
            orig=_LockNotAvailableError(),
        )

    monkeypatch.setattr(async_db_session, "scalar", _raise_lock_not_available)

    with pytest.raises(RetryableDbLockError) as exc_info:
        await ws_ticket_service.consume_ticket(
            async_db_session,
            token=issued.token,
            scope_type="test_scope",
            scope_id=scope_id,
        )
    assert exc_info.value.kind == DbLockFailureKind.LOCK_NOT_AVAILABLE


@pytest.mark.asyncio
async def test_consume_ticket_raises_retryable_timeout_on_statement_timeout(
    async_db_session,
    monkeypatch,
):
    user = await create_user(async_db_session)
    scope_id = uuid4()
    issued = await ws_ticket_service.issue_ticket(
        async_db_session, user_id=user.id, scope_type="test_scope", scope_id=scope_id
    )

    class _StatementTimeoutError(Exception):
        sqlstate = "57014"

    async def _raise_statement_timeout(*_args, **_kwargs):
        raise DBAPIError(
            statement="SELECT ... FOR UPDATE NOWAIT",
            params={},
            orig=_StatementTimeoutError("canceling statement due to statement timeout"),
        )

    monkeypatch.setattr(async_db_session, "scalar", _raise_statement_timeout)

    with pytest.raises(RetryableDbQueryTimeoutError) as exc_info:
        await ws_ticket_service.consume_ticket(
            async_db_session,
            token=issued.token,
            scope_type="test_scope",
            scope_id=scope_id,
        )

    assert "service busy" in str(exc_info.value)
