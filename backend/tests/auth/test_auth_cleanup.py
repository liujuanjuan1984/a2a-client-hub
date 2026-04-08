from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.db.models.auth_audit_event import AuthAuditEvent
from app.db.models.auth_legacy_refresh_revocation import AuthLegacyRefreshRevocation
from app.db.models.auth_refresh_session import AuthRefreshSession
from app.features.auth import cleanup_service as auth_cleanup_module
from app.features.auth.cleanup_service import auth_cleanup_service
from app.utils.timezone_util import utc_now
from tests.support.utils import create_user


@pytest.mark.asyncio
async def test_cleanup_auth_records_removes_only_stale_rows(async_db_session) -> None:
    now = utc_now()
    user = await create_user(async_db_session)
    user_id = user.id

    async_db_session.add_all(
        [
            AuthRefreshSession(
                user_id=user_id,
                current_jti="expired-session",
                expires_at=now - timedelta(days=31),
            ),
            AuthRefreshSession(
                user_id=user_id,
                current_jti="recent-session",
                expires_at=now + timedelta(days=1),
            ),
            AuthLegacyRefreshRevocation(
                user_id=user_id,
                token_jti="expired-legacy-jti",
                expires_at=now - timedelta(minutes=1),
                revoked_at=now - timedelta(days=1),
                revoke_reason="logout",
            ),
            AuthLegacyRefreshRevocation(
                user_id=user_id,
                token_jti="active-legacy-jti",
                expires_at=now + timedelta(days=1),
                revoked_at=now - timedelta(hours=1),
                revoke_reason="logout",
            ),
            AuthAuditEvent(
                user_id=user_id,
                event_type="refresh_failed",
                outcome="failed",
                occurred_at=now - timedelta(days=91),
            ),
            AuthAuditEvent(
                user_id=user_id,
                event_type="refresh_success",
                outcome="success",
                occurred_at=now - timedelta(days=1),
            ),
        ]
    )
    await async_db_session.commit()

    result = await auth_cleanup_service.cleanup_auth_records(
        async_db_session,
        now=now,
        refresh_session_retention_days=30,
        audit_retention_days=90,
    )

    assert result.refresh_sessions_deleted == 1
    assert result.legacy_revocations_deleted == 1
    assert result.audit_events_deleted == 1

    remaining_sessions = (
        await async_db_session.scalars(select(AuthRefreshSession))
    ).all()
    assert [item.current_jti for item in remaining_sessions] == ["recent-session"]

    remaining_revocations = (
        await async_db_session.scalars(select(AuthLegacyRefreshRevocation))
    ).all()
    assert [item.token_jti for item in remaining_revocations] == ["active-legacy-jti"]

    remaining_events = (await async_db_session.scalars(select(AuthAuditEvent))).all()
    assert [item.event_type for item in remaining_events] == ["refresh_success"]


@pytest.mark.asyncio
async def test_cleanup_auth_records_honors_batch_size(async_db_session) -> None:
    now = utc_now()
    user = await create_user(async_db_session)

    for index in range(2):
        async_db_session.add(
            AuthLegacyRefreshRevocation(
                user_id=user.id,
                token_jti=f"expired-legacy-{index}",
                expires_at=now - timedelta(minutes=index + 1),
                revoked_at=now - timedelta(days=1),
                revoke_reason="logout",
            )
        )
    await async_db_session.commit()

    result = await auth_cleanup_service.cleanup_auth_records(
        async_db_session,
        now=now,
        batch_size=1,
    )
    assert result.legacy_revocations_deleted == 1

    remaining = (
        await async_db_session.scalars(select(AuthLegacyRefreshRevocation))
    ).all()
    assert len(remaining) == 1


@pytest.mark.asyncio
async def test_cleanup_auth_records_job_drains_all_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_mock = AsyncMock(
        side_effect=[
            auth_cleanup_module.AuthCleanupResult(500, 0, 0),
            auth_cleanup_module.AuthCleanupResult(0, 500, 0),
            auth_cleanup_module.AuthCleanupResult(0, 0, 12),
        ]
    )
    session_entries = 0

    class _DummySessionContext:
        async def __aenter__(self) -> object:
            nonlocal session_entries
            session_entries += 1
            return object()

        async def __aexit__(self, _exc_type, _exc, _tb) -> None:
            return None

    monkeypatch.setattr(
        auth_cleanup_module,
        "AsyncSessionLocal",
        lambda: _DummySessionContext(),
        raising=False,
    )
    monkeypatch.setattr(
        auth_cleanup_module,
        "_AUTH_CLEANUP_BATCH_SIZE",
        500,
    )
    monkeypatch.setattr(
        auth_cleanup_module.auth_cleanup_service,
        "cleanup_auth_records",
        cleanup_mock,
    )

    await auth_cleanup_module.cleanup_auth_records_job()

    assert cleanup_mock.await_count == 3
    assert session_entries == 3


def test_ensure_auth_cleanup_job_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    added_jobs: dict[str, dict[str, object]] = {}

    class _Scheduler:
        @property
        def jobs(self) -> dict[str, dict[str, object]]:
            return added_jobs

        def get_job(self, job_id: str) -> dict[str, object] | None:
            return added_jobs.get(job_id)

        def add_job(self, func, *, trigger, id, **kwargs):
            added_jobs[id] = {"func": func, "trigger": trigger, **kwargs}

    monkeypatch.setattr(auth_cleanup_module, "get_scheduler", lambda: _Scheduler())

    auth_cleanup_module.ensure_auth_cleanup_job()
    auth_cleanup_module.ensure_auth_cleanup_job()

    assert "auth-cleanup-daily" in added_jobs
    job = added_jobs["auth-cleanup-daily"]
    assert job["func"] is auth_cleanup_module.cleanup_auth_records_job
