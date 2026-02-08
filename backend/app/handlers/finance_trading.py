"""Trading plan domain handlers (async)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.finance_trading import TradingEntry, TradingInstrument, TradingPlan
from app.db.transaction import commit_safely
from app.handlers.finance_common import FinanceError
from app.handlers.metrics import trading_metrics
from app.handlers.user_preferences import get_finance_primary_currency
from app.utils.timezone_util import utc_now


class TradingPlanError(FinanceError):
    """Base error for trading plan operations."""


class TradingPlanNotFoundError(TradingPlanError):
    """Raised when a trading plan cannot be found for the user."""


class TradingInstrumentNotFoundError(TradingPlanError):
    """Raised when a trading instrument is missing or unauthorized."""


class TradingInstrumentConflictError(TradingPlanError):
    """Raised when an instrument violates uniqueness constraints."""


class TradingEntryNotFoundError(TradingPlanError):
    """Raised when a trade entry cannot be located."""


class TradingInstrumentMismatchError(TradingPlanError):
    """Raised when plan/instrument relationship is invalid."""


class TradingInstrumentValidationError(TradingPlanError):
    """Raised when instrument payload is invalid."""


def _normalize_asset_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip().upper()
    return text or None


def _extract_symbol_assets(symbol: str) -> Tuple[str, str]:
    text = (symbol or "").strip().upper()
    if not text:
        raise TradingInstrumentValidationError("symbol must not be empty")
    for sep in ("/", "-", "_"):
        if sep in text:
            parts = [segment for segment in text.split(sep) if segment]
            if len(parts) == 2:
                return parts[0], parts[1]
    if len(text) >= 2:
        midpoint = len(text) // 2
        return text[:midpoint], text[midpoint:]
    raise TradingInstrumentValidationError("symbol must include base and quote assets")


def _normalize_instrument_fields(
    symbol: Optional[str],
    base_asset: Optional[str],
    quote_asset: Optional[str],
    *,
    require_symbol: bool = False,
) -> Tuple[str, str, str]:
    base_from_symbol: Optional[str] = None
    quote_from_symbol: Optional[str] = None
    if symbol is not None:
        base_from_symbol, quote_from_symbol = _extract_symbol_assets(symbol)
    elif require_symbol:
        raise TradingInstrumentValidationError("symbol is required")

    base = _normalize_asset_value(base_asset) or base_from_symbol
    quote = _normalize_asset_value(quote_asset) or quote_from_symbol
    if not base or not quote:
        raise TradingInstrumentValidationError(
            "symbol or explicit base/quote must include both assets",
        )
    normalized_symbol = f"{base}/{quote}"
    return normalized_symbol, base, quote


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    return text or None


async def list_trading_plans(
    db: AsyncSession,
    user_id: UUID,
    *,
    include_archived: bool = False,
    offset: int = 0,
    limit: int = 100,
) -> Tuple[List[TradingPlan], int]:
    conditions = [
        TradingPlan.user_id == user_id,
        TradingPlan.deleted_at.is_(None),
    ]
    if not include_archived:
        conditions.append(TradingPlan.status != "archived")

    stmt = (
        select(TradingPlan)
        .where(*conditions)
        .order_by(TradingPlan.created_at.desc())
        .offset(max(offset, 0))
        .limit(max(limit, 1))
    )
    count_stmt = select(func.count()).select_from(TradingPlan).where(*conditions)
    plans = (await db.execute(stmt)).scalars().all()
    total = await db.scalar(count_stmt)
    return plans, int(total or 0)


async def get_trading_plan(
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
        raise TradingPlanNotFoundError("Trading plan not found")
    return plan


async def create_trading_plan(
    db: AsyncSession,
    user_id: UUID,
    *,
    name: str,
    period_start: Optional[datetime],
    period_end: Optional[datetime],
    target_roi: Optional[Decimal],
    note: Optional[str],
    status: str,
) -> TradingPlan:
    snapshot_currency = await get_finance_primary_currency(db, user_id=user_id)
    plan = TradingPlan(
        user_id=user_id,
        name=name,
        period_start=period_start,
        period_end=period_end,
        target_roi=target_roi,
        note=note,
        status=status,
        rate_snapshot_ts=utc_now(),
        rate_snapshot_currency=snapshot_currency,
    )
    db.add(plan)
    await commit_safely(db)
    await db.refresh(plan)
    return plan


async def update_trading_plan(
    db: AsyncSession,
    user_id: UUID,
    plan_id: UUID,
    *,
    name: Optional[str] = None,
    period_start: Optional[datetime] = None,
    period_end: Optional[datetime] = None,
    target_roi: Optional[Decimal] = None,
    note: Optional[str] = None,
    status: Optional[str] = None,
) -> TradingPlan:
    plan = await get_trading_plan(db, user_id, plan_id, for_update=True)
    if name is not None:
        plan.name = name
    if period_start is not None:
        plan.period_start = period_start
    if period_end is not None:
        plan.period_end = period_end
    if target_roi is not None:
        plan.target_roi = target_roi
    if note is not None:
        plan.note = note
    if status is not None:
        plan.status = status

    await commit_safely(db)
    await db.refresh(plan)
    return plan


async def archive_trading_plan(
    db: AsyncSession,
    user_id: UUID,
    plan_id: UUID,
) -> TradingPlan:
    plan = await get_trading_plan(db, user_id, plan_id)
    plan.status = "archived"
    await commit_safely(db)
    await db.refresh(plan)
    return plan


async def touch_rate_snapshot(
    db: AsyncSession,
    user_id: UUID,
    plan_id: UUID,
    *,
    snapshot_ts: Optional[datetime] = None,
) -> TradingPlan:
    plan = await get_trading_plan(db, user_id, plan_id, for_update=True)
    resolved_snapshot_ts = snapshot_ts or utc_now()
    primary_currency = await get_finance_primary_currency(db, user_id=user_id)
    (
        snapshot_currency,
        snapshot_rates,
    ) = await trading_metrics.build_trading_plan_rate_snapshot(
        db,
        user_id,
        plan.id,
        primary_currency=primary_currency,
        effective_at=resolved_snapshot_ts,
    )
    plan.rate_snapshot_ts = resolved_snapshot_ts
    plan.rate_snapshot_currency = snapshot_currency
    plan.rate_snapshot_rates = snapshot_rates
    await commit_safely(db)
    await db.refresh(plan)
    return plan


async def _ensure_instrument_symbol_available(
    db: AsyncSession,
    user_id: UUID,
    plan_id: UUID,
    symbol: str,
    exclude_id: Optional[UUID] = None,
) -> None:
    normalized_symbol = symbol.strip().upper()
    stmt = select(TradingInstrument.id).where(
        TradingInstrument.user_id == user_id,
        TradingInstrument.plan_id == plan_id,
        func.upper(TradingInstrument.symbol) == normalized_symbol,
        TradingInstrument.deleted_at.is_(None),
    )
    if exclude_id:
        stmt = stmt.where(TradingInstrument.id != exclude_id)
    exists = (await db.execute(stmt)).scalar_one_or_none()
    if exists is not None:
        raise TradingInstrumentConflictError("Instrument symbol already exists in plan")


async def list_trading_instruments(
    db: AsyncSession,
    user_id: UUID,
    *,
    plan_id: Optional[UUID] = None,
    offset: int = 0,
    limit: int = 100,
) -> Tuple[List[TradingInstrument], int]:
    conditions = [
        TradingInstrument.user_id == user_id,
        TradingInstrument.deleted_at.is_(None),
    ]
    if plan_id:
        conditions.append(TradingInstrument.plan_id == plan_id)

    stmt = (
        select(TradingInstrument)
        .where(*conditions)
        .order_by(TradingInstrument.created_at.desc())
        .offset(max(offset, 0))
        .limit(max(limit, 1))
    )
    count_stmt = select(func.count()).select_from(TradingInstrument).where(*conditions)
    instruments = (await db.execute(stmt)).scalars().all()
    total = await db.scalar(count_stmt)
    return instruments, int(total or 0)


async def create_trading_instrument(
    db: AsyncSession,
    user_id: UUID,
    *,
    plan_id: UUID,
    symbol: str,
    base_asset: str,
    quote_asset: str,
    exchange: Optional[str],
    strategy_tag: Optional[str],
    note: Optional[str],
) -> TradingInstrument:
    plan = await get_trading_plan(db, user_id, plan_id)
    normalized_symbol, normalized_base, normalized_quote = _normalize_instrument_fields(
        symbol,
        base_asset,
        quote_asset,
        require_symbol=True,
    )
    await _ensure_instrument_symbol_available(db, user_id, plan.id, normalized_symbol)
    instrument = TradingInstrument(
        user_id=user_id,
        plan_id=plan.id,
        symbol=normalized_symbol,
        base_asset=normalized_base,
        quote_asset=normalized_quote,
        exchange=_clean_optional_text(exchange),
        strategy_tag=_clean_optional_text(strategy_tag),
        note=_clean_optional_text(note),
    )
    db.add(instrument)
    await commit_safely(db)
    await db.refresh(instrument)
    return instrument


async def get_trading_instrument(
    db: AsyncSession,
    user_id: UUID,
    instrument_id: UUID,
    *,
    for_update: bool = False,
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
    if for_update:
        stmt = stmt.with_for_update()
    instrument = (await db.execute(stmt)).scalars().first()
    if not instrument:
        raise TradingInstrumentNotFoundError("Trading instrument not found")
    return instrument


async def update_trading_instrument(
    db: AsyncSession,
    user_id: UUID,
    instrument_id: UUID,
    *,
    symbol: Optional[str] = None,
    base_asset: Optional[str] = None,
    quote_asset: Optional[str] = None,
    exchange: Optional[str] = None,
    strategy_tag: Optional[str] = None,
    note: Optional[str] = None,
) -> TradingInstrument:
    instrument = await get_trading_instrument(
        db, user_id, instrument_id, for_update=True
    )
    if any(value is not None for value in (symbol, base_asset, quote_asset)):
        (
            normalized_symbol,
            normalized_base,
            normalized_quote,
        ) = _normalize_instrument_fields(
            symbol if symbol is not None else instrument.symbol,
            base_asset if base_asset is not None else instrument.base_asset,
            quote_asset if quote_asset is not None else instrument.quote_asset,
            require_symbol=True,
        )
        if normalized_symbol != instrument.symbol:
            await _ensure_instrument_symbol_available(
                db,
                user_id,
                instrument.plan_id,
                normalized_symbol,
                instrument.id,
            )
        instrument.symbol = normalized_symbol
        instrument.base_asset = normalized_base
        instrument.quote_asset = normalized_quote

    if exchange is not None:
        instrument.exchange = _clean_optional_text(exchange)
    if strategy_tag is not None:
        instrument.strategy_tag = _clean_optional_text(strategy_tag)
    if note is not None:
        instrument.note = _clean_optional_text(note)

    await commit_safely(db)
    await db.refresh(instrument)
    return instrument


async def delete_trading_instrument(
    db: AsyncSession,
    user_id: UUID,
    instrument_id: UUID,
) -> None:
    instrument = await get_trading_instrument(db, user_id, instrument_id)
    instrument.soft_delete()
    await commit_safely(db)


async def list_trading_entries(
    db: AsyncSession,
    user_id: UUID,
    *,
    plan_id: Optional[UUID] = None,
    instrument_id: Optional[UUID] = None,
    direction: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    offset: int = 0,
    limit: int = 50,
) -> Tuple[List[TradingEntry], int]:
    stmt = (
        select(TradingEntry)
        .where(
            TradingEntry.user_id == user_id,
            TradingEntry.deleted_at.is_(None),
        )
        .order_by(TradingEntry.trade_time.desc(), TradingEntry.created_at.desc())
    )
    if plan_id:
        stmt = stmt.where(TradingEntry.plan_id == plan_id)
    if instrument_id:
        stmt = stmt.where(TradingEntry.instrument_id == instrument_id)
    if direction:
        stmt = stmt.where(TradingEntry.direction == direction)
    if start_time:
        stmt = stmt.where(TradingEntry.trade_time >= start_time)
    if end_time:
        stmt = stmt.where(TradingEntry.trade_time <= end_time)

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = await db.scalar(total_stmt)
    rows = (
        (await db.execute(stmt.offset(max(offset, 0)).limit(max(limit, 1))))
        .scalars()
        .all()
    )
    return rows, int(total or 0)


def _validate_plan_instrument(plan: TradingPlan, instrument: TradingInstrument) -> None:
    if instrument.plan_id != plan.id:
        raise TradingInstrumentMismatchError("Instrument does not belong to plan")


async def create_trading_entry(
    db: AsyncSession,
    user_id: UUID,
    *,
    plan_id: UUID,
    instrument_id: UUID,
    trade_time: datetime,
    direction: str,
    base_delta: Decimal,
    quote_delta: Decimal,
    price: Optional[Decimal],
    fee_asset: Optional[str],
    fee_amount: Optional[Decimal],
    source: str,
    note: Optional[str],
) -> TradingEntry:
    plan = await get_trading_plan(db, user_id, plan_id)
    instrument = await get_trading_instrument(db, user_id, instrument_id)
    _validate_plan_instrument(plan, instrument)
    entry = TradingEntry(
        user_id=user_id,
        plan_id=plan.id,
        instrument_id=instrument.id,
        trade_time=trade_time,
        direction=direction,
        base_delta=base_delta,
        quote_delta=quote_delta,
        price=price,
        fee_asset=fee_asset,
        fee_amount=fee_amount,
        source=source,
        note=note,
    )
    db.add(entry)
    await commit_safely(db)
    await db.refresh(entry)
    await _trigger_metric_recalc(db, user_id, instrument.id)
    return entry


async def get_trading_entry(
    db: AsyncSession,
    user_id: UUID,
    entry_id: UUID,
    *,
    for_update: bool = False,
) -> TradingEntry:
    stmt = (
        select(TradingEntry)
        .where(
            TradingEntry.id == entry_id,
            TradingEntry.user_id == user_id,
            TradingEntry.deleted_at.is_(None),
        )
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    entry = (await db.execute(stmt)).scalars().first()
    if not entry:
        raise TradingEntryNotFoundError("Trading entry not found")
    return entry


async def update_trading_entry(
    db: AsyncSession,
    user_id: UUID,
    entry_id: UUID,
    *,
    trade_time: Optional[datetime] = None,
    direction: Optional[str] = None,
    base_delta: Optional[Decimal] = None,
    quote_delta: Optional[Decimal] = None,
    price: Optional[Decimal] = None,
    fee_asset: Optional[str] = None,
    fee_amount: Optional[Decimal] = None,
    source: Optional[str] = None,
    note: Optional[str] = None,
) -> TradingEntry:
    entry = await get_trading_entry(db, user_id, entry_id, for_update=True)

    if trade_time is not None:
        entry.trade_time = trade_time
    if direction is not None:
        entry.direction = direction
    if base_delta is not None:
        entry.base_delta = base_delta
    if quote_delta is not None:
        entry.quote_delta = quote_delta
    if price is not None:
        entry.price = price
    if fee_asset is not None:
        entry.fee_asset = fee_asset
    if fee_amount is not None:
        entry.fee_amount = fee_amount
    if source is not None:
        entry.source = source
    if note is not None:
        entry.note = note

    await commit_safely(db)
    await db.refresh(entry)
    await _trigger_metric_recalc(db, user_id, entry.instrument_id)
    return entry


async def delete_trading_entry(
    db: AsyncSession,
    user_id: UUID,
    entry_id: UUID,
) -> None:
    entry = await get_trading_entry(db, user_id, entry_id)
    instrument_id = entry.instrument_id
    entry.soft_delete()
    await commit_safely(db)
    await _trigger_metric_recalc(db, user_id, instrument_id)


async def _trigger_metric_recalc(
    db: AsyncSession,
    user_id: UUID,
    instrument_id: UUID,
) -> None:
    try:
        await trading_metrics.recalculate_instrument_metrics(db, user_id, instrument_id)
    except TradingInstrumentNotFoundError:
        pass


__all__ = [
    "TradingPlanError",
    "TradingPlanNotFoundError",
    "TradingInstrumentNotFoundError",
    "TradingInstrumentConflictError",
    "TradingEntryNotFoundError",
    "TradingInstrumentMismatchError",
    "TradingInstrumentValidationError",
    "list_trading_plans",
    "get_trading_plan",
    "create_trading_plan",
    "update_trading_plan",
    "archive_trading_plan",
    "list_trading_instruments",
    "create_trading_instrument",
    "get_trading_instrument",
    "update_trading_instrument",
    "delete_trading_instrument",
    "list_trading_entries",
    "create_trading_entry",
    "get_trading_entry",
    "update_trading_entry",
    "delete_trading_entry",
]
