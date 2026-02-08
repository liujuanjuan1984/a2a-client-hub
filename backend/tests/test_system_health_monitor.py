from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_session import AgentSession
from app.services import system_health_monitor as monitor
from backend.tests.utils import create_user


@pytest.mark.asyncio
async def test_dispatch_health_notification_creates_info_message_for_admin(
    async_db_session, async_session_maker, monkeypatch
):
    admin = await create_user(
        async_db_session, is_superuser=True, skip_onboarding_defaults=True
    )
    await async_db_session.commit()

    monkeypatch.setattr(monitor, "AsyncSessionLocal", async_session_maker)
    fake_checks = [{"name": "database", "status": "healthy", "latency_ms": 12.5}]
    monkeypatch.setattr(
        monitor, "run_health_checks", lambda: ("healthy", fake_checks), raising=False
    )

    await monitor.dispatch_health_notification()

    async with async_session_maker() as verify_session:
        result = await verify_session.execute(
            select(AgentMessage).where(AgentMessage.user_id == admin.id)
        )
        messages = result.scalars().all()
        assert len(messages) == 1
        message = messages[0]
        assert message.sender == "system"
        assert message.message_type == AgentMessage.TYPE_NOTIFICATION
        assert message.severity == AgentMessage.SEVERITY_INFO
        assert "System health status: HEALTHY" in message.content

        system_session = (
            await verify_session.execute(
                select(AgentSession)
                .where(AgentSession.user_id == admin.id)
                .where(AgentSession.session_type == AgentSession.TYPE_SYSTEM)
            )
        ).scalar_one()
        assert system_session.name == "系统通知"


@pytest.mark.asyncio
async def test_dispatch_health_notification_escalates_severity_for_degraded_status(
    async_db_session, async_session_maker, monkeypatch
):
    admin = await create_user(
        async_db_session, is_superuser=True, skip_onboarding_defaults=True
    )
    await async_db_session.commit()

    monkeypatch.setattr(monitor, "AsyncSessionLocal", async_session_maker)
    fake_checks = [
        {
            "name": "database",
            "status": "degraded",
            "latency_ms": 222.1,
            "detail": "slow",
        }
    ]
    monkeypatch.setattr(
        monitor, "run_health_checks", lambda: ("degraded", fake_checks), raising=False
    )

    await monitor.dispatch_health_notification()

    async with async_session_maker() as verify_session:
        message = (
            (
                await verify_session.execute(
                    select(AgentMessage)
                    .where(AgentMessage.user_id == admin.id)
                    .order_by(AgentMessage.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        assert message is not None
        assert message.severity == AgentMessage.SEVERITY_WARNING
        assert "System health status: DEGRADED" in message.content
