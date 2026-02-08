"""Shared helpers for finance rate snapshots."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Iterable, Literal
from uuid import UUID

from app.handlers import finance_exchange_rates as exchange_service
from app.handlers.finance_common import MissingExchangeRateError, to_json_number
from app.handlers.finance_exchange_rate_utils import normalize_currency_code
from app.utils.timezone_util import utc_now


def _format_missing_pairs(missing: Iterable[str], primary: str) -> str:
    pairs = ", ".join(f"{currency}/{primary}" for currency in sorted(set(missing)))
    return f"缺少汇率：{pairs}"


async def collect_rates_to_primary(
    resolver: exchange_service.ExchangeRateResolver,
    *,
    primary_currency: str,
    currencies: Iterable[str],
) -> dict[str, Decimal]:
    primary = normalize_currency_code(primary_currency)
    required = {
        normalize_currency_code(currency) for currency in currencies if currency
    }
    missing: list[str] = []
    rate_map: dict[str, Decimal] = {}
    for currency in sorted(required):
        if currency == primary:
            continue
        try:
            rate_map[currency] = await resolver.get_rate(currency, primary)
        except exchange_service.ExchangeRateNotFoundError:
            missing.append(currency)
    if missing:
        raise MissingExchangeRateError(_format_missing_pairs(missing, primary))
    return rate_map


def build_rate_usage_payload(
    usage: exchange_service.ExchangeRateUsageRecord,
    *,
    user_id: UUID,
) -> dict[str, object]:
    if usage.plan_id is not None:
        scope: Literal["plan", "user", "global", "synthetic"] = "plan"
    elif usage.user_id == user_id:
        scope = "user"
    elif usage.user_id is None:
        scope = "global"
    else:
        scope = "synthetic"
    return {
        "base_asset": usage.base_asset,
        "quote_asset": usage.quote_asset,
        "rate": to_json_number(usage.rate),
        "scope": scope,
        "derived": usage.derived,
        "source": usage.source,
        "captured_at": usage.captured_at.isoformat() if usage.captured_at else None,
    }


def build_rate_usage_payloads(
    resolver: exchange_service.ExchangeRateResolver,
    *,
    user_id: UUID,
) -> list[dict[str, object]]:
    return [
        build_rate_usage_payload(record, user_id=user_id)
        for record in resolver.get_usage_records()
        if record.base_asset != record.quote_asset
    ]


async def build_rate_snapshot_map(
    db,
    *,
    user_id: UUID,
    primary_currency: str,
    currencies: Iterable[str],
    effective_at: datetime | None = None,
    plan_id: UUID | None = None,
) -> tuple[str, dict[str, Decimal], list[dict[str, object]], datetime]:
    effective_timestamp = effective_at or utc_now()
    resolver = exchange_service.ExchangeRateResolver(
        db,
        user_id,
        effective_at=effective_timestamp,
        plan_id=plan_id,
    )
    rate_map = await collect_rates_to_primary(
        resolver,
        primary_currency=primary_currency,
        currencies=currencies,
    )
    usage_payloads = build_rate_usage_payloads(resolver, user_id=user_id)
    normalized_primary = normalize_currency_code(primary_currency)
    return normalized_primary, rate_map, usage_payloads, effective_timestamp


__all__ = [
    "build_rate_snapshot_map",
    "build_rate_usage_payloads",
    "collect_rates_to_primary",
]
