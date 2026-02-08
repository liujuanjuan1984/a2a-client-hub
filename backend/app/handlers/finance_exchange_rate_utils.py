"""Shared helpers for finance exchange rate handling."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Tuple

from app.handlers.finance_common import (
    EIGHT_PLACES,
    DuplicateExchangeRateError,
    MissingExchangeRateError,
)


def normalize_currency_code(value: str) -> str:
    text = value.strip().upper()
    if not text:
        raise ValueError("currency code must not be empty")
    return text


def build_exchange_rate_map(
    rates: Iterable[Tuple[str, Decimal]],
) -> Dict[str, Decimal]:
    result: Dict[str, Decimal] = {}
    for currency, rate in rates:
        cur = normalize_currency_code(currency)
        if cur in result:
            raise DuplicateExchangeRateError(f"重复的汇率：{cur}")
        normalized = rate.quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)
        result[cur] = normalized
    return result


def ensure_rates_for_currencies(
    *,
    primary_currency: str,
    currencies: Iterable[str],
    rate_map: Dict[str, Decimal],
) -> None:
    primary = normalize_currency_code(primary_currency)
    missing: List[str] = []
    for currency in currencies:
        cur = normalize_currency_code(currency)
        if cur == primary:
            continue
        if cur not in rate_map:
            missing.append(cur)
    if missing:
        missing_pairs = ", ".join(f"{cur}/{primary}" for cur in sorted(set(missing)))
        raise MissingExchangeRateError(f"缺少汇率：{missing_pairs}")


__all__ = [
    "build_exchange_rate_map",
    "ensure_rates_for_currencies",
    "normalize_currency_code",
]
