from datetime import timedelta
from uuid import uuid4

import pytest

from app.db.models.ws_ticket import WsTicket
from app.services.a2a_agents import a2a_agent_service
from app.services.ws_ticket_service import (
    WsTicketExpiredError,
    WsTicketNotFoundError,
    WsTicketUsedError,
    ws_ticket_service,
)
from app.utils.timezone_util import utc_now
from backend.tests.utils import create_user


@pytest.mark.asyncio
async def test_issue_and_consume_ws_ticket(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name=f"Agent {uuid4().hex[:6]}",
        card_url=f"https://example.com/{uuid4().hex}",
        auth_type="none",
    )

    issued = await ws_ticket_service.issue_ticket(
        async_db_session, user_id=user.id, agent_id=record.agent.id
    )
    assert issued.token
    assert issued.expires_in > 0

    ticket = await ws_ticket_service.consume_ticket(
        async_db_session, token=issued.token, agent_id=record.agent.id
    )
    assert ticket.user_id == user.id

    with pytest.raises(WsTicketUsedError):
        await ws_ticket_service.consume_ticket(
            async_db_session, token=issued.token, agent_id=record.agent.id
        )


@pytest.mark.asyncio
async def test_consume_expired_ws_ticket(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name=f"Agent {uuid4().hex[:6]}",
        card_url=f"https://example.com/{uuid4().hex}",
        auth_type="none",
    )

    token = "expired-ticket"
    token_hash = ws_ticket_service._hash_token(token)
    expired_ticket = WsTicket(
        user_id=user.id,
        agent_id=record.agent.id,
        token_hash=token_hash,
        expires_at=utc_now() - timedelta(seconds=1),
    )
    async_db_session.add(expired_ticket)
    await async_db_session.commit()

    with pytest.raises(WsTicketExpiredError):
        await ws_ticket_service.consume_ticket(
            async_db_session, token=token, agent_id=record.agent.id
        )


@pytest.mark.asyncio
async def test_consume_unknown_ws_ticket(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name=f"Agent {uuid4().hex[:6]}",
        card_url=f"https://example.com/{uuid4().hex}",
        auth_type="none",
    )

    with pytest.raises(WsTicketNotFoundError):
        await ws_ticket_service.consume_ticket(
            async_db_session, token="missing", agent_id=record.agent.id
        )
