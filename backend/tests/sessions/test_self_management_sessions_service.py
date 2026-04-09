from __future__ import annotations

import pytest

from app.features.agents_shared.actor_context import (
    SelfManagementActorType,
    build_self_management_actor_context,
)
from app.features.agents_shared.tool_gateway import (
    SelfManagementSurface,
    SelfManagementToolGateway,
)
from app.features.sessions.self_management_sessions_service import (
    self_management_sessions_service,
)
from tests.support.utils import create_conversation_thread, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _build_gateway(user):
    actor = build_self_management_actor_context(
        user=user,
        actor_type=SelfManagementActorType.HUMAN_API,
    )
    return SelfManagementToolGateway(actor, surface=SelfManagementSurface.REST)


async def test_self_management_sessions_service_list_and_get_sessions(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    manual_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Manual Thread",
    )
    scheduled_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        source="scheduled",
        title="Scheduled Thread",
    )
    gateway = _build_gateway(user)

    items, extra, db_mutated = await self_management_sessions_service.list_sessions(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        page=1,
        size=20,
    )
    fetched = await self_management_sessions_service.get_session(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        conversation_id=str(manual_thread.id),
    )

    assert db_mutated is False
    assert extra["pagination"]["total"] >= 2
    returned_ids = {item["conversationId"] for item in items}
    assert str(manual_thread.id) in returned_ids
    assert str(scheduled_thread.id) in returned_ids
    assert fetched["conversationId"] == str(manual_thread.id)
    assert fetched["title"] == "Manual Thread"


async def test_self_management_sessions_service_list_respects_filters(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    kept_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        source="scheduled",
        title="Keep Me",
    )
    await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Skip Me",
    )
    gateway = _build_gateway(user)

    items, extra, db_mutated = await self_management_sessions_service.list_sessions(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        page=1,
        size=20,
        source="scheduled",
    )

    assert db_mutated is False
    assert extra["pagination"]["total"] == 1
    assert len(items) == 1
    assert items[0]["conversationId"] == str(kept_thread.id)
    assert items[0]["source"] == "scheduled"
