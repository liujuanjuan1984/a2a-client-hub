from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.features.agents.catalog import router as agent_catalog_router
from app.features.agents.catalog.service import unified_agent_catalog_service
from tests.support.api_utils import create_test_client
from tests.support.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.mark.asyncio
async def test_list_current_user_agent_catalog_returns_unified_items(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(
        async_db_session,
        email="catalog-user@example.com",
        is_superuser=False,
    )

    async def _fake_list_catalog(db, *, user_id):
        assert user_id == user.id
        return [
            {
                "id": "hub-assistant",
                "source": "hub_assistant",
                "name": "A2A Client Hub Assistant",
                "card_url": "hub-assistant://hub-assistant",
                "auth_type": "none",
                "enabled": True,
                "health_status": "healthy",
                "last_health_check_at": None,
                "last_health_check_error": None,
                "last_health_check_reason_code": None,
                "description": "Hub Assistant",
                "runtime": "swival",
                "resources": ["agents", "sessions"],
            },
            {
                "id": "shared-agent-1",
                "source": "shared",
                "name": "Shared Agent",
                "card_url": "https://example.com/shared.json",
                "auth_type": "bearer",
                "enabled": True,
                "health_status": "unknown",
                "last_health_check_at": None,
                "last_health_check_error": None,
                "last_health_check_reason_code": None,
                "credential_mode": "user",
                "credential_configured": False,
                "credential_display_hint": None,
            },
        ]

    monkeypatch.setattr(
        unified_agent_catalog_service,
        "list_catalog",
        _fake_list_catalog,
    )

    async with create_test_client(
        agent_catalog_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.get(f"{settings.api_v1_prefix}/me/agents/catalog")

    assert response.status_code == 200
    payload = response.json()
    assert [item["source"] for item in payload["items"]] == ["hub_assistant", "shared"]
    assert payload["items"][0]["runtime"] == "swival"
    assert payload["items"][1]["credential_mode"] == "user"


@pytest.mark.asyncio
async def test_check_current_user_agent_catalog_health_returns_summary_and_items(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(
        async_db_session,
        email="catalog-health@example.com",
        is_superuser=False,
    )
    checked_at = datetime(2026, 4, 13, 12, 0, tzinfo=UTC)

    async def _fake_check_catalog_health(db, *, user_id, force: bool = False):
        assert user_id == user.id
        assert force is False
        return (
            SimpleNamespace(
                requested=3,
                checked=3,
                skipped_cooldown=0,
                healthy=2,
                degraded=0,
                unavailable=0,
                unknown=1,
            ),
            [
                SimpleNamespace(
                    agent_id="personal-1",
                    agent_source="personal",
                    health_status="healthy",
                    checked_at=checked_at,
                    skipped_cooldown=False,
                    error=None,
                    reason_code=None,
                ),
                SimpleNamespace(
                    agent_id="shared-1",
                    agent_source="shared",
                    health_status="unknown",
                    checked_at=checked_at,
                    skipped_cooldown=False,
                    error="User credential required",
                    reason_code="credential_required",
                ),
                SimpleNamespace(
                    agent_id="hub-assistant",
                    agent_source="hub_assistant",
                    health_status="healthy",
                    checked_at=checked_at,
                    skipped_cooldown=False,
                    error=None,
                    reason_code=None,
                ),
            ],
        )

    monkeypatch.setattr(
        unified_agent_catalog_service,
        "check_catalog_health",
        _fake_check_catalog_health,
    )

    async with create_test_client(
        agent_catalog_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(f"{settings.api_v1_prefix}/me/agents/check-health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "requested": 3,
        "checked": 3,
        "skipped_cooldown": 0,
        "healthy": 2,
        "degraded": 0,
        "unavailable": 0,
        "unknown": 1,
    }
    assert payload["items"][1] == {
        "agent_id": "shared-1",
        "agent_source": "shared",
        "health_status": "unknown",
        "checked_at": "2026-04-13T12:00:00Z",
        "skipped_cooldown": False,
        "error": "User credential required",
        "reason_code": "credential_required",
    }
