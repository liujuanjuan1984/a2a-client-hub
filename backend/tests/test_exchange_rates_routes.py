from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.api.routers.finance_exchange_rates import router as exchange_router
from app.handlers import finance_exchange_rates as exchange_service
from app.handlers import finance_trading as trading_service
from backend.tests.api_utils import create_test_client
from backend.tests.conftest import _truncate_all_tables
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(scope="module")
def exchange_test_user(async_session_maker, async_engine):
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


async def test_create_and_query_exchange_rate(exchange_test_user, async_session_maker):
    user = exchange_test_user
    captured = datetime(2025, 1, 1, tzinfo=timezone.utc)

    async with create_test_client(
        exchange_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_resp = await client.post(
            "/finance/exchange-rates",
            json={
                "base_asset": "BTC",
                "quote_asset": "USDT",
                "rate": "42000",
                "source": "manual",
                "captured_at": captured.isoformat(),
            },
        )
        assert create_resp.status_code == 201

        query_resp = await client.get(
            "/finance/exchange-rates",
            params={"base": "BTC", "quote": "USDT"},
        )
        assert query_resp.status_code == 200
        payload = query_resp.json()
        assert payload["pairs"][0]["rate"] == "42000"


async def test_query_multiple_pairs_requires_existing_rate(
    exchange_test_user, async_session_maker
):
    user = exchange_test_user
    async with async_session_maker() as async_session:
        await exchange_service.create_exchange_rate(
            async_session,
            user.id,
            plan_id=None,
            base_asset="BTC",
            quote_asset="USDT",
            rate=Decimal("30000"),
            source="binance",
            captured_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        )
        await exchange_service.create_exchange_rate(
            async_session,
            None,
            plan_id=None,
            base_asset="USDT",
            quote_asset="USD",
            rate=Decimal("1"),
            source="manual",
            captured_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        )

    async with create_test_client(
        exchange_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.get(
            "/finance/exchange-rates",
            params={"pairs": ["BTC/USDT", "USDT/USD"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["pairs"]) == 2


async def test_query_missing_pair_returns_404(exchange_test_user, async_session_maker):
    user = exchange_test_user
    async with create_test_client(
        exchange_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.get(
            "/finance/exchange-rates",
            params={"base": "ETH", "quote": "USD"},
        )
    assert resp.status_code == 404


async def test_latest_snapshot_rates_missing_currency_returns_400(
    exchange_test_user, async_session_maker
):
    user = exchange_test_user
    async with create_test_client(
        exchange_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.get(
            "/finance/exchange-rates/latest",
            params={"scope": "snapshot", "currencies": "USD,EUR"},
        )
        assert resp.status_code == 400
        assert "缺少汇率" in resp.json()["detail"]


async def test_plan_scoped_rate_precedence(exchange_test_user, async_session_maker):
    user = exchange_test_user
    async with async_session_maker() as async_session:
        plan = await trading_service.create_trading_plan(
            async_session,
            user.id,
            name="Plan A",
            period_start=None,
            period_end=None,
            target_roi=None,
            note=None,
            status="draft",
        )
        plan_id = plan.id
        captured = datetime(2025, 4, 1, tzinfo=timezone.utc)
        await exchange_service.create_exchange_rate(
            async_session,
            user.id,
            plan_id=plan_id,
            base_asset="BTC",
            quote_asset="USDT",
            rate=Decimal("41000"),
            source="plan",
            captured_at=captured,
        )
        await exchange_service.create_exchange_rate(
            async_session,
            user.id,
            plan_id=None,
            base_asset="BTC",
            quote_asset="USDT",
            rate=Decimal("42000"),
            source="user",
            captured_at=captured,
        )

    async with create_test_client(
        exchange_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        scoped = await client.get(
            "/finance/exchange-rates",
            params={"base": "BTC", "quote": "USDT", "plan_id": str(plan.id)},
        )
        assert scoped.status_code == 200
        assert scoped.json()["pairs"][0]["rate"] == "41000"

        fallback = await client.get(
            "/finance/exchange-rates",
            params={"base": "BTC", "quote": "USDT"},
        )
        assert fallback.status_code == 200
        assert fallback.json()["pairs"][0]["rate"] == "42000"
