from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models.ws_ticket import WsTicket
from app.services.ws_ticket_service import (
    WsTicketScopeError,
    ws_ticket_service,
)
from app.utils.timezone_util import utc_now

@pytest.mark.asyncio
async def test_consume_ticket_strict_scope_type(async_db_session):
    """Verify that consume_ticket strictly matches scope_type."""
    user_id = uuid4()
    scope_id = uuid4()
    
    # 1. Issue a ticket with a specific scope_type
    issue_result = await ws_ticket_service.issue_ticket(
        async_db_session,
        user_id=user_id,
        scope_type="test_scope",
        scope_id=scope_id
    )
    
    # 2. Try to consume with wrong scope_type
    with pytest.raises(WsTicketScopeError):
        await ws_ticket_service.consume_ticket(
            async_db_session,
            token=issue_result.token,
            scope_type="wrong_scope",
            scope_id=scope_id
        )
    
    # 3. Try to consume with None scope_type (if expected is not None)
    with pytest.raises(WsTicketScopeError):
        await ws_ticket_service.consume_ticket(
            async_db_session,
            token=issue_result.token,
            scope_type="",
            scope_id=scope_id
        )
        
    # 4. Success case
    consumed = await ws_ticket_service.consume_ticket(
        async_db_session,
        token=issue_result.token,
        scope_type="test_scope",
        scope_id=scope_id
    )
    assert consumed.user_id == user_id

@pytest.mark.asyncio
async def test_cleanup_tickets(async_db_session):
    """Verify that cleanup_tickets deletes expired, old used, or NULL scope_type tickets."""
    now = utc_now()
    user_id = uuid4()
    
    # 1. Valid ticket (should NOT be deleted)
    await ws_ticket_service.issue_ticket(
        async_db_session, user_id=user_id, scope_type="valid", scope_id=uuid4()
    )
    
    # 2. Expired ticket
    expired_ticket = WsTicket(
        user_id=user_id,
        scope_type="expired",
        scope_id=uuid4(),
        token_hash="hash1",
        expires_at=now - timedelta(minutes=1)
    )
    async_db_session.add(expired_ticket)
    
    # 3. Old used ticket (beyond 7 days default)
    old_used_ticket = WsTicket(
        user_id=user_id,
        scope_type="old_used",
        scope_id=uuid4(),
        token_hash="hash2",
        expires_at=now + timedelta(minutes=10),
        used_at=now - timedelta(days=8)
    )
    async_db_session.add(old_used_ticket)
    
    # 4. Recently used ticket (should NOT be deleted)
    recent_used_ticket = WsTicket(
        user_id=user_id,
        scope_type="recent_used",
        scope_id=uuid4(),
        token_hash="hash3",
        expires_at=now + timedelta(minutes=10),
        used_at=now - timedelta(days=1)
    )
    async_db_session.add(recent_used_ticket)
    
    # 5. NULL scope_type ticket (legacy)
    null_scope_ticket = WsTicket(
        user_id=user_id,
        scope_type=None,
        scope_id=uuid4(),
        token_hash="hash4",
        expires_at=now + timedelta(minutes=10)
    )
    async_db_session.add(null_scope_ticket)
    
    await async_db_session.commit()
    
    # Run cleanup
    deleted_count = await ws_ticket_service.cleanup_tickets(async_db_session)
    assert deleted_count == 3  # expired, old_used, null_scope
    
    # Verify remaining tickets
    stmt = select(WsTicket)
    remaining = (await async_db_session.scalars(stmt)).all()
    remaining_scopes = {t.scope_type for t in remaining}
    assert "valid" in remaining_scopes
    assert "recent_used" in remaining_scopes
    assert len(remaining) == 2
