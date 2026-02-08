from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.handlers.exports.finance_trading_export import export_finance_trading_data
from app.handlers.finance_trading import (
    create_trading_entry,
    create_trading_instrument,
    create_trading_plan,
)
from app.schemas.export import FinanceTradingExportParams
from tests.utils import create_user


async def _seed_trading(async_db_session, user_id):
    plan = await create_trading_plan(
        async_db_session,
        user_id,
        name="PlanA",
        period_start=None,
        period_end=None,
        target_roi=None,
        note=None,
        status="active",
    )
    inst = await create_trading_instrument(
        async_db_session,
        user_id,
        plan_id=plan.id,
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        exchange="binance",
        strategy_tag=None,
        note=None,
    )
    await create_trading_entry(
        async_db_session,
        user_id,
        plan_id=plan.id,
        instrument_id=inst.id,
        trade_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        direction="buy",
        base_delta=1,
        quote_delta=-30000,
        price=30000,
        fee_asset="USDT",
        fee_amount=10,
        source="manual",
        note="test entry",
    )
    return plan, inst


pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("engine")]


async def test_finance_trading_export_builds_instrument_map(async_db_session):
    user = await create_user(async_db_session)
    plan, inst = await _seed_trading(async_db_session, user.id)

    params = FinanceTradingExportParams(
        plan_id=str(plan.id),
        instrument_id=None,
        start_time=None,
        end_time=None,
        format="csv",
        locale="zh-CN",
    )

    content, content_type, filename = await export_finance_trading_data(
        async_db_session, params, user.id
    )
    assert inst.symbol in content
    assert inst.base_asset in content
    assert content_type == "text/csv"
    assert filename.endswith(".csv")
