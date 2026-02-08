from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.handlers import agent_message as agent_message_service
from app.handlers.agent_message import AgentMessageCreationError

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_session(monkeypatch):
    db = SimpleNamespace(add=MagicMock(), flush=AsyncMock())
    monkeypatch.setattr(
        agent_message_service.cardbox_service,
        "sync_message",
        MagicMock(return_value=None),
    )
    return db


async def test_create_agent_message_syncs_to_cardbox(mock_session):
    user_id = uuid4()
    session = SimpleNamespace(id=uuid4())

    message = await agent_message_service.create_agent_message(
        mock_session,
        user_id=user_id,
        content="hi",
        sender="user",
        session=session,
        metadata={"foo": "bar"},
    )

    mock_session.add.assert_called_once()
    mock_session.flush.assert_awaited_once()
    agent_message_service.cardbox_service.sync_message.assert_called_once_with(
        message, session=session
    )
    assert message.session_id == session.id
    assert message.user_id == user_id


async def test_create_agent_message_without_cardbox_sync(mock_session):
    user_id = uuid4()

    message = await agent_message_service.create_agent_message(
        mock_session,
        user_id=user_id,
        content="hi",
        sender="agent",
        sync_to_cardbox=False,
    )

    agent_message_service.cardbox_service.sync_message.assert_not_called()
    assert message.sender == "agent"


async def test_update_agent_message_aliases_metadata():
    db = SimpleNamespace(flush=AsyncMock())
    message = SimpleNamespace(content="old", message_metadata=None)

    updated = await agent_message_service.update_agent_message(
        db, message=message, metadata={"key": "value"}, content="new"
    )

    assert updated.content == "new"
    assert updated.message_metadata == {"key": "value"}
    db.flush.assert_awaited_once()


async def test_commit_agent_messages_raises_on_failure(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(
        agent_message_service,
        "commit_safely",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    with pytest.raises(AgentMessageCreationError):
        await agent_message_service.commit_agent_messages(db)
