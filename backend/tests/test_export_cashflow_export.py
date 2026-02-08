from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.handlers import finance_cashflow, finance_cashflow_trees
from app.handlers.exports.finance_cashflow_export import export_finance_cashflow_data
from app.schemas.export import FinanceCashflowExportParams
from tests.utils import create_user

pytestmark = pytest.mark.asyncio


async def _make_snapshot(session, user_id):
    tree = await finance_cashflow_trees.ensure_default_cashflow_tree(session, user_id)
    source = await finance_cashflow.create_cashflow_source(
        session,
        user_id,
        tree_id=tree.id,
        name="Salary",
        parent_id=None,
        metadata=None,
        sort_order=None,
        kind="income",
        billing_cycle_type=None,
        billing_cycle_interval=None,
        billing_anchor_day=None,
        billing_anchor_date=None,
        billing_post_to=None,
        billing_default_amount=None,
        billing_default_note=None,
        billing_requires_manual_input=None,
    )

    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=29)

    await finance_cashflow.create_cashflow_snapshot(
        session,
        user_id,
        tree_id=tree.id,
        primary_currency="USD",
        period_start=start,
        period_end=end,
        entries_payload=[(source, Decimal("123.45"), "Jan pay")],
        note="Jan snapshot",
    )


async def test_finance_cashflow_export_handles_snapshot_entries(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    await _make_snapshot(async_db_session, user.id)

    params = FinanceCashflowExportParams(
        start_time=None,
        end_time=None,
        format="text",
        locale="zh-CN",
    )

    content, content_type, filename = await export_finance_cashflow_data(
        async_db_session, params, user.id
    )
    assert "Salary" in content
    assert "123.45" in content
    assert content_type == "text/plain"
    assert filename.endswith(".txt")
