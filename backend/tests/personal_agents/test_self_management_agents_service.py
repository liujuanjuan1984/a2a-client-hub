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
from app.features.personal_agents.self_management_agents_service import (
    self_management_agents_service,
)
from tests.support.utils import create_a2a_agent, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _build_gateway(user):
    actor = build_self_management_actor_context(
        user=user,
        actor_type=SelfManagementActorType.HUMAN_API,
    )
    return SelfManagementToolGateway(actor, surface=SelfManagementSurface.REST)


async def test_self_management_agents_service_list_and_get_agents(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    first = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="self-list-a",
        tags=["alpha"],
    )
    second = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="self-list-b",
        enabled=False,
    )
    gateway = _build_gateway(user)

    items, total, counts = await self_management_agents_service.list_agents(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        page=1,
        size=20,
    )
    fetched = await self_management_agents_service.get_agent(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        agent_id=first.id,
    )

    returned_ids = {item.id for item in items}
    assert total >= 2
    assert first.id in returned_ids
    assert second.id in returned_ids
    assert counts.unknown >= 2
    assert fetched.id == first.id
    assert fetched.tags == ["alpha"]


async def test_self_management_agents_service_update_config(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    record = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="self-update",
    )
    gateway = _build_gateway(user)

    updated = await self_management_agents_service.update_config(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        agent_id=record.id,
        name="Updated Agent",
        enabled=False,
        tags=["cli", "self"],
        extra_headers={"X-Test": "1"},
        invoke_metadata_defaults={"model": "gpt-5"},
    )

    assert updated.name == "Updated Agent"
    assert updated.enabled is False
    assert updated.tags == ["cli", "self"]
    assert updated.extra_headers == {"X-Test": "1"}
    assert updated.invoke_metadata_defaults == {"model": "gpt-5"}
