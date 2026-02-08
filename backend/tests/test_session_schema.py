from uuid import uuid4

import pytest

from app.db.models.agent_session import AgentSession
from app.schemas.session import SessionResponse
from backend.tests.utils import create_user


@pytest.mark.asyncio
async def test_session_response_exposes_session_type_and_module(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    session = AgentSession(
        id=uuid4(),
        user_id=user.id,
        name="System notifications",
        module_key="system",
        session_type=AgentSession.TYPE_SYSTEM,
    )
    async_db_session.add(session)
    await async_db_session.commit()
    await async_db_session.refresh(session)

    response = SessionResponse.from_orm(session)

    assert response.session_type == AgentSession.TYPE_SYSTEM
    assert response.module_key == "system"
    # agent_name continues to mirror module_key for backwards compatibility
    assert response.agent_name == "system"
