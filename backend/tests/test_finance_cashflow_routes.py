from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterable

import pytest

from app.api.routers.finance_cashflow import router as cashflow_router
from app.handlers import finance_cashflow as cashflow_service
from app.handlers import finance_cashflow_trees as cashflow_tree_service
from app.handlers import finance_exchange_rates as exchange_service
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _create_billing_source(async_session_maker, user_id) -> object:
    async with async_session_maker() as async_session:
        tree = await cashflow_tree_service.ensure_default_cashflow_tree(
            async_session, user_id
        )
        return await cashflow_service.create_cashflow_source(
            async_session,
            user_id,
            tree_id=tree.id,
            name="Monthly Subscription",
            parent_id=None,
            metadata=None,
            sort_order=None,
            kind="billing",
            billing_cycle_type="month",
            billing_cycle_interval=1,
            billing_anchor_day=1,
            billing_anchor_date=date(2025, 1, 1),
            billing_post_to="end",
            billing_default_amount=Decimal("99.90"),
            billing_default_note="Auto charge",
            billing_requires_manual_input=False,
        )


async def _upsert_entries(
    async_session_maker,
    user_id,
    source_id,
    month: date,
    entries: Iterable[tuple[date, date, Decimal, str | None]],
) -> None:
    async with async_session_maker() as async_session:
        await cashflow_service.upsert_billing_cycle_entries(
            async_session,
            user_id,
            source_id=source_id,
            month=month,
            entries=[
                (start, end, amount, note) for start, end, amount, note in entries
            ],
            primary_currency="USD",
        )


async def test_list_billing_cycle_history_bulk_returns_expected_entries(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    source = await _create_billing_source(async_session_maker, user.id)

    january = date(2025, 1, 1)
    february = date(2025, 2, 1)

    await _upsert_entries(
        async_session_maker,
        user.id,
        source.id,
        month=january,
        entries=[
            (date(2025, 1, 1), date(2025, 1, 31), Decimal("120.00"), "January bill"),
        ],
    )
    await _upsert_entries(
        async_session_maker,
        user.id,
        source.id,
        month=february,
        entries=[
            (date(2025, 2, 1), date(2025, 2, 28), Decimal("115.50"), "February bill"),
        ],
    )
    async with create_test_client(
        cashflow_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.get(
            f"/finance/cashflow/billing/{source.id}/history",
            params=[
                ("months", "2025-02"),
                ("months", "2025-02"),
                ("months", "2025-01"),
                ("months", "2025-03"),
            ],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_id"] == str(source.id)

    months = payload["months"]
    assert set(months.keys()) == {"2025-01", "2025-02", "2025-03"}

    january_entries = months["2025-01"]
    assert len(january_entries) == 1
    assert january_entries[0]["note"] == "January bill"
    assert Decimal(january_entries[0]["amount"]) == Decimal("120.00000000")

    february_entries = months["2025-02"]
    assert len(february_entries) == 1
    assert Decimal(february_entries[0]["amount"]) == Decimal("115.50000000")

    march_entries = months["2025-03"]
    assert march_entries, "Expected generated cycles even without entries"
    assert march_entries[0]["amount"] is None


async def test_list_billing_cycle_history_bulk_rejects_invalid_month(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    source = await _create_billing_source(async_session_maker, user.id)
    invalid_months = ["2025/01", "2025-13", ""]

    async with create_test_client(
        cashflow_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        for invalid_month in invalid_months:
            response = await client.get(
                f"/finance/cashflow/billing/{source.id}/history",
                params=[("months", invalid_month)],
            )
            assert response.status_code == 400, invalid_month


async def test_cashflow_snapshot_auto_builds_exchange_rates(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    async with async_session_maker() as async_session:
        tree = await cashflow_tree_service.ensure_default_cashflow_tree(
            async_session, user.id
        )
        source = await cashflow_service.create_cashflow_source(
            async_session,
            user.id,
            tree_id=tree.id,
            name="Salary",
            parent_id=None,
            metadata=None,
            sort_order=None,
            kind="regular",
            currency_code="EUR",
        )
        await exchange_service.create_exchange_rate(
            async_session,
            user.id,
            plan_id=None,
            base_asset="EUR",
            quote_asset="USD",
            rate=Decimal("1.20"),
            source="manual",
            captured_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
        )

    async with create_test_client(
        cashflow_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.post(
            "/finance/cashflow/snapshots",
            json={
                "period_start": "2025-01-01T00:00:00Z",
                "period_end": "2025-02-01T00:00:00Z",
                "entries": [{"id": str(source.id), "amount": "100", "note": "Jan"}],
                "exchange_rates": [],
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["primary_currency"] == "USD"
    assert any(
        rate["quote_currency"] == "EUR" and Decimal(rate["rate"]) == Decimal("1.2")
        for rate in payload.get("exchange_rates", [])
    )
