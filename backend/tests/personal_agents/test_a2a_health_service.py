from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.models.a2a_agent import A2AAgent
from app.features.personal_agents import service as personal_service_module
from app.features.personal_agents.service import a2a_agent_service
from tests.support.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _fake_runtime_resolver(**kwargs):
    return SimpleNamespace(url=kwargs["card_url"]), None


@pytest.mark.asyncio
async def test_check_agents_health_skips_agents_inside_cooldown(
    async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])
    monkeypatch.setattr(settings, "a2a_agent_health_check_cooldown_seconds", 3600)

    user = await create_user(async_db_session, email="health-cooldown@example.com")
    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name="Cooldown Agent",
        card_url="https://example.com/.well-known/agent-card.json",
        auth_type="none",
        enabled=True,
        tags=[],
        extra_headers={},
    )

    agent = await async_db_session.scalar(
        select(A2AAgent).where(A2AAgent.id == record.id)
    )
    assert agent is not None
    now = datetime.now(UTC)
    agent.health_status = A2AAgent.HEALTH_DEGRADED
    agent.consecutive_health_check_failures = 1
    agent.last_health_check_at = now
    await async_db_session.commit()

    monkeypatch.setattr(
        personal_service_module.a2a_runtime_builder,
        "resolve_prefetched",
        _fake_runtime_resolver,
    )

    async def _should_not_run(**kwargs):
        raise AssertionError("health probe should be skipped during cooldown")

    monkeypatch.setattr(
        personal_service_module,
        "fetch_and_validate_agent_card",
        _should_not_run,
    )

    summary, items = await a2a_agent_service.check_agents_health(
        user_id=user.id,
        force=False,
    )

    assert summary.requested == 1
    assert summary.checked == 0
    assert summary.skipped_cooldown == 1
    assert summary.degraded == 1
    assert len(items) == 1
    assert items[0].health_status == A2AAgent.HEALTH_DEGRADED
    assert items[0].skipped_cooldown is True
    assert items[0].checked_at == now


@pytest.mark.asyncio
async def test_check_agents_health_marks_agent_unavailable_after_threshold(
    async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])
    monkeypatch.setattr(settings, "a2a_agent_health_check_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "a2a_agent_health_unavailable_threshold", 3)

    user = await create_user(async_db_session, email="health-unavailable@example.com")
    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name="Unavailable Agent",
        card_url="https://example.com/.well-known/agent-card.json",
        auth_type="none",
        enabled=True,
        tags=[],
        extra_headers={},
    )

    agent = await async_db_session.scalar(
        select(A2AAgent).where(A2AAgent.id == record.id)
    )
    assert agent is not None
    agent.health_status = A2AAgent.HEALTH_DEGRADED
    agent.consecutive_health_check_failures = 2
    agent.last_health_check_at = datetime.now(UTC) - timedelta(hours=2)
    await async_db_session.commit()

    monkeypatch.setattr(
        personal_service_module.a2a_runtime_builder,
        "resolve_prefetched",
        _fake_runtime_resolver,
    )
    monkeypatch.setattr(
        personal_service_module,
        "get_a2a_service",
        lambda: SimpleNamespace(gateway=object()),
    )

    async def _failed_validation(**kwargs):
        return SimpleNamespace(
            success=False,
            validation_errors=["Connection failed"],
            message=None,
        )

    monkeypatch.setattr(
        personal_service_module,
        "fetch_and_validate_agent_card",
        _failed_validation,
    )

    summary, items = await a2a_agent_service.check_agents_health(
        user_id=user.id,
        force=True,
    )

    assert summary.checked == 1
    assert summary.unavailable == 1
    assert len(items) == 1
    assert items[0].health_status == A2AAgent.HEALTH_UNAVAILABLE
    assert items[0].error == "Connection failed"
    assert items[0].reason_code == "card_validation_failed"

    refreshed = await async_db_session.scalar(
        select(A2AAgent).where(A2AAgent.id == record.id)
    )
    assert refreshed is not None
    await async_db_session.refresh(refreshed)
    assert refreshed.health_status == A2AAgent.HEALTH_UNAVAILABLE
    assert refreshed.consecutive_health_check_failures == 3
    assert refreshed.last_health_check_error == "Connection failed"
    assert refreshed.last_health_check_reason_code == "card_validation_failed"
    assert refreshed.last_health_check_at is not None


@pytest.mark.asyncio
async def test_check_agents_health_marks_agent_healthy_and_resets_failures(
    async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])
    monkeypatch.setattr(settings, "a2a_agent_health_check_cooldown_seconds", 0)

    user = await create_user(async_db_session, email="health-healthy@example.com")
    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name="Healthy Agent",
        card_url="https://example.com/.well-known/agent-card.json",
        auth_type="none",
        enabled=True,
        tags=[],
        extra_headers={},
    )

    agent = await async_db_session.scalar(
        select(A2AAgent).where(A2AAgent.id == record.id)
    )
    assert agent is not None
    agent.health_status = A2AAgent.HEALTH_UNAVAILABLE
    agent.consecutive_health_check_failures = 4
    agent.last_health_check_error = "Previous error"
    await async_db_session.commit()

    monkeypatch.setattr(
        personal_service_module.a2a_runtime_builder,
        "resolve_prefetched",
        _fake_runtime_resolver,
    )
    monkeypatch.setattr(
        personal_service_module,
        "get_a2a_service",
        lambda: SimpleNamespace(gateway=object()),
    )

    async def _successful_validation(**kwargs):
        return SimpleNamespace(success=True)

    monkeypatch.setattr(
        personal_service_module,
        "fetch_and_validate_agent_card",
        _successful_validation,
    )

    summary, items = await a2a_agent_service.check_agents_health(
        user_id=user.id,
        force=True,
    )

    assert summary.checked == 1
    assert summary.healthy == 1
    assert len(items) == 1
    assert items[0].health_status == A2AAgent.HEALTH_HEALTHY
    assert items[0].error is None
    assert items[0].reason_code is None

    refreshed = await async_db_session.scalar(
        select(A2AAgent).where(A2AAgent.id == record.id)
    )
    assert refreshed is not None
    await async_db_session.refresh(refreshed)
    assert refreshed.health_status == A2AAgent.HEALTH_HEALTHY
    assert refreshed.consecutive_health_check_failures == 0
    assert refreshed.last_health_check_error is None
    assert refreshed.last_health_check_reason_code is None
    assert refreshed.last_health_check_at is not None
    assert refreshed.last_successful_health_check_at is not None
