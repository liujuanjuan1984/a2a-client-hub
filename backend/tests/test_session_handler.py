import pytest

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_session import AgentSession
from app.handlers import agent_session as session_service
from app.handlers.agent_session import SessionHandlerError
from backend.tests.utils import create_user

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


async def test_ensure_session_reuses_existing_session_when_agent_matches(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    existing = await session_service.create_session(
        async_db_session,
        user_id=user.id,
        name="Existing",
        module_key="focus_agent",
    )

    ensured = await session_service.ensure_session(
        db=async_db_session,
        user_id=user.id,
        session_id=existing.id,
        agent_name="focus_agent",
    )

    assert ensured.id == existing.id
    assert ensured.module_key == "focus_agent"
    assert ensured.session_type == AgentSession.TYPE_CHAT


async def test_ensure_session_reassigns_agent_when_no_history(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    existing = await session_service.create_session(
        async_db_session,
        user_id=user.id,
        name="Existing",
        module_key="focus_agent",
    )

    ensured = await session_service.ensure_session(
        db=async_db_session,
        user_id=user.id,
        session_id=existing.id,
        agent_name="root_agent",
    )

    assert ensured.id == existing.id
    assert ensured.module_key == "root_agent"


async def test_ensure_session_creates_new_session_when_type_differs(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    existing = await session_service.create_session(
        async_db_session,
        user_id=user.id,
        name="Existing",
        module_key="focus_agent",
        session_type=AgentSession.TYPE_SYSTEM,
    )

    new_session = await session_service.ensure_session(
        db=async_db_session,
        user_id=user.id,
        session_id=existing.id,
        agent_name="focus_agent",
        session_type=AgentSession.TYPE_CHAT,
    )

    assert new_session.id != existing.id
    assert new_session.session_type == AgentSession.TYPE_CHAT
    await async_db_session.refresh(existing)
    assert existing.session_type == AgentSession.TYPE_SYSTEM


async def test_update_session_allows_reassign_without_messages(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    session = await session_service.create_session(
        async_db_session,
        user_id=user.id,
        name="Empty Session",
        module_key="focus_agent",
    )

    updated = await session_service.update_session(
        async_db_session,
        session_id=session.id,
        user_id=user.id,
        agent_name="root_agent",
    )

    assert updated is not None
    assert updated.module_key == "root_agent"


async def test_update_session_blocks_reassign_with_messages(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    session = await session_service.create_session(
        async_db_session,
        user_id=user.id,
        name="ChitChat",
        module_key="focus_agent",
    )
    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            session_id=session.id,
            content="Hello world",
            sender="user",
        )
    )
    await async_db_session.flush()

    with pytest.raises(SessionHandlerError):
        await session_service.update_session(
            async_db_session,
            session_id=session.id,
            user_id=user.id,
            agent_name="root_agent",
        )
