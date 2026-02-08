from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.api.routers import agentic as agentic_router
from app.schemas.export import FinanceAccountsExportParams, TimeLogExportParams
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_agentic_timelog_wraps_export_text(
    async_db_session, async_session_maker, monkeypatch
):
    user = await create_user(async_db_session)

    captured = {}

    async def fake_export_timelog_data(db, *, params, user_id):
        captured["user_id"] = user_id
        captured["params"] = params
        return "TIMEL0G_CONTENT", {"total_count": 123}

    monkeypatch.setattr(
        "app.api.routers.agentic.export_timelog_data",
        fake_export_timelog_data,
    )

    payload = TimeLogExportParams(
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2025, 1, 2, tzinfo=timezone.utc),
        dimension_id=None,
        description_keyword=None,
    ).model_dump(mode="json")

    async with create_test_client(
        agentic_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post("/agentic/timelog", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["module"] == "timelog"
    assert data["content"] == "TIMEL0G_CONTENT"
    assert data["metadata"]["total_count"] == 123
    assert captured["user_id"] == str(user.id)


async def test_agentic_finance_accounts_wraps_export_text(
    async_db_session, async_session_maker, monkeypatch
):
    user = await create_user(async_db_session)

    async def fake_export_finance_accounts_data(db, *, params, user_id):
        assert user_id == user.id
        assert isinstance(params, FinanceAccountsExportParams)
        return "ACCOUNTS_CONTENT", "text/plain", "accounts.txt"

    monkeypatch.setattr(
        "app.api.routers.agentic.export_finance_accounts_data",
        fake_export_finance_accounts_data,
    )

    async with create_test_client(
        agentic_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post("/agentic/finance/accounts", json={"format": "text"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["module"] == "finance-accounts"
    assert data["content"] == "ACCOUNTS_CONTENT"
    assert data["metadata"]["filename"] == "accounts.txt"
