from types import SimpleNamespace
from uuid import uuid4

from app.schemas.agent_message import MAX_MESSAGE_CONTENT_LENGTH, AgentMessageResponse
from app.utils.timezone_util import utc_now


def _build_message(content: str):
    """Helper to mimic the ORM object expected by AgentMessageResponse."""
    return SimpleNamespace(
        id=uuid4(),
        content=content,
        sender="agent",
        is_typing=False,
        created_at=utc_now(),
        user_id=uuid4(),
        session_id=None,
        session=None,
        message_type="chat",
        message_metadata={},
        cardbox_card_id=None,
    )


def test_agent_message_response_truncates_long_content():
    raw = "x" * (MAX_MESSAGE_CONTENT_LENGTH + 5)

    response = AgentMessageResponse.from_orm(_build_message(raw))

    assert len(response.content) == MAX_MESSAGE_CONTENT_LENGTH
    assert response.content == raw[:MAX_MESSAGE_CONTENT_LENGTH]


def test_agent_message_response_keeps_short_content():
    raw = "short message"

    response = AgentMessageResponse.from_orm(_build_message(raw))

    assert response.content == raw
