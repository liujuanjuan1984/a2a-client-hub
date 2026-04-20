from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models.user_agent_availability_snapshot import UserAgentAvailabilitySnapshot
from app.features.agents_catalog.service import unified_agent_catalog_service
from app.features.hub_agents.runtime import HubA2AUserCredentialRequiredError
from tests.support.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.mark.asyncio
async def test_list_catalog_reads_persisted_shared_and_builtin_snapshots(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(
        async_db_session,
        email="catalog-snapshots@example.com",
        is_superuser=False,
    )
    shared_agent_id = str(uuid4())
    checked_at = datetime(2026, 4, 13, 12, 0, tzinfo=UTC)

    async_db_session.add_all(
        [
            UserAgentAvailabilitySnapshot(
                user_id=user.id,
                agent_source="shared",
                agent_id=shared_agent_id,
                health_status="healthy",
                last_health_check_at=checked_at,
                last_successful_health_check_at=checked_at,
                last_health_check_reason_code=None,
            ),
            UserAgentAvailabilitySnapshot(
                user_id=user.id,
                agent_source="hub_assistant",
                agent_id="hub-assistant",
                health_status="unavailable",
                last_health_check_at=checked_at,
                last_health_check_error="Built-in runtime unavailable",
                last_health_check_reason_code="agent_unavailable",
            ),
        ]
    )
    await async_db_session.flush()

    async def _fake_list_all_agents(db, *, user_id):
        assert user_id == user.id
        return []

    async def _fake_list_visible_agents_for_user(db, *, user_id, page, size):
        assert user_id == user.id
        assert page == 1
        return (
            [
                SimpleNamespace(
                    id=shared_agent_id,
                    name="Shared Agent",
                    card_url="https://example.com/shared.json",
                    auth_type="none",
                    credential_mode="none",
                    credential_configured=True,
                    credential_display_hint=None,
                )
            ],
            1,
        )

    monkeypatch.setattr(
        "app.features.agents_catalog.service.a2a_agent_service.list_all_agents",
        _fake_list_all_agents,
    )
    monkeypatch.setattr(
        "app.features.agents_catalog.service.hub_a2a_agent_service.list_visible_agents_for_user",
        _fake_list_visible_agents_for_user,
    )
    monkeypatch.setattr(
        "app.features.agents_catalog.service.hub_assistant_service.get_profile",
        lambda: SimpleNamespace(
            agent_id="hub-assistant",
            name="A2A Client Hub Assistant",
            description="Built-in assistant",
            runtime="swival",
            configured=True,
            resources=("agents",),
        ),
    )

    items = await unified_agent_catalog_service.list_catalog(
        async_db_session,
        user_id=user.id,
    )

    by_source = {item["source"]: item for item in items}
    assert by_source["shared"]["health_status"] == "healthy"
    assert by_source["shared"]["last_health_check_at"] == checked_at
    assert by_source["shared"]["last_health_check_reason_code"] is None
    assert by_source["hub_assistant"]["health_status"] == "unavailable"
    assert (
        by_source["hub_assistant"]["last_health_check_error"]
        == "Built-in runtime unavailable"
    )
    assert (
        by_source["hub_assistant"]["last_health_check_reason_code"]
        == "agent_unavailable"
    )


@pytest.mark.asyncio
async def test_check_catalog_health_persists_shared_and_builtin_snapshots(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(
        async_db_session,
        email="catalog-health-persist@example.com",
        is_superuser=False,
    )
    shared_agent_id = uuid4()

    async def _fake_check_agents_health(*, user_id, force: bool = False):
        assert user_id == user.id
        assert force is True
        return (
            SimpleNamespace(
                requested=0,
                checked=0,
                skipped_cooldown=0,
                healthy=0,
                degraded=0,
                unavailable=0,
                unknown=0,
            ),
            [],
        )

    async def _fake_list_visible_agents_for_user(db, *, user_id, page, size):
        assert user_id == user.id
        assert page == 1
        return (
            [
                SimpleNamespace(
                    id=shared_agent_id,
                    name="Shared Agent",
                    card_url="https://example.com/shared.json",
                    auth_type="none",
                    credential_mode="none",
                    credential_configured=True,
                    credential_display_hint=None,
                )
            ],
            1,
        )

    async def _fake_build(db, *, user_id, agent_id):
        assert user_id == user.id
        assert agent_id == shared_agent_id
        return SimpleNamespace(resolved=object())

    async def _fake_validate(*, gateway, resolved):
        assert resolved is not None
        return SimpleNamespace(success=True)

    monkeypatch.setattr(
        "app.features.agents_catalog.service.a2a_agent_service.check_agents_health",
        _fake_check_agents_health,
    )
    monkeypatch.setattr(
        "app.features.agents_catalog.service.hub_a2a_agent_service.list_visible_agents_for_user",
        _fake_list_visible_agents_for_user,
    )
    monkeypatch.setattr(
        "app.features.agents_catalog.service.hub_a2a_runtime_builder.build",
        _fake_build,
    )
    monkeypatch.setattr(
        "app.features.agents_catalog.service.fetch_and_validate_agent_card",
        _fake_validate,
    )
    monkeypatch.setattr(
        "app.features.agents_catalog.service.get_a2a_service",
        lambda: SimpleNamespace(gateway=object()),
    )
    monkeypatch.setattr(
        "app.features.agents_catalog.service.hub_assistant_service.get_profile",
        lambda: SimpleNamespace(
            agent_id="hub-assistant",
            name="A2A Client Hub Assistant",
            description="Built-in assistant",
            runtime="swival",
            configured=True,
            resources=("agents",),
        ),
    )

    summary, items = await unified_agent_catalog_service.check_catalog_health(
        async_db_session,
        user_id=user.id,
        force=True,
    )

    assert summary.requested == 2
    assert summary.healthy == 2
    assert {(item.agent_source, item.health_status) for item in items} == {
        ("shared", "healthy"),
        ("hub_assistant", "healthy"),
    }
    assert all(item.reason_code is None for item in items)

    snapshots = (
        await async_db_session.scalars(
            select(UserAgentAvailabilitySnapshot).where(
                UserAgentAvailabilitySnapshot.user_id == user.id
            )
        )
    ).all()
    assert {
        (
            row.agent_source,
            row.agent_id,
            row.health_status,
            row.last_health_check_reason_code,
        )
        for row in snapshots
    } == {
        ("shared", str(shared_agent_id), "healthy", None),
        ("hub_assistant", "hub-assistant", "healthy", None),
    }


@pytest.mark.asyncio
async def test_check_catalog_health_marks_missing_shared_credential_unavailable(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(
        async_db_session,
        email="catalog-health-credential@example.com",
        is_superuser=False,
    )
    shared_agent_id = uuid4()

    async def _fake_check_agents_health(*, user_id, force: bool = False):
        assert user_id == user.id
        assert force is True
        return (
            SimpleNamespace(
                requested=0,
                checked=0,
                skipped_cooldown=0,
                healthy=0,
                degraded=0,
                unavailable=0,
                unknown=0,
            ),
            [],
        )

    async def _fake_list_visible_agents_for_user(db, *, user_id, page, size):
        assert user_id == user.id
        assert page == 1
        return (
            [
                SimpleNamespace(
                    id=shared_agent_id,
                    name="Shared Agent",
                    card_url="https://example.com/shared.json",
                    auth_type="bearer",
                    credential_mode="user",
                    credential_configured=False,
                    credential_display_hint=None,
                )
            ],
            1,
        )

    async def _fake_build(db, *, user_id, agent_id):
        raise HubA2AUserCredentialRequiredError("User credential required")

    monkeypatch.setattr(
        "app.features.agents_catalog.service.a2a_agent_service.check_agents_health",
        _fake_check_agents_health,
    )
    monkeypatch.setattr(
        "app.features.agents_catalog.service.hub_a2a_agent_service.list_visible_agents_for_user",
        _fake_list_visible_agents_for_user,
    )
    monkeypatch.setattr(
        "app.features.agents_catalog.service.hub_a2a_runtime_builder.build",
        _fake_build,
    )
    monkeypatch.setattr(
        "app.features.agents_catalog.service.hub_assistant_service.get_profile",
        lambda: SimpleNamespace(
            agent_id="hub-assistant",
            name="A2A Client Hub Assistant",
            description="Built-in assistant",
            runtime="swival",
            configured=False,
            resources=(),
        ),
    )

    summary, items = await unified_agent_catalog_service.check_catalog_health(
        async_db_session,
        user_id=user.id,
        force=True,
    )

    assert summary.requested == 1
    assert summary.unavailable == 1
    assert items[0].agent_source == "shared"
    assert items[0].health_status == "unavailable"
    assert items[0].error == "User credential required"
    assert items[0].reason_code == "credential_required"

    snapshot = await async_db_session.scalar(
        select(UserAgentAvailabilitySnapshot).where(
            UserAgentAvailabilitySnapshot.user_id == user.id,
            UserAgentAvailabilitySnapshot.agent_source == "shared",
            UserAgentAvailabilitySnapshot.agent_id == str(shared_agent_id),
        )
    )
    assert snapshot is not None
    assert snapshot.health_status == "unavailable"
    assert snapshot.last_health_check_error == "User credential required"
    assert snapshot.last_health_check_reason_code == "credential_required"
