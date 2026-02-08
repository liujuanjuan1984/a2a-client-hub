from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.handlers import finance_trading as trading_service
from app.handlers.metrics import trading_metrics as metrics_service
from tests.utils import create_user

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


async def test_trading_plan_crud_flow(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    plan = await trading_service.create_trading_plan(
        async_db_session,
        user.id,
        name="Q1 Alpha",
        period_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        period_end=datetime(2025, 3, 31, tzinfo=timezone.utc),
        target_roi=Decimal("0.2500"),
        note="Aggressive",
        status="draft",
    )

    assert plan.status == "draft"

    updated = await trading_service.update_trading_plan(
        async_db_session,
        user.id,
        plan.id,
        name="Q1 Alpha+",
        status="active",
    )
    assert updated.name == "Q1 Alpha+"
    assert updated.status == "active"

    archived = await trading_service.archive_trading_plan(
        async_db_session, user.id, plan.id
    )
    assert archived.status == "archived"


async def test_instrument_symbol_conflict(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    plan = await trading_service.create_trading_plan(
        async_db_session,
        user.id,
        name="Plan",
        period_start=None,
        period_end=None,
        target_roi=None,
        note=None,
        status="draft",
    )

    await trading_service.create_trading_instrument(
        async_db_session,
        user.id,
        plan_id=plan.id,
        symbol="BTC/USDT",
        base_asset="BTC",
        quote_asset="USDT",
        exchange="Binance",
        strategy_tag=None,
        note=None,
    )

    with pytest.raises(trading_service.TradingInstrumentConflictError):
        await trading_service.create_trading_instrument(
            async_db_session,
            user.id,
            plan_id=plan.id,
            symbol="btc/usdt",
            base_asset="BTC",
            quote_asset="USDT",
            exchange=None,
            strategy_tag=None,
            note=None,
        )


async def test_entry_requires_matching_instrument_plan(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    plan_a = await trading_service.create_trading_plan(
        async_db_session,
        user.id,
        name="Plan A",
        period_start=None,
        period_end=None,
        target_roi=None,
        note=None,
        status="draft",
    )
    plan_b = await trading_service.create_trading_plan(
        async_db_session,
        user.id,
        name="Plan B",
        period_start=None,
        period_end=None,
        target_roi=None,
        note=None,
        status="draft",
    )

    instrument_a = await trading_service.create_trading_instrument(
        async_db_session,
        user.id,
        plan_id=plan_a.id,
        symbol="ETH/USDT",
        base_asset="ETH",
        quote_asset="USDT",
        exchange=None,
        strategy_tag=None,
        note=None,
    )
    instrument_b = await trading_service.create_trading_instrument(
        async_db_session,
        user.id,
        plan_id=plan_b.id,
        symbol="SOL/USDT",
        base_asset="SOL",
        quote_asset="USDT",
        exchange=None,
        strategy_tag=None,
        note=None,
    )

    trade_time = datetime(2025, 2, 1, 12, tzinfo=timezone.utc)

    entry = await trading_service.create_trading_entry(
        async_db_session,
        user.id,
        plan_id=plan_a.id,
        instrument_id=instrument_a.id,
        trade_time=trade_time,
        direction="buy",
        base_delta=Decimal("1"),
        quote_delta=Decimal("-2500"),
        price=Decimal("2500"),
        fee_asset="USDT",
        fee_amount=Decimal("2.5"),
        source="manual",
        note="test",
    )
    assert entry.instrument_id == instrument_a.id

    with pytest.raises(trading_service.TradingInstrumentMismatchError):
        await trading_service.create_trading_entry(
            async_db_session,
            user.id,
            plan_id=plan_a.id,
            instrument_id=instrument_b.id,
            trade_time=trade_time,
            direction="buy",
            base_delta=Decimal("1"),
            quote_delta=Decimal("-2500"),
            price=Decimal("2500"),
            fee_asset=None,
            fee_amount=None,
            source="manual",
            note=None,
        )


async def test_metrics_recalculation_tracks_realized_and_unrealized(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    plan = await trading_service.create_trading_plan(
        async_db_session,
        user.id,
        name="Metrics",
        period_start=None,
        period_end=None,
        target_roi=None,
        note=None,
        status="active",
    )
    instrument = await trading_service.create_trading_instrument(
        async_db_session,
        user.id,
        plan_id=plan.id,
        symbol="BTC/USDT",
        base_asset="BTC",
        quote_asset="USDT",
        exchange=None,
        strategy_tag=None,
        note=None,
    )
    trade_time = datetime(2025, 4, 1, tzinfo=timezone.utc)
    await trading_service.create_trading_entry(
        async_db_session,
        user.id,
        plan_id=plan.id,
        instrument_id=instrument.id,
        trade_time=trade_time,
        direction="buy",
        base_delta=Decimal("1"),
        quote_delta=Decimal("-20000"),
        price=Decimal("20000"),
        fee_asset="USDT",
        fee_amount=Decimal("10"),
        source="manual",
        note=None,
    )
    await trading_service.create_trading_entry(
        async_db_session,
        user.id,
        plan_id=plan.id,
        instrument_id=instrument.id,
        trade_time=trade_time.replace(day=2),
        direction="sell",
        base_delta=Decimal("-0.4"),
        quote_delta=Decimal("9000"),
        price=Decimal("22500"),
        fee_asset="USDT",
        fee_amount=Decimal("5"),
        source="manual",
        note=None,
    )

    metrics = await metrics_service.recalculate_instrument_metrics(
        async_db_session, user.id, instrument.id
    )
    assert metrics.net_position == Decimal("0.6")
    assert metrics.total_base_in == Decimal("1")
    assert metrics.total_base_out == Decimal("0.4")
    assert metrics.realized_pnl > Decimal("0")


async def test_metrics_handle_flipping_positions(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    plan = await trading_service.create_trading_plan(
        async_db_session,
        user.id,
        name="Flip",
        period_start=None,
        period_end=None,
        target_roi=None,
        note=None,
        status="active",
    )
    instrument = await trading_service.create_trading_instrument(
        async_db_session,
        user.id,
        plan_id=plan.id,
        symbol="ETH/USDT",
        base_asset="ETH",
        quote_asset="USDT",
        exchange=None,
        strategy_tag=None,
        note=None,
    )

    entries = [
        (
            "sell",
            Decimal("-1"),
            Decimal("3538.6691"),
            datetime(2025, 11, 13, 7, 22, tzinfo=timezone.utc),
        ),
        (
            "buy",
            Decimal("1.00697202"),
            Decimal("-3457.23"),
            datetime(2025, 11, 13, 14, 20, tzinfo=timezone.utc),
        ),
        (
            "sell",
            Decimal("-1.6069"),
            Decimal("5104.2348"),
            datetime(2025, 11, 17, 0, 32, tzinfo=timezone.utc),
        ),
        (
            "buy",
            Decimal("1.60690143"),
            Decimal("-5000"),
            datetime(2025, 11, 17, 7, 47, tzinfo=timezone.utc),
        ),
    ]

    for direction, base_delta, quote_delta, trade_time in entries:
        await trading_service.create_trading_entry(
            async_db_session,
            user.id,
            plan_id=plan.id,
            instrument_id=instrument.id,
            trade_time=trade_time,
            direction=direction,
            base_delta=base_delta,
            quote_delta=quote_delta,
            price=None,
            fee_asset=None,
            fee_amount=Decimal("0"),
            source="manual",
            note=None,
        )

    metrics = await metrics_service.recalculate_instrument_metrics(
        async_db_session, user.id, instrument.id
    )
    assert metrics.net_position == Decimal("0.00697345")
    assert metrics.total_base_in == Decimal("2.61387345")
    assert metrics.total_base_out == Decimal("2.6069")
    assert metrics.avg_entry_price == Decimal("3111.57853659")
    assert metrics.realized_pnl == Decimal("207.37233735")
