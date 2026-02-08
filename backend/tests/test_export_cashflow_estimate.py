from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.api.routers import export as export_router
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_finance_cashflow_estimate_accepts_date_filters(
    async_db_session, async_session_maker
):
    """Regression: ensure start_time/end_time params don't break estimate handler."""

    user = await create_user(async_db_session)

    payload = {
        "module": "finance-cashflow",
        "params": {
            "start_time": datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
            "end_time": datetime(
                2025, 1, 31, 23, 59, 59, tzinfo=timezone.utc
            ).isoformat(),
            "format": "text",
        },
    }

    async with create_test_client(
        export_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post("/export/estimate", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert "estimated_size_bytes" in data
    assert "record_count" in data
    assert "can_clipboard" in data
