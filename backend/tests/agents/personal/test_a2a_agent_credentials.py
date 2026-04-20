from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models.a2a_agent_credential import A2AAgentCredential
from app.features.agents.personal.service import a2a_agent_service
from tests.support.utils import create_user


async def _create_bearer_agent(async_db_session, *, user_id, suffix: str):
    return await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user_id,
        name=f"agent-{suffix}",
        card_url=f"https://example.com/{suffix}",
        auth_type="bearer",
        auth_header="Authorization",
        auth_scheme="Bearer",
        enabled=True,
        tags=["test"],
        extra_headers={"X-Test": "1"},
        token="token1234",
    )


async def _get_credential(async_db_session, *, agent_id):
    return await async_db_session.scalar(
        select(A2AAgentCredential).where(A2AAgentCredential.agent_id == agent_id)
    )


@pytest.mark.asyncio
async def test_update_to_none_hard_deletes_credential(async_db_session):
    user = await create_user(async_db_session, email="a2a-hard-delete-none@example.com")
    record = await _create_bearer_agent(
        async_db_session, user_id=user.id, suffix=f"none-{uuid4().hex}"
    )

    credential = await _get_credential(async_db_session, agent_id=record.id)
    assert credential is not None

    updated = await a2a_agent_service.update_agent(
        async_db_session,
        user_id=user.id,
        agent_id=record.id,
        auth_type="none",
        token=None,
    )
    assert updated.token_last4 is None

    credential = await _get_credential(async_db_session, agent_id=record.id)
    assert credential is None


@pytest.mark.asyncio
async def test_delete_agent_hard_deletes_credential(async_db_session):
    user = await create_user(
        async_db_session, email="a2a-hard-delete-agent@example.com"
    )
    record = await _create_bearer_agent(
        async_db_session, user_id=user.id, suffix=f"delete-{uuid4().hex}"
    )

    await a2a_agent_service.delete_agent(
        async_db_session,
        user_id=user.id,
        agent_id=record.id,
    )

    credential = await _get_credential(async_db_session, agent_id=record.id)
    assert credential is None


@pytest.mark.asyncio
async def test_upsert_keeps_single_credential_row(async_db_session):
    user = await create_user(
        async_db_session, email="a2a-hard-delete-legacy@example.com"
    )
    record = await _create_bearer_agent(
        async_db_session, user_id=user.id, suffix=f"legacy-{uuid4().hex}"
    )
    credential = await _get_credential(async_db_session, agent_id=record.id)
    assert credential is not None

    updated = await a2a_agent_service.update_agent(
        async_db_session,
        user_id=user.id,
        agent_id=record.id,
        auth_type="bearer",
        token="token9999",
    )
    assert updated.token_last4 == "9999"

    rows = (
        await async_db_session.execute(
            select(A2AAgentCredential).where(A2AAgentCredential.agent_id == record.id)
        )
    ).scalars()
    credentials = list(rows)
    assert len(credentials) == 1
    assert credentials[0].token_last4 == "9999"


@pytest.mark.asyncio
async def test_changing_auth_type_requires_new_credential(async_db_session):
    user = await create_user(async_db_session, email="a2a-switch-auth-type@example.com")
    record = await _create_bearer_agent(
        async_db_session, user_id=user.id, suffix=f"switch-{uuid4().hex}"
    )

    with pytest.raises(Exception, match="New credentials are required"):
        await a2a_agent_service.update_agent(
            async_db_session,
            user_id=user.id,
            agent_id=record.id,
            auth_type="basic",
        )
