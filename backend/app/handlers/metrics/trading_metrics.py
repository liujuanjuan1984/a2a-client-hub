"""Async trading metrics helpers."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.finance_trading import (
    TradingEntry,
    TradingInstrument,
    TradingInstrumentMetric,
    TradingPlan,
)
from app.db.transaction import commit_safely
from app.handlers import finance_exchange_rates as exchange_service
from app.handlers.finance_common import (
    MissingExchangeRateError,
    RateSnapshotNotReadyError,
    from_json_number,
)
from app.handlers.finance_exchange_rate_utils import normalize_currency_code
from app.handlers.finance_exchange_rates import (
    ExchangeRateNotFoundError,
    ExchangeRateResolver,
)
from app.handlers.finance_rate_snapshots import (
    build_rate_usage_payloads,
    collect_rates_to_primary,
)
from app.schemas.finance_trading import (
    TradingInstrumentSummary,
    TradingPlanExchangeRateUsage,
    TradingPlanSummaryResponse,
    TradingPlanSummaryTotals,
)
from app.utils.timezone_util import utc_now

AMOUNT_PLACES = Decimal("0.00000001")


class SnapshotRateResolver:
    def __init__(self, rate_map: dict[tuple[str, str], Decimal]) -> None:
        self._rate_map = rate_map

    async def get_rate(self, base: str, quote: str) -> Decimal:
        base_asset = normalize_currency_code(base)
        quote_asset = normalize_currency_code(quote)
        if base_asset == quote_asset:
            return Decimal("1")
        key = (base_asset, quote_asset)
        if key not in self._rate_map:
            raise ExchangeRateNotFoundError(
                f"Missing exchange rate for {base_asset}/{quote_asset}"
            )
        return self._rate_map[key]

    async def convert(self, amount: Decimal, base: str, quote: str) -> Decimal:
        if normalize_currency_code(base) == normalize_currency_code(quote):
            return amount
        rate = await self.get_rate(base, quote)
        return amount * rate


def _parse_snapshot_rates(
    payloads: list[dict[str, object]],
) -> tuple[dict[tuple[str, str], Decimal], list[TradingPlanExchangeRateUsage]]:
    rate_map: dict[tuple[str, str], Decimal] = {}
    usages: list[TradingPlanExchangeRateUsage] = []
    for payload in payloads:
        base_asset = normalize_currency_code(str(payload.get("base_asset", "")))
        quote_asset = normalize_currency_code(str(payload.get("quote_asset", "")))
        rate = from_json_number(payload.get("rate"))
        rate_map[(base_asset, quote_asset)] = rate
        captured_at_raw = payload.get("captured_at")
        if isinstance(captured_at_raw, datetime):
            captured_at = captured_at_raw
        elif isinstance(captured_at_raw, str) and captured_at_raw:
            captured_at = datetime.fromisoformat(captured_at_raw)
        else:
            captured_at = None
        usages.append(
            TradingPlanExchangeRateUsage(
                base_asset=base_asset,
                quote_asset=quote_asset,
                rate=rate,
                scope=payload.get("scope", "global"),
                derived=bool(payload.get("derived", False)),
                source=payload.get("source"),
                captured_at=captured_at,
            )
        )
    return rate_map, usages


async def build_trading_plan_rate_snapshot(
    db: AsyncSession,
    user_id: UUID,
    plan_id: UUID,
    *,
    primary_currency: str,
    effective_at: Optional[datetime] = None,
) -> tuple[str, list[dict[str, object]]]:
    plan = await _load_plan(db, user_id, plan_id)
    instruments = await _load_plan_instruments(db, user_id, plan.id)
    primary = normalize_currency_code(primary_currency)
    effective_timestamp = effective_at or utc_now()

    resolver = ExchangeRateResolver(
        db,
        user_id,
        effective_at=effective_timestamp,
        plan_id=plan.id,
    )
    required_quotes = {
        normalize_currency_code(instrument.quote_asset)
        for instrument in instruments
        if instrument.quote_asset
    }
    await collect_rates_to_primary(
        resolver,
        primary_currency=primary,
        currencies=required_quotes,
    )

    for instrument in instruments:
        base_asset = normalize_currency_code(instrument.base_asset)
        quote_asset = normalize_currency_code(instrument.quote_asset)
        if base_asset == quote_asset:
            continue
        try:
            await resolver.get_rate(base_asset, quote_asset)
        except ExchangeRateNotFoundError:
            continue

    payloads = build_rate_usage_payloads(resolver, user_id=user_id)
    return primary, payloads


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(AMOUNT_PLACES)


async def _fetch_instrument(
    db: AsyncSession,
    user_id: UUID,
    instrument_id: UUID,
) -> TradingInstrument:
    stmt = (
        select(TradingInstrument)
        .where(
            TradingInstrument.id == instrument_id,
            TradingInstrument.user_id == user_id,
            TradingInstrument.deleted_at.is_(None),
        )
        .limit(1)
    )
    instrument = (await db.execute(stmt)).scalars().first()
    if not instrument:
        from app.handlers.finance_trading import TradingInstrumentNotFoundError

        raise TradingInstrumentNotFoundError("Trading instrument not found")
    return instrument


async def _load_entries(
    db: AsyncSession,
    user_id: UUID,
    instrument_id: UUID,
) -> list[TradingEntry]:
    stmt = (
        select(TradingEntry)
        .where(
            TradingEntry.instrument_id == instrument_id,
            TradingEntry.user_id == user_id,
            TradingEntry.deleted_at.is_(None),
        )
        .order_by(TradingEntry.trade_time.asc(), TradingEntry.created_at.asc())
    )
    return (await db.execute(stmt)).scalars().all()


async def recalculate_instrument_metrics(
    db: AsyncSession,
    user_id: UUID,
    instrument_id: UUID,
) -> TradingInstrumentMetric:
    instrument = await _fetch_instrument(db, user_id, instrument_id)
    entries = await _load_entries(db, user_id, instrument_id)

    total_in = Decimal("0")
    total_out = Decimal("0")
    position = Decimal("0")
    cost_basis = Decimal("0")
    realized = Decimal("0")

    for entry in entries:
        qty = Decimal(entry.base_delta or 0)
        quote_delta = Decimal(entry.quote_delta or 0)
        fee = Decimal(entry.fee_amount or 0)
        fee_in_quote = (
            fee
            if entry.fee_asset
            and entry.fee_asset.upper() == instrument.quote_asset.upper()
            else Decimal("0")
        )

        if qty > 0:
            total_in += qty
            total_cost = (-quote_delta) + fee_in_quote if qty != 0 else Decimal("0")
            qty_remaining = qty
            cost_remaining = total_cost
            while qty_remaining > 0 and position < 0:
                short_size = -position
                cover_qty = min(qty_remaining, short_size)
                unit_cost = (
                    cost_remaining / qty_remaining if qty_remaining else Decimal("0")
                )
                cover_cost = unit_cost * cover_qty
                unit_proceeds = cost_basis / short_size if short_size else Decimal("0")
                cost_portion = unit_proceeds * cover_qty
                realized += cost_portion - cover_cost
                cost_basis -= cost_portion
                position += cover_qty
                qty_remaining -= cover_qty
                cost_remaining -= cover_cost
                if position == Decimal("0"):
                    cost_basis = Decimal("0")
            if qty_remaining > 0:
                position += qty_remaining
                cost_basis += cost_remaining
        elif qty < 0:
            qty_abs = -qty
            total_out += qty_abs
            proceeds = quote_delta - fee_in_quote
            qty_remaining = qty_abs
            proceeds_remaining = proceeds
            while qty_remaining > 0 and position > 0:
                long_size = position
                close_qty = min(qty_remaining, long_size)
                unit_proceeds = (
                    proceeds_remaining / qty_remaining
                    if qty_remaining
                    else Decimal("0")
                )
                proceeds_portion = unit_proceeds * close_qty
                unit_cost = cost_basis / long_size if long_size else Decimal("0")
                cost_portion = unit_cost * close_qty
                realized += proceeds_portion - cost_portion
                cost_basis -= cost_portion
                position -= close_qty
                qty_remaining -= close_qty
                proceeds_remaining -= proceeds_portion
                if position == Decimal("0"):
                    cost_basis = Decimal("0")
            if qty_remaining > 0:
                position -= qty_remaining
                cost_basis += proceeds_remaining

    stmt = (
        select(TradingInstrumentMetric)
        .where(
            TradingInstrumentMetric.instrument_id == instrument_id,
            TradingInstrumentMetric.user_id == user_id,
        )
        .limit(1)
    )
    metrics = (await db.execute(stmt)).scalars().first()
    if not metrics:
        metrics = TradingInstrumentMetric(
            user_id=user_id,
            plan_id=instrument.plan_id,
            instrument_id=instrument.id,
        )
        db.add(metrics)

    metrics.total_base_in = _quantize(total_in)
    metrics.total_base_out = _quantize(total_out)
    metrics.net_position = _quantize(position)
    if position > 0:
        metrics.avg_entry_price = (cost_basis / position).quantize(AMOUNT_PLACES)
    elif position < 0:
        metrics.avg_entry_price = (cost_basis / (-position)).quantize(AMOUNT_PLACES)
    else:
        metrics.avg_entry_price = None
    metrics.realized_pnl = realized.quantize(AMOUNT_PLACES)
    metrics.unrealized_pnl = Decimal("0")

    await commit_safely(db)
    await db.refresh(metrics)
    return metrics


async def _load_plan(
    db: AsyncSession,
    user_id: UUID,
    plan_id: UUID,
    *,
    for_update: bool = False,
) -> TradingPlan:
    stmt = (
        select(TradingPlan)
        .where(
            TradingPlan.id == plan_id,
            TradingPlan.user_id == user_id,
            TradingPlan.deleted_at.is_(None),
        )
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    plan = (await db.execute(stmt)).scalars().first()
    if not plan:
        from app.handlers.finance_trading import TradingPlanNotFoundError

        raise TradingPlanNotFoundError("Trading plan not found")
    return plan


async def _load_plan_instruments(
    db: AsyncSession, user_id: UUID, plan_id: UUID
) -> list[TradingInstrument]:
    stmt = (
        select(TradingInstrument)
        .where(
            TradingInstrument.plan_id == plan_id,
            TradingInstrument.user_id == user_id,
            TradingInstrument.deleted_at.is_(None),
        )
        .order_by(TradingInstrument.created_at.asc())
    )
    return (await db.execute(stmt)).scalars().all()


async def _load_quote_balances(
    db: AsyncSession, user_id: UUID, plan_id: UUID
) -> dict[UUID, Decimal]:
    stmt = (
        select(
            TradingEntry.instrument_id,
            func.coalesce(func.sum(TradingEntry.quote_delta), 0),
        )
        .where(
            TradingEntry.plan_id == plan_id,
            TradingEntry.user_id == user_id,
            TradingEntry.deleted_at.is_(None),
        )
        .group_by(TradingEntry.instrument_id)
    )
    rows = await db.execute(stmt)
    return {instrument_id: Decimal(total or 0) for instrument_id, total in rows.all()}


async def get_trading_plan_summary(
    db: AsyncSession,
    user_id: UUID,
    plan_id: UUID,
    *,
    primary_currency: str,
    effective_at: Optional[datetime] = None,
    rate_mode: Literal["snapshot", "source"] = "snapshot",
) -> TradingPlanSummaryResponse:
    calculated_at = utc_now()
    plan = await _load_plan(db, user_id, plan_id)
    instruments = await _load_plan_instruments(db, user_id, plan.id)
    quote_balances = await _load_quote_balances(db, user_id, plan.id)

    effective_timestamp = (
        plan.rate_snapshot_ts if rate_mode == "snapshot" else effective_at
    ) or utc_now()
    primary = normalize_currency_code(primary_currency)
    required_quotes = {
        normalize_currency_code(instrument.quote_asset)
        for instrument in instruments
        if instrument.quote_asset
    }
    snapshot_usages: list[TradingPlanExchangeRateUsage] = []
    if rate_mode == "snapshot":
        if not plan.rate_snapshot_currency or plan.rate_snapshot_rates is None:
            raise RateSnapshotNotReadyError("快照口径尚未生成，请先刷新快照")
        snapshot_primary = normalize_currency_code(plan.rate_snapshot_currency)
        if primary != snapshot_primary:
            raise RateSnapshotNotReadyError(
                f"快照口径已锁定为 {snapshot_primary}，请刷新快照或切换为实时口径"
            )
        rate_map, snapshot_usages = _parse_snapshot_rates(
            list(plan.rate_snapshot_rates or [])
        )
        if required_quotes:
            missing_quotes = [
                quote
                for quote in required_quotes
                if quote != snapshot_primary
                and (quote, snapshot_primary) not in rate_map
            ]
            if missing_quotes:
                missing_pairs = ", ".join(
                    f"{quote}/{snapshot_primary}"
                    for quote in sorted(set(missing_quotes))
                )
                raise MissingExchangeRateError(f"缺少汇率：{missing_pairs}")
        resolver: SnapshotRateResolver | ExchangeRateResolver
        resolver = SnapshotRateResolver(rate_map)
        primary = snapshot_primary
        effective_timestamp = plan.rate_snapshot_ts or effective_timestamp
    else:
        if required_quotes:
            missing_quotes: list[str] = []
            for quote in required_quotes:
                if quote == primary:
                    continue
                try:
                    await exchange_service.query_exchange_rates(
                        db,
                        user_id,
                        pairs=[(quote, primary)],
                        effective_at=effective_timestamp,
                        plan_id=plan.id,
                    )
                except ExchangeRateNotFoundError:
                    missing_quotes.append(quote)
            if missing_quotes:
                missing_pairs = ", ".join(
                    f"{quote}/{primary}" for quote in sorted(set(missing_quotes))
                )
                raise MissingExchangeRateError(f"缺少汇率：{missing_pairs}")
        resolver = ExchangeRateResolver(
            db,
            user_id,
            effective_at=effective_timestamp,
            plan_id=plan.id,
        )

    instrument_summaries: list[TradingInstrumentSummary] = []
    total_invested = Decimal("0")
    total_realized = Decimal("0")
    total_unrealized = Decimal("0")
    total_quote_balance_primary = Decimal("0")

    for instrument in instruments:
        stmt = (
            select(TradingInstrumentMetric)
            .where(
                TradingInstrumentMetric.instrument_id == instrument.id,
                TradingInstrumentMetric.user_id == user_id,
            )
            .limit(1)
        )
        metrics = (await db.execute(stmt)).scalars().first()
        if not metrics:
            metrics = await recalculate_instrument_metrics(db, user_id, instrument.id)

        net_position = Decimal(metrics.net_position or 0)
        net_quote_position = quote_balances.get(instrument.id, Decimal("0"))
        avg_entry_price = metrics.avg_entry_price or Decimal("0")
        cost_basis_quote = (
            avg_entry_price * net_position if net_position > 0 else Decimal("0")
        )
        quote_currency = instrument.quote_asset

        try:
            market_price_quote = await resolver.get_rate(
                instrument.base_asset, quote_currency
            )
        except ExchangeRateNotFoundError:
            market_price_quote = avg_entry_price or Decimal("0")

        market_value_quote = net_position * market_price_quote
        realized_quote = Decimal(metrics.realized_pnl or 0)
        unrealized_quote = market_value_quote - cost_basis_quote

        invested_primary = await resolver.convert(
            cost_basis_quote, quote_currency, primary
        )
        realized_primary = await resolver.convert(
            realized_quote, quote_currency, primary
        )
        unrealized_primary = await resolver.convert(
            unrealized_quote, quote_currency, primary
        )
        market_value_primary_base = await resolver.convert(
            market_value_quote, quote_currency, primary
        )
        market_value_primary_quote = await resolver.convert(
            net_quote_position, quote_currency, primary
        )
        market_value_primary_total = (
            market_value_primary_base + market_value_primary_quote
        )
        total_quote_balance_primary += market_value_primary_quote

        total_invested += invested_primary
        total_realized += realized_primary
        total_unrealized += unrealized_primary

        roi_primary = None
        if invested_primary and invested_primary != Decimal("0"):
            roi_primary = (realized_primary + unrealized_primary) / invested_primary

        instrument_summaries.append(
            TradingInstrumentSummary(
                instrument_id=instrument.id,
                plan_id=plan.id,
                symbol=instrument.symbol,
                base_asset=instrument.base_asset,
                quote_asset=quote_currency,
                net_position=net_position,
                net_position_quote=net_quote_position,
                avg_entry_price=avg_entry_price,
                market_price=market_price_quote,
                market_value_primary=market_value_primary_total,
                market_value_primary_base=market_value_primary_base,
                market_value_primary_quote=market_value_primary_quote,
                realized_pnl_primary=realized_primary,
                unrealized_pnl_primary=unrealized_primary,
                invested_primary=invested_primary,
                roi=roi_primary,
                updated_at=metrics.updated_at,
            )
        )

    net_value = (total_invested + total_unrealized) + total_quote_balance_primary
    plan_roi = None
    if total_invested and total_invested != Decimal("0"):
        plan_roi = (total_realized + total_unrealized) / total_invested

    rates_used: list[TradingPlanExchangeRateUsage] = []
    latest_usage_ts: Optional[datetime] = None
    if rate_mode == "snapshot":
        rates_used = snapshot_usages
        for usage in rates_used:
            if usage.captured_at and (
                latest_usage_ts is None or usage.captured_at > latest_usage_ts
            ):
                latest_usage_ts = usage.captured_at
    else:
        usage_records = resolver.get_usage_records()
        for usage in usage_records:
            if usage.base_asset == usage.quote_asset:
                continue
            if usage.captured_at and (
                latest_usage_ts is None or usage.captured_at > latest_usage_ts
            ):
                latest_usage_ts = usage.captured_at
            scope: Literal["plan", "user", "global", "synthetic"]
            if usage.plan_id is not None:
                scope = "plan"
            elif usage.user_id == user_id:
                scope = "user"
            elif usage.user_id is None:
                scope = "global"
            else:
                scope = "synthetic"
            rates_used.append(
                TradingPlanExchangeRateUsage(
                    base_asset=usage.base_asset,
                    quote_asset=usage.quote_asset,
                    rate=usage.rate,
                    scope=scope,
                    derived=usage.derived,
                    source=usage.source,
                    captured_at=usage.captured_at,
                )
            )

    totals = TradingPlanSummaryTotals(
        total_investment=total_invested,
        total_realized=total_realized,
        total_unrealized=total_unrealized,
        net_value=net_value,
        roi=plan_roi,
    )

    if rate_mode == "snapshot":
        rates_updated_at = plan.rate_snapshot_ts
    else:
        rates_updated_at = latest_usage_ts or effective_timestamp

    return TradingPlanSummaryResponse(
        plan_id=plan.id,
        plan_name=plan.name,
        plan_status=plan.status,
        primary_currency=primary,
        calculated_at=calculated_at,
        totals=totals,
        instruments=instrument_summaries,
        rates_used=rates_used,
        rates_updated_at=rates_updated_at,
        rate_mode=rate_mode,
        rate_snapshot_ts=plan.rate_snapshot_ts,
    )


__all__ = [
    "build_trading_plan_rate_snapshot",
    "recalculate_instrument_metrics",
    "get_trading_plan_summary",
]
