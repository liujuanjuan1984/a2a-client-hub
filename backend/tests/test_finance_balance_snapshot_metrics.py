from decimal import Decimal
from uuid import uuid4

from app.db.models.finance_accounts import FinanceAccount
from app.handlers.finance_balance_snapshots import _calculate_snapshot_state


def _account(name: str, account_type: str, currency: str = "USD") -> FinanceAccount:
    return FinanceAccount(
        user_id=uuid4(),
        name=name,
        path=f"/{name}",
        depth=0,
        type=account_type,
        currency_code=currency,
    )


def test_snapshot_metrics_split_positive_and_negative_totals() -> None:
    asset = _account("Asset", "asset")
    liability = _account("Liability", "liability")

    accounts_payload = [
        (asset, Decimal("1000.00"), None),
        (liability, Decimal("-200.00"), None),
    ]

    _, summary, _ = _calculate_snapshot_state(
        primary_currency="USD",
        rates={},
        accounts_payload=accounts_payload,
    )

    assert summary["total_assets"] == 1000.0
    assert summary["total_liabilities"] == -200.0
    assert summary["net_worth"] == 800.0
