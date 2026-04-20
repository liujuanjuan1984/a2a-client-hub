from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.features.sessions import (
    history_projection as session_history_projection_module,
)
from app.features.sessions.common import serialize_interrupt_event_block_content
from app.features.sessions.identity import conversation_identity_service
from app.features.sessions.service import session_hub_service
from app.utils.idempotency_key import (
    IDEMPOTENCY_KEY_MAX_LENGTH,
    normalize_idempotency_key,
)
from app.utils.timezone_util import utc_now
from tests.support.utils import create_user

# ruff: noqa: F401


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _list_message_items(
    async_db_session,
    *,
    user_id,
    conversation_id: str,
    limit: int = 50,
):
    items, _, _ = await session_hub_service.list_messages(
        async_db_session,
        user_id=user_id,
        conversation_id=conversation_id,
        before=None,
        limit=limit,
    )
    return items


__all__ = [
    "AgentMessage",
    "AgentMessageBlock",
    "ConversationThread",
    "IDEMPOTENCY_KEY_MAX_LENGTH",
    "IntegrityError",
    "_list_message_items",
    "conversation_identity_service",
    "create_user",
    "normalize_idempotency_key",
    "pytest",
    "select",
    "serialize_interrupt_event_block_content",
    "session_history_projection_module",
    "session_hub_service",
    "utc_now",
    "uuid4",
]
