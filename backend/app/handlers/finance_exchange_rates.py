"""Exchange rate handlers for trading subsystem (async-only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, Iterable, Optional, Tuple
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.finance_trading import ExchangeRate
from app.db.transaction import commit_safely
from app.handlers.finance_common import FinanceError
from app.utils.timezone_util import utc_now


class ExchangeRateError(FinanceError):
    """Base class for exchange rate errors."""


class ExchangeRateNotFoundError(ExchangeRateError):
    """Raised when a requested rate cannot be located."""


@dataclass
class ExchangeRateUsageRecord:
    base_asset: str
    quote_asset: str
    rate: Decimal
    source: Optional[str]
    captured_at: Optional[datetime]
    plan_id: Optional[UUID]
    user_id: Optional[UUID]
    derived: bool
    record_id: Optional[UUID]


def _normalize_asset(value: str) -> str:
    text = value.strip().upper()
    if not text:
        raise ValueError("Asset symbol cannot be empty")
    return text


def _build_lookup_order(
    plan_id: Optional[UUID], user_id: Optional[UUID]
) -> list[Tuple[Optional[UUID], Optional[UUID]]]:
    order: list[Tuple[Optional[UUID], Optional[UUID]]] = []
    if plan_id is not None:
        order.append((plan_id, user_id))
        order.append((plan_id, None))
    order.append((None, user_id))
    order.append((None, None))
    seen: set[Tuple[Optional[UUID], Optional[UUID]]] = set()
    deduped: list[Tuple[Optional[UUID], Optional[UUID]]] = []
    for item in order:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


async def _query_rate(
    db: AsyncSession,
    user_id: Optional[UUID],
    plan_id: Optional[UUID],
    base_asset: str,
    quote_asset: str,
    effective_at: datetime,
) -> Optional[ExchangeRate]:
    stmt = (
        select(ExchangeRate)
        .where(
            ExchangeRate.base_asset == base_asset,
            ExchangeRate.quote_asset == quote_asset,
            ExchangeRate.captured_at <= effective_at,
        )
        .order_by(desc(ExchangeRate.captured_at))
        .limit(1)
    )
    if user_id is None:
        stmt = stmt.where(ExchangeRate.user_id.is_(None))
    else:
        stmt = stmt.where(ExchangeRate.user_id == user_id)
    if plan_id is None:
        stmt = stmt.where(ExchangeRate.plan_id.is_(None))
    else:
        stmt = stmt.where(ExchangeRate.plan_id == plan_id)
    return (await db.execute(stmt)).scalars().first()


async def _resolve_rate_record(
    db: AsyncSession,
    base_asset: str,
    quote_asset: str,
    effective_at: datetime,
    *,
    plan_id: Optional[UUID],
    user_id: Optional[UUID],
) -> Optional[ExchangeRate]:
    for plan_scope, user_scope in _build_lookup_order(plan_id, user_id):
        record = await _query_rate(
            db,
            user_scope,
            plan_scope,
            base_asset,
            quote_asset,
            effective_at,
        )
        if record is not None:
            return record
    return None


async def create_exchange_rate(
    db: AsyncSession,
    user_id: Optional[UUID],
    *,
    plan_id: Optional[UUID],
    base_asset: str,
    quote_asset: str,
    rate: Decimal,
    source: Optional[str],
    captured_at: datetime,
) -> ExchangeRate:
    record = ExchangeRate(
        user_id=user_id,
        plan_id=plan_id,
        base_asset=_normalize_asset(base_asset),
        quote_asset=_normalize_asset(quote_asset),
        rate=rate,
        source=(source or "manual").strip(),
        captured_at=captured_at,
    )
    db.add(record)
    await commit_safely(db)
    await db.refresh(record)
    return record


async def query_exchange_rates(
    db: AsyncSession,
    user_id: Optional[UUID],
    *,
    pairs: Iterable[Tuple[str, str]],
    effective_at: Optional[datetime] = None,
    plan_id: Optional[UUID] = None,
) -> Dict[Tuple[str, str], Tuple[Decimal, Optional[str], Optional[datetime]]]:
    results: Dict[
        Tuple[str, str], Tuple[Decimal, Optional[str], Optional[datetime]]
    ] = {}
    timestamp = effective_at or utc_now()
    for base_asset, quote_asset in pairs:
        base = _normalize_asset(base_asset)
        quote = _normalize_asset(quote_asset)
        if base == quote:
            results[(base, quote)] = (Decimal("1"), None, timestamp)
            continue
        record = await _resolve_rate_record(
            db,
            base,
            quote,
            timestamp,
            plan_id=plan_id,
            user_id=user_id,
        )
        if record is None:
            inverse = await _resolve_rate_record(
                db,
                quote,
                base,
                timestamp,
                plan_id=plan_id,
                user_id=user_id,
            )
            if inverse is None:
                raise ExchangeRateNotFoundError(
                    f"Missing exchange rate for {base}/{quote}"
                )
            rate_value = Decimal("1") / inverse.rate
            source = inverse.source
            captured_at = inverse.captured_at
        else:
            rate_value = record.rate
            source = record.source
            captured_at = record.captured_at
        results[(base, quote)] = (rate_value, source, captured_at)
    return results


class ExchangeRateResolver:
    """Utility that caches rate lookups for bulk conversions."""

    def __init__(
        self,
        db: AsyncSession,
        user_id: Optional[UUID],
        *,
        effective_at: Optional[datetime] = None,
        plan_id: Optional[UUID] = None,
    ) -> None:
        self._db = db
        self._user_id = user_id
        self._effective_at = effective_at or utc_now()
        self._plan_id = plan_id
        self._cache: Dict[Tuple[str, str], Decimal] = {}
        self._usage: Dict[Tuple[str, str], ExchangeRateUsageRecord] = {}

    def _record_usage(
        self,
        base: str,
        quote: str,
        rate: Decimal,
        record: Optional[ExchangeRate],
        *,
        derived: bool,
    ) -> None:
        self._usage[(base, quote)] = ExchangeRateUsageRecord(
            base_asset=base,
            quote_asset=quote,
            rate=rate,
            source=getattr(record, "source", None) if record else None,
            captured_at=getattr(record, "captured_at", None) if record else None,
            plan_id=getattr(record, "plan_id", None) if record else None,
            user_id=getattr(record, "user_id", None) if record else None,
            derived=derived,
            record_id=getattr(record, "id", None) if record else None,
        )

    async def get_rate(self, base_asset: str, quote_asset: str) -> Decimal:
        base = _normalize_asset(base_asset)
        quote = _normalize_asset(quote_asset)
        key = (base, quote)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        if base == quote:
            rate_identity = Decimal("1")
            self._cache[key] = rate_identity
            self._record_usage(base, quote, rate_identity, None, derived=False)
            return rate_identity

        record = await _resolve_rate_record(
            self._db,
            base,
            quote,
            self._effective_at,
            plan_id=self._plan_id,
            user_id=self._user_id,
        )
        derived = False
        if record is None:
            inverse = await _resolve_rate_record(
                self._db,
                quote,
                base,
                self._effective_at,
                plan_id=self._plan_id,
                user_id=self._user_id,
            )
            if inverse is None:
                raise ExchangeRateNotFoundError(
                    f"Missing exchange rate for {base}/{quote}"
                )
            rate = Decimal("1") / inverse.rate
            record = inverse
            derived = True
        else:
            rate = record.rate

        self._cache[key] = rate
        self._record_usage(base, quote, rate, record, derived=derived)
        return rate

    async def convert(
        self, amount: Decimal, base_asset: str, quote_asset: str
    ) -> Decimal:
        rate = await self.get_rate(base_asset, quote_asset)
        return amount * rate

    async def bulk_pairs(
        self, pairs: Iterable[Tuple[str, str]]
    ) -> Dict[Tuple[str, str], Decimal]:
        result: Dict[Tuple[str, str], Decimal] = {}
        for base, quote in pairs:
            result[(base, quote)] = await self.get_rate(base, quote)
        return result

    def get_usage_records(self) -> list[ExchangeRateUsageRecord]:
        return list(self._usage.values())


__all__ = [
    "ExchangeRateError",
    "ExchangeRateNotFoundError",
    "ExchangeRateResolver",
    "create_exchange_rate",
    "query_exchange_rates",
]
