from __future__ import annotations

from uuid import uuid4

import pytest

from app.db.models.conversation_thread import ConversationThread
from app.utils.timezone_util import utc_now
from tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_conversation_thread_title_is_normalized_and_truncated(async_db_session):
    user = await create_user(async_db_session)

    thread = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        title="A" * 400,
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(thread)
    await async_db_session.commit()
    await async_db_session.refresh(thread)

    assert len(thread.title) == ConversationThread.TITLE_MAX_LENGTH
    assert thread.title == "A" * ConversationThread.TITLE_MAX_LENGTH

    thread.title = "   "
    await async_db_session.commit()
    await async_db_session.refresh(thread)

    assert thread.title == "Session"
