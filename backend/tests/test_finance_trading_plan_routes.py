from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.api.routers.finance_exchange_rates import router as exchange_router
from app.api.routers.finance_trading_plans import router as trading_router
from app.handlers import finance_exchange_rates as exchange_service
from app.handlers import finance_trading as trading_service
from backend.tests.api_utils import create_test_client
from backend.tests.conftest import _truncate_all_tables
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(scope="module")
def trading_plan_user(async_session_maker, async_engine):
    async def _setup():
        async with async_session_maker() as session:
            user = await create_user(session, skip_onboarding_defaults=True)
            await session.commit()
            await session.refresh(user)
            session.expunge(user)
            return user

    user = asyncio.run(_setup())

    try:
        yield user
    finally:
        asyncio.run(_truncate_all_tables(async_engine))


async def test_plan_routes_flow(trading_plan_user, async_session_maker):
    user = trading_plan_user

    async with create_test_client(
        trading_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_response = await client.post(
            "/finance/trading-plans",
            json={
                "name": "Router Plan",
                "period_start": "2025-01-01T00:00:00Z",
                "period_end": "2025-02-01T00:00:00Z",
                "target_roi": "0.1200",
                "note": "swing",
            },
        )
        assert create_response.status_code == 201
        plan_payload = create_response.json()
        assert plan_payload["name"] == "Router Plan"
        plan_id = plan_payload["id"]

        list_response = await client.get("/finance/trading-plans")
        assert list_response.status_code == 200
        data = list_response.json()
        assert data["pagination"]["total"] == 1
        assert data["items"][0]["status"] == "draft"

        # Clean up so later tests don't see leftover draft plan
        archive_resp = await client.post(f"/finance/trading-plans/{plan_id}/archive")
        assert archive_resp.status_code == 200


async def test_instrument_routes_flow(trading_plan_user, async_session_maker):
    user = trading_plan_user
    async with async_session_maker() as async_session:
        plan = await trading_service.create_trading_plan(
            async_session,
            user.id,
            name="Instrument Plan",
            period_start=None,
            period_end=None,
            target_roi=None,
            note=None,
            status="draft",
        )
    plan_id = plan.id

    async with create_test_client(
        trading_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_resp = await client.post(
            f"/finance/trading-plans/{plan_id}/instruments",
            json={
                "symbol": "btc/usdt",
                "exchange": "Binance",
                "strategy_tag": "scalping",
            },
        )
        assert create_resp.status_code == 201
        instrument_id = create_resp.json()["id"]

        list_resp = await client.get(f"/finance/trading-plans/{plan_id}/instruments")
        assert list_resp.status_code == 200
        instruments = list_resp.json()
        assert instruments["pagination"]["total"] == 1
        assert instruments["items"][0]["symbol"] == "BTC/USDT"

        update_resp = await client.patch(
            f"/finance/trading-plans/{plan_id}/instruments/{instrument_id}",
            json={"note": "core"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["note"] == "core"

        delete_resp = await client.delete(
            f"/finance/trading-plans/{plan_id}/instruments/{instrument_id}"
        )
        assert delete_resp.status_code == 204

        post_delete_list = await client.get(
            f"/finance/trading-plans/{plan_id}/instruments"
        )
        assert post_delete_list.status_code == 200
        assert post_delete_list.json()["pagination"]["total"] == 0

    async with async_session_maker() as cleanup_session:
        await trading_service.archive_trading_plan(
            cleanup_session,
            user.id,
            plan_id,
        )


async def test_entry_routes_flow(trading_plan_user, async_session_maker):
    user = trading_plan_user
    async with async_session_maker() as async_session:
        plan = await trading_service.create_trading_plan(
            async_session,
            user.id,
            name="Entry Plan",
            period_start=None,
            period_end=None,
            target_roi=None,
            note=None,
            status="draft",
        )
        instrument = await trading_service.create_trading_instrument(
            async_session,
            user.id,
            plan_id=plan.id,
            symbol="ETH/USDT",
            base_asset="ETH",
            quote_asset="USDT",
            exchange=None,
            strategy_tag=None,
            note=None,
        )
    plan_id = plan.id
    instrument_id = instrument.id

    trade_time = datetime(2025, 3, 3, 15, tzinfo=timezone.utc).isoformat()

    async with create_test_client(
        trading_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        payload = {
            "plan_id": str(plan_id),
            "instrument_id": str(instrument_id),
            "trade_time": trade_time,
            "direction": "buy",
            "base_delta": "1",
            "quote_delta": "-3500",
            "price": "3500",
            "fee_asset": "USDT",
            "fee_amount": "3.5",
            "source": "manual",
            "note": "entry",
        }
        create_resp = await client.post("/finance/trading-entries", json=payload)
        assert create_resp.status_code == 201
        entry_id = create_resp.json()["id"]

        list_resp = await client.get(
            "/finance/trading-entries",
            params={"plan_id": str(plan_id)},
        )
        assert list_resp.status_code == 200
        listing = list_resp.json()
        assert listing["pagination"]["total"] == 1

        update_resp = await client.put(
            f"/finance/trading-entries/{entry_id}",
            json={"note": "updated"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["note"] == "updated"

        delete_resp = await client.delete(f"/finance/trading-entries/{entry_id}")
        assert delete_resp.status_code == 204

        empty_resp = await client.get(
            "/finance/trading-entries",
            params={"plan_id": str(plan_id)},
        )
        assert empty_resp.json()["pagination"]["total"] == 0

    async with async_session_maker() as cleanup_session:
        await trading_service.archive_trading_plan(
            cleanup_session,
            user.id,
            plan_id,
        )


async def test_plan_summary_endpoint(trading_plan_user, async_session_maker):
    user = trading_plan_user
    async with async_session_maker() as async_session:
        plan = await trading_service.create_trading_plan(
            async_session,
            user.id,
            name="Summary",
            period_start=None,
            period_end=None,
            target_roi=None,
            note=None,
            status="active",
        )
        instrument = await trading_service.create_trading_instrument(
            async_session,
            user.id,
            plan_id=plan.id,
            symbol="ETH/USDT",
            base_asset="ETH",
            quote_asset="USDT",
            exchange=None,
            strategy_tag=None,
            note=None,
        )
        await exchange_service.create_exchange_rate(
            async_session,
            user.id,
            plan_id=None,
            base_asset="ETH",
            quote_asset="USDT",
            rate=Decimal("2000"),
            source="manual",
            captured_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
        )
        await exchange_service.create_exchange_rate(
            async_session,
            None,
            plan_id=None,
            base_asset="USDT",
            quote_asset="USD",
            rate=Decimal("1"),
            source="manual",
            captured_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
        )
        await trading_service.create_trading_entry(
            async_session,
            user.id,
            plan_id=plan.id,
            instrument_id=instrument.id,
            trade_time=datetime(2025, 3, 10, tzinfo=timezone.utc),
            direction="buy",
            base_delta=Decimal("2"),
            quote_delta=Decimal("-4000"),
            price=Decimal("2000"),
            fee_asset="USDT",
            fee_amount=Decimal("5"),
            source="manual",
            note=None,
        )
        await trading_service.create_trading_entry(
            async_session,
            user.id,
            plan_id=plan.id,
            instrument_id=instrument.id,
            trade_time=datetime(2025, 3, 12, tzinfo=timezone.utc),
            direction="sell",
            base_delta=Decimal("-1"),
            quote_delta=Decimal("2100"),
            price=Decimal("2100"),
            fee_asset="USDT",
            fee_amount=Decimal("3"),
            source="manual",
            note=None,
        )
    plan_id = plan.id

    async with create_test_client(
        trading_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        refresh_resp = await client.post(
            f"/finance/trading-plans/{plan_id}/rate-snapshot"
        )
        assert refresh_resp.status_code == 200
        resp = await client.get(f"/finance/trading-plans/{plan_id}/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totals"]["total_investment"] is not None
        assert len(data["instruments"]) == 1
        instrument_payload = data["instruments"][0]
        assert instrument_payload["symbol"] == "ETH/USDT"
        assert instrument_payload["net_position"] == "1"
        assert instrument_payload["net_position_quote"] == "-1900"
        assert instrument_payload["market_value_primary_base"] == "2000"
        assert instrument_payload["market_value_primary_quote"] == "-1900"
        assert instrument_payload["market_value_primary"] == "100"
        assert data["rates_updated_at"] is not None
        rates = {
            (item["base_asset"], item["quote_asset"]): item
            for item in data["rates_used"]
        }
        assert ("ETH", "USDT") in rates
        assert rates[("ETH", "USDT")]["rate"] == "2000"
        assert ("USDT", "USD") in rates
        assert rates[("USDT", "USD")]["rate"] == "1"

    async with async_session_maker() as cleanup_session:
        await trading_service.archive_trading_plan(
            cleanup_session,
            user.id,
            plan_id,
        )


async def test_plan_exchange_rates_listing(trading_plan_user, async_session_maker):
    user = trading_plan_user
    async with async_session_maker() as async_session:
        plan = await trading_service.create_trading_plan(
            async_session,
            user.id,
            name="FX Plan",
            period_start=None,
            period_end=None,
            target_roi=None,
            note=None,
            status="active",
        )
    plan_id = plan.id

    async with create_test_client(
        exchange_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        payload = {
            "plan_id": str(plan_id),
            "base_asset": "USDT",
            "quote_asset": "CNY",
            "rate": "7.10",
            "captured_at": "2025-03-01T00:00:00Z",
            "source": "manual",
        }
        create_resp = await client.post("/finance/exchange-rates", json=payload)
        assert create_resp.status_code == 201

        list_resp = await client.get(f"/finance/exchange-rates/plans/{plan_id}")
        assert list_resp.status_code == 200
        records = list_resp.json()["items"]
        assert len(records) == 1
        assert records[0]["base_asset"] == "USDT"
        assert records[0]["quote_asset"] == "CNY"
        assert records[0]["rate"] == "7.1"

    async with async_session_maker() as cleanup_session:
        await trading_service.archive_trading_plan(
            cleanup_session,
            user.id,
            plan_id,
        )
