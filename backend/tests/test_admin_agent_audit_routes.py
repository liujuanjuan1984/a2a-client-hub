from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.api import deps
from app.api.routers import admin_agent_audit
from app.core.config import settings
from app.db.models.agent_audit_log import AgentAuditLog
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_user


async def _insert_audit_log(session, user_id):
    entry = AgentAuditLog(
        run_id=uuid4(),
        trigger_user_id=user_id,
        session_id=None,
        message_id=None,
        agent_name="audit-agent",
        tool_name="create_task",
        tool_call_id="call-1",
        operation="tasks.create",
        status="finished",
        duration_ms=1234,
        target_entities={"type": "task", "ids": ["task-1"]},
        before_snapshot=None,
        after_snapshot={"task": {"id": "task-1", "content": "demo"}},
        extra={"arguments": {"content": "demo"}},
    )
    session.add(entry)
    await session.flush()
    return entry


@pytest.mark.asyncio
async def test_admin_agent_audit_endpoints(async_db_session, async_session_maker):
    admin_user = await create_user(
        async_db_session, is_superuser=True, skip_onboarding_defaults=True
    )
    entry = await _insert_audit_log(async_db_session, user_id=admin_user.id)
    await async_db_session.commit()

    async def override_admin():
        return admin_user

    overrides = {deps.get_current_admin_user: override_admin}

    async with create_test_client(
        admin_agent_audit.router,
        async_session_maker=async_session_maker,
        overrides=overrides,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        base = f"{settings.api_v1_prefix}/admin/agent-audit"

        response = await client.get(f"{base}/logs")
        assert response.status_code == 200
        payload = response.json()
        assert payload["pagination"]["total"] == 1
        assert payload["items"][0]["tool_name"] == "create_task"

        detail = await client.get(f"{base}/logs/{entry.id}")
        assert detail.status_code == 200
        assert detail.json()["operation"] == "tasks.create"

        preview = await client.post(f"{base}/logs/{entry.id}/rollback-preview")
        assert preview.status_code == 200
        data = preview.json()
        assert "before_snapshot" in data["log"]

        export = await client.get(f"{base}/logs/export")
        assert export.status_code == 200
        assert export.json()["pagination"]["total"] == 1

        entry.created_at = entry.created_at - timedelta(days=120)
        await async_db_session.flush()
        await async_db_session.commit()

        dry_run = await client.post(
            f"{base}/retention/purge", json={"before_days": 90, "dry_run": True}
        )
        assert dry_run.status_code == 200
        assert dry_run.json()["deleted_rows"] == 1

        purge = await client.post(
            f"{base}/retention/purge", json={"before_days": 90, "dry_run": False}
        )
        assert purge.status_code == 200
        assert purge.json()["deleted_rows"] == 1

    async with async_session_maker() as verify_session:
        remaining = await verify_session.scalar(
            select(func.count()).select_from(AgentAuditLog)
        )
        assert remaining == 0
