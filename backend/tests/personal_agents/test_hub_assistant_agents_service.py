from __future__ import annotations

import pytest

from app.features.hub_access.actor_context import (
    HubActorType,
    build_hub_actor_context,
)
from app.features.hub_access.operation_gateway import (
    HubOperationGateway,
    HubSurface,
)
from app.features.personal_agents import service as personal_agent_service_module
from app.features.personal_agents.hub_assistant_agents_service import (
    hub_assistant_agents_service,
)
from app.features.personal_agents.service import A2AAgentNotFoundError
from tests.support.utils import create_a2a_agent, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _build_gateway(user):
    actor = build_hub_actor_context(
        user=user,
        actor_type=HubActorType.HUMAN_API,
    )
    return HubOperationGateway(actor, surface=HubSurface.REST)


async def test_hub_assistant_agents_service_list_and_get_agents(
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

    items, total, counts = await hub_assistant_agents_service.list_agents(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        page=1,
        size=20,
    )
    fetched = await hub_assistant_agents_service.get_agent(
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


async def test_hub_assistant_agents_service_update_config(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    record = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="self-update",
    )
    gateway = _build_gateway(user)

    updated = await hub_assistant_agents_service.update_config(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        agent_id=record.id,
        name="Updated Agent",
        enabled=False,
        tags=["hub-assistant", "self"],
        extra_headers={"X-Test": "1"},
        invoke_metadata_defaults={"model": "gpt-5"},
    )

    assert updated.name == "Updated Agent"
    assert updated.enabled is False
    assert updated.tags == ["hub-assistant", "self"]
    assert updated.extra_headers == {"X-Test": "1"}
    assert updated.invoke_metadata_defaults == {"model": "gpt-5"}


async def test_hub_assistant_agents_service_checks_agent_health(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    record = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="self-health",
    )
    gateway = _build_gateway(user)

    async def _fake_check_agents_health(*, user_id, force=False, agent_id=None):
        assert user_id == user.id
        return (
            personal_agent_service_module.A2AAgentHealthCheckSummaryRecord(
                requested=1 if agent_id is not None else 2,
                checked=1,
                skipped_cooldown=0,
                healthy=1,
                degraded=0,
                unavailable=0,
                unknown=0,
            ),
            [
                personal_agent_service_module.A2AAgentHealthCheckItemRecord(
                    agent_id=record.id,
                    health_status="healthy",
                    checked_at=record.updated_at,
                    skipped_cooldown=not force,
                    error=None,
                    reason_code=None,
                )
            ],
        )

    monkeypatch.setattr(
        personal_agent_service_module.a2a_agent_service,
        "check_agents_health",
        _fake_check_agents_health,
    )

    single_summary, single_items = (
        await hub_assistant_agents_service.check_agent_health(
            db=async_db_session,
            gateway=gateway,
            current_user=user,
            agent_id=record.id,
            force=True,
        )
    )
    all_summary, all_items = await hub_assistant_agents_service.check_all_agents_health(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        force=True,
    )

    assert single_summary.requested == 1
    assert len(single_items) == 1
    assert single_items[0].agent_id == record.id
    assert all_summary.requested >= 1
    assert any(item.agent_id == record.id for item in all_items)


async def test_hub_assistant_agents_service_create_and_delete_agent(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    gateway = _build_gateway(user)

    created = await hub_assistant_agents_service.create_agent(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        name="Created Agent",
        card_url="https://example.com/self-created/.well-known/agent-card.json",
        auth_type="bearer",
        token="secret-token",
        tags=["managed"],
        extra_headers={"X-Scope": "self"},
    )

    assert created.name == "Created Agent"
    assert created.auth_type == "bearer"
    assert created.tags == ["managed"]
    assert created.extra_headers == {"X-Scope": "self"}
    assert created.token_last4 == "oken"

    await hub_assistant_agents_service.delete_agent(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        agent_id=created.id,
    )

    with pytest.raises(A2AAgentNotFoundError, match="A2A agent not found"):
        await hub_assistant_agents_service.get_agent(
            db=async_db_session,
            gateway=gateway,
            current_user=user,
            agent_id=created.id,
        )
