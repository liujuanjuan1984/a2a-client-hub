"""
Async helpers for finance cashflow handlers.

This module keeps router code pure-async without relying on ``run_with_session``.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Optional, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.finance_cashflow import (
    CashflowBillingEntry,
    CashflowSnapshot,
    CashflowSnapshotEntry,
    CashflowSource,
)
from app.db.models.user_preference import UserPreference
from app.db.transaction import commit_safely
from app.handlers.finance_cashflow_trees import resolve_cashflow_tree
from app.handlers.finance_common import (
    EIGHT_PLACES,
    CashflowSourceNameConflictError,
    CashflowSourceNotFoundError,
    EmptySnapshotPayloadError,
    FinanceError,
    build_path,
    compute_depth,
    from_json_number,
    slugify,
    to_json_number,
)
from app.handlers.finance_exchange_rate_utils import (
    build_exchange_rate_map,
    ensure_rates_for_currencies,
    normalize_currency_code,
)
from app.handlers.finance_rate_snapshots import build_rate_snapshot_map
from app.utils.timezone_util import utc_now

SNAPSHOT_TIME_TOLERANCE = timedelta(minutes=1)


def _month_bounds(month: date) -> Tuple[date, date]:
    month_start = month.replace(day=1)
    last_day = calendar.monthrange(month_start.year, month_start.month)[1]
    month_end = date(month_start.year, month_start.month, last_day)
    return month_start, month_end


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _add_years(value: date, years: int) -> date:
    year = value.year + years
    month = value.month
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _advance_cycle_forward(start: date, cycle_type: str, interval: int) -> date:
    if cycle_type == "day":
        return start + timedelta(days=interval)
    if cycle_type == "week":
        return start + timedelta(days=7 * interval)
    if cycle_type == "month":
        return _add_months(start, interval)
    if cycle_type == "year":
        return _add_years(start, interval)
    raise ValueError("Unsupported billing cycle type")


def _advance_cycle_backward(start: date, cycle_type: str, interval: int) -> date:
    if cycle_type == "day":
        return start - timedelta(days=interval)
    if cycle_type == "week":
        return start - timedelta(days=7 * interval)
    if cycle_type == "month":
        return _add_months(start, -interval)
    if cycle_type == "year":
        return _add_years(start, -interval)
    raise ValueError("Unsupported billing cycle type")


def _normalize_snapshot_period_bounds(
    user_timezone: ZoneInfo,
    period_start: datetime,
    period_end: datetime,
) -> Tuple[datetime, datetime, date, date]:
    if period_start.tzinfo is None:
        period_start = period_start.replace(tzinfo=timezone.utc)
    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)

    local_start = period_start.astimezone(user_timezone)
    month_start = local_start.date().replace(day=1)
    next_month = _add_months(month_start, 1)
    month_end = next_month - timedelta(days=1)

    end_month_candidate = period_end.astimezone(user_timezone).date().replace(day=1)
    if end_month_candidate not in {month_start, next_month}:
        raise ValueError("period_end must align with the month boundary")

    start_dt_local = datetime.combine(month_start, time.min, tzinfo=user_timezone)
    end_dt_local = datetime.combine(next_month, time.min, tzinfo=user_timezone)

    return (
        start_dt_local.astimezone(timezone.utc),
        end_dt_local.astimezone(timezone.utc),
        month_start,
        month_end,
    )


def _normalize_cashflow_entries_payload(
    entries_payload: List[Tuple[CashflowSource, Decimal, Optional[str], Optional[str]]],
) -> List[Tuple[CashflowSource, Decimal, Optional[str], Optional[str]]]:
    normalized: List[Tuple[CashflowSource, Decimal, Optional[str], Optional[str]]] = []
    for entry in entries_payload:
        if len(entry) == 3:
            source, amount, entry_note = entry  # type: ignore[misc]
            entry_currency = None
        elif len(entry) == 4:
            source, amount, entry_note, entry_currency = entry  # type: ignore[misc]
        else:
            raise ValueError("entries_payload must contain 3 or 4 values")
        normalized.append((source, amount, entry_note, entry_currency))
    return normalized


def _resolve_entry_currency(
    source: CashflowSource,
    entry_currency: Optional[str],
    primary_currency: str,
) -> str:
    fallback = source.currency_code or primary_currency
    return normalize_currency_code(entry_currency or fallback)


def _resolve_tree_id_from_sources(
    tree_id: Optional[UUID], sources: List[CashflowSource]
) -> UUID:
    if tree_id:
        if any(source.tree_id != tree_id for source in sources):
            raise FinanceError("Cashflow sources must belong to the same tree")
        return tree_id
    if not sources:
        raise FinanceError("Cannot resolve cashflow tree without sources")
    inferred = sources[0].tree_id
    if any(source.tree_id != inferred for source in sources):
        raise FinanceError("Cashflow sources must belong to the same tree")
    return inferred


def _resolve_snapshot_ts(period_end: datetime) -> datetime:
    end_ts = period_end
    if end_ts.tzinfo is None:
        end_ts = end_ts.replace(tzinfo=timezone.utc)
    now = utc_now()
    return min(now, end_ts)


def _normalize_posted_month(
    source: CashflowSource,
    cycle_start: date,
    cycle_end: date,
) -> date:
    reference = (
        cycle_start if (source.billing_post_to or "end") == "start" else cycle_end
    )
    return reference.replace(day=1)


def _calculate_cycles_for_month(
    source: CashflowSource,
    month: date,
) -> List[Tuple[date, date]]:
    if not source.billing_cycle_type or not source.billing_anchor_date:
        return []
    interval = source.billing_cycle_interval or 1
    cycle_type = source.billing_cycle_type
    anchor = source.billing_anchor_date
    month_start, month_end = _month_bounds(month)

    current_start = anchor
    if current_start > month_start:
        while current_start > month_start:
            next_start = _advance_cycle_backward(current_start, cycle_type, interval)
            if next_start >= current_start:
                break
            current_start = next_start
    else:
        while True:
            next_start = _advance_cycle_forward(current_start, cycle_type, interval)
            if next_start > month_start:
                break
            current_start = next_start

    cycles: List[Tuple[date, date]] = []
    visited = 0
    while current_start <= month_end and visited < 1000:
        next_start = _advance_cycle_forward(current_start, cycle_type, interval)
        cycle_end = next_start - timedelta(days=1)
        if cycle_end >= month_start and current_start <= month_end:
            cycles.append((current_start, cycle_end))
        current_start = next_start
        visited += 1

    return cycles


def _apply_billing_config(
    source: CashflowSource,
    *,
    kind: Optional[str],
    cycle_type: Optional[str],
    cycle_interval: Optional[int],
    anchor_day: Optional[int],
    anchor_date: Optional[date],
    post_to: Optional[str],
    default_amount: Optional[Decimal],
    default_note: Optional[str],
    requires_manual_input: Optional[bool],
) -> None:
    """Normalize billing attributes on a source (mirrors sync handler)."""

    normalized_kind = (kind or "regular").lower()
    source.kind = normalized_kind
    if normalized_kind != "billing":
        source.billing_cycle_type = None
        source.billing_cycle_interval = None
        source.billing_anchor_day = None
        source.billing_anchor_date = None
        source.billing_post_to = None
        source.billing_default_amount = None
        source.billing_default_note = None
        source.billing_requires_manual_input = False
        return

    if not cycle_type:
        raise ValueError("Billing source must specify billing_cycle_type")
    cycle_type = cycle_type.lower()
    if cycle_type not in {"day", "week", "month", "year"}:
        raise ValueError("billing_cycle_type must be one of day/week/month/year")

    interval = cycle_interval or 1
    if interval <= 0:
        raise ValueError("billing_cycle_interval must be greater than 0")

    if anchor_date is None:
        raise ValueError("Billing source must provide billing_anchor_date")

    post_to_value = (post_to or "end").lower()
    if post_to_value not in {"start", "end"}:
        raise ValueError("billing_post_to must be either 'start' or 'end'")

    requires_manual = bool(requires_manual_input)
    source.billing_requires_manual_input = requires_manual

    if not requires_manual:
        if default_amount is None:
            raise ValueError(
                "Fixed-amount billing source must provide a default amount"
            )
        normalized_amount = default_amount.quantize(
            EIGHT_PLACES, rounding=ROUND_HALF_UP
        )
    else:
        normalized_amount = (
            default_amount.quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)
            if default_amount is not None
            else None
        )

    if cycle_type in {"month", "year"}:
        computed_anchor_day = anchor_day or anchor_date.day
        if not 1 <= computed_anchor_day <= 28:
            raise ValueError("billing_anchor_day must be between 1 and 28")
        source.billing_anchor_day = computed_anchor_day
    else:
        source.billing_anchor_day = None

    source.billing_cycle_type = cycle_type
    source.billing_cycle_interval = interval
    source.billing_anchor_date = anchor_date
    source.billing_post_to = post_to_value
    source.billing_default_amount = normalized_amount
    source.billing_default_note = default_note.strip() if default_note else None


async def _load_source(
    db: AsyncSession,
    user_id: UUID,
    source_id: UUID,
    tree_id: Optional[UUID] = None,
    *,
    with_for_update: bool = False,
) -> Optional[CashflowSource]:
    stmt = (
        select(CashflowSource)
        .where(
            CashflowSource.id == source_id,
            CashflowSource.user_id == user_id,
            CashflowSource.deleted_at.is_(None),
        )
        .limit(1)
    )
    if tree_id:
        stmt = stmt.where(CashflowSource.tree_id == tree_id)
    if with_for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return result.scalars().first()


async def _assert_source_name_available(
    db: AsyncSession,
    user_id: UUID,
    tree_id: UUID,
    parent_id: Optional[UUID],
    name: str,
    *,
    exclude_source_id: Optional[UUID] = None,
) -> None:
    stmt = (
        select(func.count())
        .select_from(CashflowSource)
        .where(
            CashflowSource.user_id == user_id,
            CashflowSource.tree_id == tree_id,
            CashflowSource.deleted_at.is_(None),
            CashflowSource.name == name,
        )
    )
    if parent_id is None:
        stmt = stmt.where(CashflowSource.parent_id.is_(None))
    else:
        stmt = stmt.where(CashflowSource.parent_id == parent_id)
    if exclude_source_id:
        stmt = stmt.where(CashflowSource.id != exclude_source_id)
    exists = (await db.execute(stmt)).scalar_one()
    if exists:
        raise CashflowSourceNameConflictError(
            "A source with the same name already exists under the parent"
        )


async def _ensure_unique_source_path(
    db: AsyncSession,
    user_id: UUID,
    tree_id: UUID,
    base_path: str,
    *,
    exclude_source_id: Optional[UUID] = None,
) -> str:
    candidate = base_path
    suffix = 1
    while True:
        stmt = (
            select(func.count())
            .select_from(CashflowSource)
            .where(
                CashflowSource.user_id == user_id,
                CashflowSource.tree_id == tree_id,
                CashflowSource.path == candidate,
            )
        )
        if exclude_source_id:
            stmt = stmt.where(CashflowSource.id != exclude_source_id)
        exists = (await db.execute(stmt)).scalar_one()
        if not exists:
            return candidate
        candidate = f"{base_path}-{suffix}"
        suffix += 1


async def _recompute_children_cache(
    db: AsyncSession,
    parent_id: Optional[UUID],
) -> None:
    if not parent_id:
        return
    parent_stmt = (
        select(CashflowSource)
        .where(
            CashflowSource.id == parent_id,
            CashflowSource.deleted_at.is_(None),
        )
        .with_for_update()
        .limit(1)
    )
    parent = (await db.execute(parent_stmt)).scalars().first()
    if not parent:
        return
    count_stmt = (
        select(func.count())
        .select_from(CashflowSource)
        .where(
            CashflowSource.parent_id == parent.id,
            CashflowSource.deleted_at.is_(None),
        )
    )
    child_count = (await db.execute(count_stmt)).scalar_one() or 0
    parent.children_count = child_count
    parent.is_rollup = child_count > 0


async def _get_or_create_month_snapshot(
    db: AsyncSession,
    user_id: UUID,
    primary_currency: str,
    month_start: date,
    month_end: date,
    tree_id: UUID,
    *,
    user_timezone: ZoneInfo,
) -> CashflowSnapshot:
    next_month = _add_months(month_start, 1)
    start_dt_local = datetime.combine(month_start, time.min, tzinfo=user_timezone)
    end_dt_local = datetime.combine(next_month, time.min, tzinfo=user_timezone)
    start_dt = start_dt_local.astimezone(timezone.utc)
    end_dt = end_dt_local.astimezone(timezone.utc)

    existing = await _find_existing_snapshot(db, user_id, start_dt, end_dt, tree_id)
    if existing:
        existing.period_start = start_dt
        existing.period_end = end_dt
        existing.primary_currency = primary_currency.upper()
        if existing.snapshot_ts is None:
            existing.snapshot_ts = _resolve_snapshot_ts(end_dt)
        return existing

    snapshot = CashflowSnapshot(
        user_id=user_id,
        tree_id=tree_id,
        period_start=start_dt,
        period_end=end_dt,
        primary_currency=primary_currency.upper(),
        total_income=Decimal("0"),
        total_expense=Decimal("0"),
        total_positive=Decimal("0"),
        total_negative=Decimal("0"),
        net_cashflow=Decimal("0"),
        summary={},
        note=None,
        snapshot_ts=_resolve_snapshot_ts(end_dt),
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


async def _upsert_snapshot_entry(
    db: AsyncSession,
    snapshot: CashflowSnapshot,
    source: CashflowSource,
    amount: Decimal,
    note: Optional[str],
    currency_code: Optional[str] = None,
    *,
    auto_generated: bool = False,
) -> None:
    normalized_amount = amount.quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)
    resolved_currency = _resolve_entry_currency(
        source, currency_code, snapshot.primary_currency
    )
    stmt = (
        select(CashflowSnapshotEntry)
        .where(
            CashflowSnapshotEntry.snapshot_id == snapshot.id,
            CashflowSnapshotEntry.source_id == source.id,
        )
        .limit(1)
    )
    entry = (await db.execute(stmt)).scalars().first()
    if entry:
        entry.amount = normalized_amount
        entry.note = note
        entry.currency_code = resolved_currency
        entry.is_auto_generated = auto_generated
        return

    db.add(
        CashflowSnapshotEntry(
            snapshot_id=snapshot.id,
            source_id=source.id,
            amount=normalized_amount,
            currency_code=resolved_currency,
            note=note,
            is_auto_generated=auto_generated,
        )
    )


async def _recalculate_snapshot_totals(
    db: AsyncSession,
    snapshot: CashflowSnapshot,
    *,
    billing_summary: Optional[Dict[str, List[Dict[str, object]]]] = None,
) -> None:
    stmt = select(CashflowSnapshotEntry).where(
        CashflowSnapshotEntry.snapshot_id == snapshot.id
    )
    entries = (await db.execute(stmt)).scalars().all()

    entry_currencies = [entry.currency_code for entry in entries]
    rate_map = {
        currency: from_json_number(rate)
        for currency, rate in (snapshot.exchange_rates or {}).items()
    }
    if not rate_map and any(
        normalize_currency_code(currency) != snapshot.primary_currency
        for currency in entry_currencies
    ):
        snapshot_ts = snapshot.snapshot_ts or _resolve_snapshot_ts(snapshot.period_end)
        _, rate_map, _, _ = await build_rate_snapshot_map(
            db,
            user_id=snapshot.user_id,
            primary_currency=snapshot.primary_currency,
            currencies=entry_currencies,
            effective_at=snapshot_ts,
        )
        snapshot.snapshot_ts = snapshot_ts
        snapshot.exchange_rates = (
            {key: to_json_number(rate) for key, rate in rate_map.items()}
            if rate_map
            else None
        )
    ensure_rates_for_currencies(
        primary_currency=snapshot.primary_currency,
        currencies=entry_currencies,
        rate_map=rate_map,
    )

    total_positive = Decimal("0")
    total_negative = Decimal("0")
    income_breakdown: Dict[str, object] = {}
    expense_breakdown: Dict[str, object] = {}

    for entry in entries:
        amount = entry.amount.quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)
        entry_currency = normalize_currency_code(entry.currency_code)
        if entry_currency != snapshot.primary_currency:
            rate = rate_map[entry_currency]
            amount = (amount * rate).quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)
        if amount >= 0:
            total_positive += amount
            income_breakdown[str(entry.source_id)] = to_json_number(amount)
        else:
            total_negative += amount
            expense_breakdown[str(entry.source_id)] = to_json_number(-amount)

    snapshot.total_positive = total_positive.quantize(EIGHT_PLACES)
    snapshot.total_negative = total_negative.quantize(EIGHT_PLACES)
    snapshot.total_income = total_positive.quantize(EIGHT_PLACES)
    snapshot.total_expense = (-total_negative).quantize(EIGHT_PLACES)
    snapshot.net_cashflow = (total_positive + total_negative).quantize(EIGHT_PLACES)

    summary: Dict[str, object] = {
        "income": income_breakdown,
        "expense": expense_breakdown,
    }
    if billing_summary:
        summary["billing_cycles"] = billing_summary
    snapshot.summary = summary


async def list_cashflow_sources(
    db: AsyncSession, user_id: UUID, *, tree_id: Optional[UUID]
) -> List[CashflowSource]:
    """Async variant of ``finance_cashflow.list_cashflow_sources``."""

    tree = await resolve_cashflow_tree(db, user_id, tree_id)
    stmt = (
        select(CashflowSource)
        .where(
            CashflowSource.user_id == user_id,
            CashflowSource.tree_id == tree.id,
            CashflowSource.deleted_at.is_(None),
        )
        .order_by(
            CashflowSource.depth,
            CashflowSource.display_order.is_(None),
            CashflowSource.display_order,
            CashflowSource.name,
        )
    )
    rows = await db.execute(stmt)
    return rows.scalars().all()


async def create_cashflow_source(
    db: AsyncSession,
    user_id: UUID,
    *,
    name: str,
    parent_id: Optional[UUID],
    tree_id: Optional[UUID],
    metadata: Optional[Dict],
    sort_order: Optional[int],
    kind: Optional[str] = None,
    currency_code: Optional[str] = None,
    billing_cycle_type: Optional[str] = None,
    billing_cycle_interval: Optional[int] = None,
    billing_anchor_day: Optional[int] = None,
    billing_anchor_date: Optional[date] = None,
    billing_post_to: Optional[str] = None,
    billing_default_amount: Optional[Decimal] = None,
    billing_default_note: Optional[str] = None,
    billing_requires_manual_input: Optional[bool] = None,
) -> CashflowSource:
    parent = None
    if parent_id:
        parent = await _load_source(db, user_id, parent_id)
        if not parent:
            raise CashflowSourceNotFoundError("Parent source does not exist")
        if tree_id and parent.tree_id != tree_id:
            raise CashflowSourceNotFoundError("Cannot create source across trees")

    resolved_tree = (
        parent.tree if parent else await resolve_cashflow_tree(db, user_id, tree_id)
    )

    normalized_name = name.strip()
    await _assert_source_name_available(
        db, user_id, resolved_tree.id, parent.id if parent else None, normalized_name
    )

    slug = slugify(normalized_name)
    base_path = build_path(parent.path if parent else None, slug)
    path = await _ensure_unique_source_path(db, user_id, resolved_tree.id, base_path)
    depth = compute_depth(path)

    effective_sort_order = sort_order
    if effective_sort_order is None:
        sibling_query = (
            select(func.coalesce(func.max(CashflowSource.display_order), 0))
            .select_from(CashflowSource)
            .where(
                CashflowSource.user_id == user_id,
                CashflowSource.tree_id == resolved_tree.id,
                CashflowSource.deleted_at.is_(None),
            )
        )
        if parent:
            sibling_query = sibling_query.where(CashflowSource.parent_id == parent.id)
        else:
            sibling_query = sibling_query.where(CashflowSource.parent_id.is_(None))
        max_order = (await db.execute(sibling_query)).scalar_one() or 0
        effective_sort_order = max_order + 1

    source = CashflowSource(
        user_id=user_id,
        tree_id=resolved_tree.id,
        name=normalized_name,
        parent_id=parent.id if parent else None,
        path=path,
        depth=depth,
        display_order=effective_sort_order,
        metadata_json=metadata,
        is_rollup=False,
        children_count=0,
        currency_code=normalize_currency_code(currency_code or "USD"),
    )
    _apply_billing_config(
        source,
        kind=kind,
        cycle_type=billing_cycle_type,
        cycle_interval=billing_cycle_interval,
        anchor_day=billing_anchor_day,
        anchor_date=billing_anchor_date,
        post_to=billing_post_to,
        default_amount=billing_default_amount,
        default_note=billing_default_note,
        requires_manual_input=billing_requires_manual_input,
    )
    db.add(source)
    await db.flush()
    await _recompute_children_cache(db, parent.id if parent else None)
    await commit_safely(db)
    await db.refresh(source)
    return source


async def update_cashflow_source(
    db: AsyncSession,
    user_id: UUID,
    source_id: UUID,
    *,
    name: Optional[str] = None,
    parent_id: Optional[UUID] = None,
    metadata: Optional[Dict] = None,
    sort_order: Optional[int] = None,
    kind: Optional[str] = None,
    currency_code: Optional[str] = None,
    billing_cycle_type: Optional[str] = None,
    billing_cycle_interval: Optional[int] = None,
    billing_anchor_day: Optional[int] = None,
    billing_anchor_date: Optional[date] = None,
    billing_post_to: Optional[str] = None,
    billing_default_amount: Optional[Decimal] = None,
    billing_default_note: Optional[str] = None,
    billing_requires_manual_input: Optional[bool] = None,
) -> CashflowSource:
    source = await _load_source(db, user_id, source_id, with_for_update=True)
    if not source:
        raise CashflowSourceNotFoundError("Cashflow source does not exist")

    original_parent_id = source.parent_id
    current_parent = (
        await _load_source(db, user_id, source.parent_id) if source.parent_id else None
    )
    parent_changed = False
    if parent_id is not None and parent_id != source.parent_id:
        if parent_id == source.id:
            raise CashflowSourceNotFoundError("Cannot set a source as its own parent")
        new_parent = await _load_source(db, user_id, parent_id)
        if not new_parent:
            raise CashflowSourceNotFoundError("Parent source does not exist")
        if new_parent.tree_id != source.tree_id:
            raise CashflowSourceNotFoundError("Cannot move source across trees")
        if new_parent.path.startswith(f"{source.path}/"):
            raise CashflowSourceNotFoundError(
                "Cannot move a source into its own descendant"
            )
        source.parent_id = new_parent.id
        current_parent = new_parent
        parent_changed = True

    new_name = name.strip() if name is not None else source.name
    await _assert_source_name_available(
        db,
        user_id,
        source.tree_id,
        source.parent_id,
        new_name,
        exclude_source_id=source.id,
    )

    dirty_path = False
    if name is not None and new_name != source.name:
        source.name = new_name
        dirty_path = True
    if metadata is not None:
        source.metadata_json = metadata
    if sort_order is not None:
        source.display_order = sort_order
    if currency_code is not None:
        source.currency_code = normalize_currency_code(currency_code)
    if parent_id is not None:
        dirty_path = True

    _apply_billing_config(
        source,
        kind=kind or source.kind,
        cycle_type=billing_cycle_type or source.billing_cycle_type,
        cycle_interval=(
            billing_cycle_interval
            if billing_cycle_interval is not None
            else source.billing_cycle_interval
        ),
        anchor_day=(
            billing_anchor_day
            if billing_anchor_day is not None
            else source.billing_anchor_day
        ),
        anchor_date=billing_anchor_date or source.billing_anchor_date,
        post_to=billing_post_to or source.billing_post_to,
        default_amount=(
            billing_default_amount
            if billing_default_amount is not None
            else source.billing_default_amount
        ),
        default_note=(
            billing_default_note
            if billing_default_note is not None
            else source.billing_default_note
        ),
        requires_manual_input=(
            billing_requires_manual_input
            if billing_requires_manual_input is not None
            else source.billing_requires_manual_input
        ),
    )

    if dirty_path:
        parent_path = current_parent.path if current_parent else None
        slug = slugify(source.name)
        base_path = build_path(parent_path, slug)
        new_path = await _ensure_unique_source_path(
            db,
            user_id,
            source.tree_id,
            base_path,
            exclude_source_id=source.id,
        )
        old_path = source.path
        source.path = new_path
        source.depth = compute_depth(new_path)
        if old_path != new_path:
            descendants_stmt = select(CashflowSource).where(
                CashflowSource.user_id == user_id,
                CashflowSource.tree_id == source.tree_id,
                CashflowSource.deleted_at.is_(None),
                CashflowSource.path.like(f"{old_path}/%"),
            )
            descendants = (await db.execute(descendants_stmt)).scalars().all()
            for child in descendants:
                relative = child.path[len(old_path) :]
                child.path = f"{new_path}{relative}"
                child.depth = compute_depth(child.path)

    if parent_changed:
        await _recompute_children_cache(db, original_parent_id)
        await _recompute_children_cache(db, source.parent_id)
    else:
        await _recompute_children_cache(db, source.parent_id)
    await _recompute_children_cache(db, source.id)

    await commit_safely(db)
    await db.refresh(source)
    return source


async def delete_cashflow_source(
    db: AsyncSession, user_id: UUID, source_id: UUID
) -> None:
    source = await _load_source(db, user_id, source_id)
    if not source:
        raise CashflowSourceNotFoundError("Cashflow source does not exist")

    now = utc_now()
    source.deleted_at = now
    descendants_stmt = select(CashflowSource).where(
        CashflowSource.user_id == user_id,
        CashflowSource.tree_id == source.tree_id,
        CashflowSource.deleted_at.is_(None),
        CashflowSource.path.like(f"{source.path}/%"),
    )
    descendants = (await db.execute(descendants_stmt)).scalars().all()
    for child in descendants:
        child.deleted_at = now
    await _recompute_children_cache(db, source.parent_id)
    await commit_safely(db)


async def _resolve_user_timezone(db: AsyncSession, user_id: UUID) -> ZoneInfo:
    """Mirror ``_resolve_user_timezone`` for AsyncSession."""

    stmt = (
        select(UserPreference.value)
        .where(
            UserPreference.user_id == user_id,
            UserPreference.key == "system.timezone",
            UserPreference.deleted_at.is_(None),
        )
        .limit(1)
    )
    raw_value = (await db.execute(stmt)).scalar_one_or_none()
    timezone_name = raw_value if isinstance(raw_value, str) else "UTC"
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


async def _find_existing_snapshot(
    db: AsyncSession,
    user_id: UUID,
    period_start: datetime,
    period_end: datetime,
    tree_id: UUID,
) -> Optional[CashflowSnapshot]:
    stmt = (
        select(CashflowSnapshot)
        .where(
            CashflowSnapshot.user_id == user_id,
            CashflowSnapshot.tree_id == tree_id,
            CashflowSnapshot.period_start >= period_start - SNAPSHOT_TIME_TOLERANCE,
            CashflowSnapshot.period_start <= period_start + SNAPSHOT_TIME_TOLERANCE,
            CashflowSnapshot.period_end >= period_end - SNAPSHOT_TIME_TOLERANCE,
            CashflowSnapshot.period_end <= period_end + SNAPSHOT_TIME_TOLERANCE,
        )
        .order_by(CashflowSnapshot.created_at.asc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


async def create_cashflow_snapshot(
    db: AsyncSession,
    user_id: UUID,
    *,
    tree_id: Optional[UUID],
    primary_currency: str,
    period_start: datetime,
    period_end: datetime,
    entries_payload: List[Tuple[CashflowSource, Decimal, Optional[str], Optional[str]]],
    exchange_rates_payload: Optional[List[Tuple[str, Decimal]]] = None,
    note: Optional[str],
) -> CashflowSnapshot:
    """Async implementation of ``finance_cashflow.create_cashflow_snapshot``."""

    if not entries_payload:
        raise EmptySnapshotPayloadError("At least one source amount is required")
    if period_end < period_start:
        raise ValueError("period_end must not be earlier than period_start")

    currency = primary_currency.upper()
    user_timezone = await _resolve_user_timezone(db, user_id)
    normalized_start, normalized_end, _, _ = _normalize_snapshot_period_bounds(
        user_timezone, period_start, period_end
    )
    resolved_tree_id = _resolve_tree_id_from_sources(
        tree_id, [entry[0] for entry in entries_payload]
    )
    existing_snapshot = await _find_existing_snapshot(
        db, user_id, normalized_start, normalized_end, resolved_tree_id
    )
    if existing_snapshot:
        raise FinanceError("Cashflow snapshot for this period already exists")

    normalized_entries = _normalize_cashflow_entries_payload(entries_payload)
    resolved_entries = [
        (
            source,
            amount,
            entry_note,
            _resolve_entry_currency(source, entry_currency, currency),
        )
        for source, amount, entry_note, entry_currency in normalized_entries
    ]

    total_positive = Decimal("0")
    total_negative = Decimal("0")
    income_breakdown: Dict[str, float] = {}
    expense_breakdown: Dict[str, float] = {}

    snapshot_ts = _resolve_snapshot_ts(normalized_end)
    if exchange_rates_payload:
        rate_map = build_exchange_rate_map(exchange_rates_payload)
        rate_map.pop(currency, None)
        ensure_rates_for_currencies(
            primary_currency=currency,
            currencies=[entry_currency for _, _, _, entry_currency in resolved_entries],
            rate_map=rate_map,
        )
    else:
        _, rate_map, _, _ = await build_rate_snapshot_map(
            db,
            user_id=user_id,
            primary_currency=currency,
            currencies=[entry_currency for _, _, _, entry_currency in resolved_entries],
            effective_at=snapshot_ts,
        )

    snapshot = CashflowSnapshot(
        user_id=user_id,
        tree_id=resolved_tree_id,
        period_start=normalized_start,
        period_end=normalized_end,
        primary_currency=currency,
        total_income=Decimal("0"),
        total_expense=Decimal("0"),
        total_positive=Decimal("0"),
        total_negative=Decimal("0"),
        net_cashflow=Decimal("0"),
        note=note,
        summary={},
        snapshot_ts=snapshot_ts,
        exchange_rates=(
            {key: to_json_number(rate) for key, rate in rate_map.items()}
            if rate_map
            else None
        ),
    )
    db.add(snapshot)
    await db.flush()

    for source, amount, entry_note, entry_currency in resolved_entries:
        if source.is_rollup:
            raise FinanceError("Rollup sources cannot accept direct snapshot amounts")
        normalized_amount = amount.quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)
        resolved_currency = entry_currency
        converted_amount = normalized_amount
        if resolved_currency != currency:
            converted_amount = (
                normalized_amount * rate_map[resolved_currency]
            ).quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)
        if converted_amount >= 0:
            total_positive += converted_amount
            income_breakdown[str(source.id)] = to_json_number(converted_amount)
        else:
            total_negative += converted_amount
            expense_breakdown[str(source.id)] = to_json_number(-converted_amount)

        entry = CashflowSnapshotEntry(
            snapshot_id=snapshot.id,
            source_id=source.id,
            amount=normalized_amount,
            currency_code=resolved_currency,
            note=entry_note,
            is_auto_generated=False,
        )
        db.add(entry)

    net_cashflow = total_positive + total_negative
    snapshot.total_positive = total_positive.quantize(EIGHT_PLACES)
    snapshot.total_negative = total_negative.quantize(EIGHT_PLACES)
    snapshot.total_income = total_positive.quantize(EIGHT_PLACES)
    snapshot.total_expense = (-total_negative).quantize(EIGHT_PLACES)
    snapshot.net_cashflow = net_cashflow.quantize(EIGHT_PLACES)
    snapshot.summary = {
        "income": income_breakdown,
        "expense": expense_breakdown,
    }

    await commit_safely(db)
    await db.refresh(snapshot)
    return snapshot


async def update_cashflow_snapshot(
    db: AsyncSession,
    user_id: UUID,
    snapshot_id: UUID,
    *,
    tree_id: Optional[UUID],
    primary_currency: Optional[str],
    period_start: datetime,
    period_end: datetime,
    entries_payload: List[Tuple[CashflowSource, Decimal, Optional[str], Optional[str]]],
    exchange_rates_payload: Optional[List[Tuple[str, Decimal]]] = None,
    note: Optional[str],
) -> CashflowSnapshot:
    stmt = (
        select(CashflowSnapshot)
        .where(
            CashflowSnapshot.id == snapshot_id,
            CashflowSnapshot.user_id == user_id,
        )
        .with_for_update()
        .limit(1)
    )
    snapshot = (await db.execute(stmt)).scalars().first()
    if not snapshot:
        raise FinanceError("Cashflow snapshot does not exist")
    if tree_id and snapshot.tree_id != tree_id:
        raise FinanceError("Cashflow snapshot does not exist")

    if not entries_payload:
        raise EmptySnapshotPayloadError("At least one source amount is required")
    if period_end < period_start:
        raise ValueError("period_end must not be earlier than period_start")

    user_timezone = await _resolve_user_timezone(db, user_id)
    normalized_start, normalized_end, _, _ = _normalize_snapshot_period_bounds(
        user_timezone, period_start, period_end
    )
    resolved_tree_id = _resolve_tree_id_from_sources(
        tree_id, [entry[0] for entry in entries_payload]
    )
    if snapshot.tree_id != resolved_tree_id:
        raise FinanceError("Cashflow snapshot does not exist")
    duplicate = await _find_existing_snapshot(
        db, user_id, normalized_start, normalized_end, resolved_tree_id
    )
    if duplicate and duplicate.id != snapshot.id:
        raise FinanceError("Another cashflow snapshot already exists for this period")

    resolved_currency = (primary_currency or snapshot.primary_currency).upper()
    normalized_entries = _normalize_cashflow_entries_payload(entries_payload)
    resolved_entries = [
        (
            source,
            amount,
            entry_note,
            _resolve_entry_currency(source, entry_currency, resolved_currency),
        )
        for source, amount, entry_note, entry_currency in normalized_entries
    ]
    snapshot_ts = _resolve_snapshot_ts(normalized_end)
    if exchange_rates_payload:
        rate_map = build_exchange_rate_map(exchange_rates_payload)
        rate_map.pop(resolved_currency, None)
        ensure_rates_for_currencies(
            primary_currency=resolved_currency,
            currencies=[entry_currency for _, _, _, entry_currency in resolved_entries],
            rate_map=rate_map,
        )
    else:
        _, rate_map, _, _ = await build_rate_snapshot_map(
            db,
            user_id=user_id,
            primary_currency=resolved_currency,
            currencies=[entry_currency for _, _, _, entry_currency in resolved_entries],
            effective_at=snapshot_ts,
        )

    snapshot.primary_currency = resolved_currency
    snapshot.exchange_rates = (
        {key: to_json_number(rate) for key, rate in rate_map.items()}
        if rate_map
        else None
    )
    snapshot.period_start = normalized_start
    snapshot.period_end = normalized_end
    snapshot.note = note
    snapshot.snapshot_ts = snapshot_ts

    await db.execute(
        delete(CashflowSnapshotEntry).where(
            CashflowSnapshotEntry.snapshot_id == snapshot.id
        )
    )

    total_positive = Decimal("0")
    total_negative = Decimal("0")
    income_breakdown: Dict[str, object] = {}
    expense_breakdown: Dict[str, object] = {}

    for source, amount, entry_note, entry_currency in resolved_entries:
        if source.is_rollup:
            raise FinanceError("Rollup sources cannot accept direct snapshot amounts")
        normalized_amount = amount.quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)
        resolved_entry_currency = entry_currency
        converted_amount = normalized_amount
        if resolved_entry_currency != resolved_currency:
            converted_amount = (
                normalized_amount * rate_map[resolved_entry_currency]
            ).quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)
        if converted_amount >= 0:
            total_positive += converted_amount
            income_breakdown[str(source.id)] = to_json_number(converted_amount)
        else:
            total_negative += converted_amount
            expense_breakdown[str(source.id)] = to_json_number(-converted_amount)

        db.add(
            CashflowSnapshotEntry(
                snapshot_id=snapshot.id,
                source_id=source.id,
                amount=normalized_amount,
                currency_code=resolved_entry_currency,
                note=entry_note,
                is_auto_generated=False,
            )
        )

    billing_summary = (
        snapshot.summary.get("billing_cycles") if snapshot.summary else None
    )
    snapshot.summary = {
        "income": income_breakdown,
        "expense": expense_breakdown,
        **({"billing_cycles": billing_summary} if billing_summary else {}),
    }
    snapshot.total_positive = total_positive.quantize(EIGHT_PLACES)
    snapshot.total_negative = total_negative.quantize(EIGHT_PLACES)
    snapshot.total_income = total_positive.quantize(EIGHT_PLACES)
    snapshot.total_expense = (-total_negative).quantize(EIGHT_PLACES)
    snapshot.net_cashflow = (total_positive + total_negative).quantize(EIGHT_PLACES)

    await commit_safely(db)
    await db.refresh(snapshot)
    return snapshot


async def delete_cashflow_snapshot(
    db: AsyncSession,
    user_id: UUID,
    snapshot_id: UUID,
) -> None:
    snapshot = await db.get(CashflowSnapshot, snapshot_id)
    if not snapshot or snapshot.user_id != user_id:
        raise FinanceError("Cashflow snapshot does not exist")

    await db.delete(snapshot)
    await commit_safely(db)


async def _build_cashflow_snapshot_query(
    db: AsyncSession,
    *,
    user_id: UUID,
    tree_id: Optional[UUID],
    start_time: Optional[datetime],
    end_time: Optional[datetime],
):
    tree = await resolve_cashflow_tree(db, user_id, tree_id)
    stmt = select(CashflowSnapshot).where(
        CashflowSnapshot.user_id == user_id, CashflowSnapshot.tree_id == tree.id
    )
    if start_time:
        stmt = stmt.where(CashflowSnapshot.period_start >= start_time)
    if end_time:
        stmt = stmt.where(CashflowSnapshot.period_start <= end_time)
    return stmt


async def list_cashflow_snapshots(
    db: AsyncSession,
    user_id: UUID,
    *,
    tree_id: Optional[UUID],
    skip: int = 0,
    offset: Optional[int] = None,
    limit: int = 20,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> List[CashflowSnapshot]:
    stmt = await _build_cashflow_snapshot_query(
        db,
        user_id=user_id,
        tree_id=tree_id,
        start_time=start_time,
        end_time=end_time,
    )
    effective_offset = offset if offset is not None else skip
    stmt = stmt.order_by(CashflowSnapshot.period_start.desc()).offset(effective_offset)
    if limit and limit > 0:
        stmt = stmt.limit(limit)
    return (await db.execute(stmt)).scalars().all()


async def list_cashflow_snapshots_with_total(
    db: AsyncSession,
    user_id: UUID,
    *,
    tree_id: Optional[UUID],
    skip: int = 0,
    offset: Optional[int] = None,
    limit: int = 20,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> Tuple[List[CashflowSnapshot], int]:
    stmt = await _build_cashflow_snapshot_query(
        db,
        user_id=user_id,
        tree_id=tree_id,
        start_time=start_time,
        end_time=end_time,
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    effective_offset = offset if offset is not None else skip
    stmt = stmt.order_by(CashflowSnapshot.period_start.desc()).offset(effective_offset)
    if limit and limit > 0:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    total = await db.scalar(count_stmt)
    return result.scalars().all(), int(total or 0)


async def get_cashflow_snapshot_detail(
    db: AsyncSession,
    user_id: UUID,
    snapshot_id: UUID,
    *,
    tree_id: Optional[UUID] = None,
) -> Tuple[CashflowSnapshot, List[Tuple[CashflowSnapshotEntry, CashflowSource]],]:
    snapshot = await db.get(CashflowSnapshot, snapshot_id)
    if not snapshot or snapshot.user_id != user_id:
        raise FinanceError("Cashflow snapshot does not exist")
    if tree_id and snapshot.tree_id != tree_id:
        raise FinanceError("Cashflow snapshot does not exist")

    stmt = (
        select(CashflowSnapshotEntry, CashflowSource)
        .join(CashflowSource, CashflowSnapshotEntry.source_id == CashflowSource.id)
        .where(CashflowSnapshotEntry.snapshot_id == snapshot_id)
    )
    rows = (await db.execute(stmt)).all()
    return snapshot, rows


async def compare_cashflow_snapshots(
    db: AsyncSession,
    user_id: UUID,
    base_snapshot_id: UUID,
    compare_snapshot_id: UUID,
    *,
    tree_id: Optional[UUID] = None,
) -> Tuple[
    CashflowSnapshot,
    CashflowSnapshot,
    Dict[UUID, CashflowSnapshotEntry],
    Dict[UUID, CashflowSnapshotEntry],
    Dict[UUID, CashflowSource],
]:
    base_snapshot = await db.get(CashflowSnapshot, base_snapshot_id)
    compare_snapshot = await db.get(CashflowSnapshot, compare_snapshot_id)
    if (
        not base_snapshot
        or not compare_snapshot
        or base_snapshot.user_id != user_id
        or compare_snapshot.user_id != user_id
    ):
        raise FinanceError("Cashflow snapshot does not exist")
    if tree_id and (
        base_snapshot.tree_id != tree_id or compare_snapshot.tree_id != tree_id
    ):
        raise FinanceError("Cashflow snapshot does not exist")
    if base_snapshot.tree_id != compare_snapshot.tree_id:
        raise FinanceError("Cashflow snapshot does not exist")

    base_stmt = select(CashflowSnapshotEntry).where(
        CashflowSnapshotEntry.snapshot_id == base_snapshot.id
    )
    compare_stmt = select(CashflowSnapshotEntry).where(
        CashflowSnapshotEntry.snapshot_id == compare_snapshot.id
    )
    base_entries = (await db.execute(base_stmt)).scalars().all()
    compare_entries = (await db.execute(compare_stmt)).scalars().all()

    source_ids = {entry.source_id for entry in base_entries} | {
        entry.source_id for entry in compare_entries
    }
    if source_ids:
        sources = (
            (
                await db.execute(
                    select(CashflowSource).where(CashflowSource.id.in_(source_ids))
                )
            )
            .scalars()
            .all()
        )
    else:
        sources = []
    source_map = {source.id: source for source in sources}

    return (
        base_snapshot,
        compare_snapshot,
        {entry.source_id: entry for entry in base_entries},
        {entry.source_id: entry for entry in compare_entries},
        source_map,
    )


async def list_billing_months(
    db: AsyncSession,
    user_id: UUID,
    *,
    source_id: UUID,
    limit: int,
    offset: int = 0,
    before: Optional[date] = None,
    after: Optional[date] = None,
    direction: str = "desc",
) -> Tuple[List[date], int]:
    source = await _load_source(db, user_id, source_id)
    if not source:
        raise CashflowSourceNotFoundError("Cashflow source does not exist")

    base_filters = (
        CashflowBillingEntry.user_id == user_id,
        CashflowBillingEntry.source_id == source_id,
        CashflowBillingEntry.posted_month.isnot(None),
    )
    stmt = select(CashflowBillingEntry.posted_month).where(*base_filters)
    if before is not None:
        stmt = stmt.where(CashflowBillingEntry.posted_month < before)
    if after is not None:
        stmt = stmt.where(CashflowBillingEntry.posted_month > after)

    order_clause = (
        CashflowBillingEntry.posted_month.asc()
        if direction.lower() == "asc"
        else CashflowBillingEntry.posted_month.desc()
    )
    stmt = (
        stmt.distinct()
        .order_by(order_clause)
        .offset(max(0, offset))
        .limit(max(1, min(limit, 120)))
    )
    total_stmt = select(func.count(CashflowBillingEntry.posted_month.distinct())).where(
        *base_filters
    )
    if before is not None:
        total_stmt = total_stmt.where(CashflowBillingEntry.posted_month < before)
    if after is not None:
        total_stmt = total_stmt.where(CashflowBillingEntry.posted_month > after)

    rows = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(total_stmt)).scalar_one()
    return [row for row in rows if row is not None], int(total or 0)


async def apply_billing_cycles(
    db: AsyncSession,
    user_id: UUID,
    *,
    tree_id: Optional[UUID],
    month: date,
    source_ids: Optional[List[UUID]],
    primary_currency: str,
) -> CashflowSnapshot:
    month_start, month_end = _month_bounds(month)
    tree = await resolve_cashflow_tree(db, user_id, tree_id)
    stmt = select(CashflowSource).where(
        CashflowSource.user_id == user_id,
        CashflowSource.tree_id == tree.id,
        CashflowSource.deleted_at.is_(None),
        CashflowSource.kind == "billing",
    )
    if source_ids:
        stmt = stmt.where(CashflowSource.id.in_(source_ids))
    sources = (await db.execute(stmt)).scalars().all()
    if source_ids:
        found_ids = {source.id for source in sources}
        missing = [value for value in source_ids if value not in found_ids]
        if missing:
            raise FinanceError("Cashflow source does not exist")

    user_timezone = await _resolve_user_timezone(db, user_id)
    snapshot = await _get_or_create_month_snapshot(
        db,
        user_id,
        primary_currency,
        month_start,
        month_end,
        tree.id,
        user_timezone=user_timezone,
    )
    billing_summary = (
        snapshot.summary.get("billing_cycles", {}) if snapshot.summary else {}
    )

    for source in sources:
        if source.billing_requires_manual_input:
            continue
        cycles = _calculate_cycles_for_month(source, month_start)
        if not cycles:
            continue

        entries_stmt = select(CashflowBillingEntry).where(
            CashflowBillingEntry.user_id == user_id,
            CashflowBillingEntry.source_id == source.id,
        )
        existing_entries = {
            (entry.cycle_start, entry.cycle_end): entry
            for entry in (await db.execute(entries_stmt)).scalars().all()
        }

        total_amount = Decimal("0")
        cycle_summary: List[Dict[str, object]] = []
        for cycle_start, cycle_end in cycles:
            posted_month = _normalize_posted_month(source, cycle_start, cycle_end)
            if posted_month != month_start:
                continue
            entry = existing_entries.get((cycle_start, cycle_end))
            if entry is None:
                if source.billing_default_amount is None:
                    continue
                entry = CashflowBillingEntry(
                    user_id=user_id,
                    source_id=source.id,
                    cycle_start=cycle_start,
                    cycle_end=cycle_end,
                    posted_month=posted_month,
                    amount=source.billing_default_amount.quantize(
                        EIGHT_PLACES, rounding=ROUND_HALF_UP
                    ),
                    note=source.billing_default_note,
                    auto_generated=True,
                )
                db.add(entry)
                existing_entries[(cycle_start, cycle_end)] = entry
            else:
                entry.auto_generated = True
                if source.billing_default_note:
                    entry.note = source.billing_default_note
                if source.billing_default_amount is not None and entry.auto_generated:
                    entry.amount = source.billing_default_amount.quantize(
                        EIGHT_PLACES, rounding=ROUND_HALF_UP
                    )
                entry.posted_month = posted_month

            total_amount += entry.amount
            cycle_summary.append(
                {
                    "cycle_start": cycle_start.isoformat(),
                    "cycle_end": cycle_end.isoformat(),
                    "amount": to_json_number(entry.amount),
                    "note": entry.note,
                    "auto_generated": bool(entry.auto_generated),
                }
            )

        if not cycle_summary:
            continue

        billing_summary[str(source.id)] = cycle_summary
        await _upsert_snapshot_entry(
            db,
            snapshot,
            source,
            total_amount,
            source.billing_default_note,
            auto_generated=True,
        )

    await _recalculate_snapshot_totals(db, snapshot, billing_summary=billing_summary)
    await commit_safely(db)
    await db.refresh(snapshot)
    return snapshot


async def get_billing_cycle_history(
    db: AsyncSession,
    user_id: UUID,
    *,
    source_id: UUID,
    month: date,
) -> List[Dict[str, object]]:
    source = await _load_source(db, user_id, source_id)
    if not source or source.kind != "billing":
        raise FinanceError("Source is not configured as a billing type")

    month_start, _ = _month_bounds(month)
    cycles = _calculate_cycles_for_month(source, month_start)
    entries_stmt = select(CashflowBillingEntry).where(
        CashflowBillingEntry.user_id == user_id,
        CashflowBillingEntry.source_id == source_id,
        CashflowBillingEntry.posted_month == month_start,
    )
    entries = {
        (entry.cycle_start, entry.cycle_end): entry
        for entry in (await db.execute(entries_stmt)).scalars().all()
    }

    history: List[Dict[str, object]] = []
    for cycle_start, cycle_end in cycles:
        posted_month = _normalize_posted_month(source, cycle_start, cycle_end)
        if posted_month != month_start:
            continue
        entry = entries.get((cycle_start, cycle_end))
        history.append(
            {
                "cycle_start": cycle_start,
                "cycle_end": cycle_end,
                "posted_month": posted_month,
                "amount": entry.amount if entry else None,
                "note": entry.note if entry else None,
                "auto_generated": bool(entry.auto_generated) if entry else False,
            }
        )
    return history


async def get_billing_cycle_history_bulk(
    db: AsyncSession,
    user_id: UUID,
    *,
    source_id: UUID,
    months: Iterable[date],
) -> Dict[date, List[Dict[str, object]]]:
    unique_months: List[date] = []
    seen: set[date] = set()
    for month in months:
        month_start, _ = _month_bounds(month)
        if month_start not in seen:
            seen.add(month_start)
            unique_months.append(month_start)

    history_map: Dict[date, List[Dict[str, object]]] = {}
    for month_start in unique_months:
        history_map[month_start] = await get_billing_cycle_history(
            db,
            user_id,
            source_id=source_id,
            month=month_start,
        )
    return history_map


async def upsert_billing_cycle_entries(
    db: AsyncSession,
    user_id: UUID,
    *,
    source_id: UUID,
    month: date,
    entries: List[Tuple[date, date, Decimal, Optional[str]]],
    primary_currency: str,
) -> Tuple[CashflowSnapshot, List[Dict[str, object]]]:
    source = await _load_source(db, user_id, source_id)
    if not source or source.kind != "billing":
        raise FinanceError("Source is not configured as a billing type")

    month_start, month_end = _month_bounds(month)
    valid_cycles = {
        (cycle_start, cycle_end)
        for cycle_start, cycle_end in _calculate_cycles_for_month(source, month_start)
        if _normalize_posted_month(source, cycle_start, cycle_end) == month_start
    }

    entry_stmt = select(CashflowBillingEntry).where(
        CashflowBillingEntry.user_id == user_id,
        CashflowBillingEntry.source_id == source_id,
        CashflowBillingEntry.posted_month == month_start,
    )
    entry_map = {
        (entry.cycle_start, entry.cycle_end): entry
        for entry in (await db.execute(entry_stmt)).scalars().all()
    }

    for cycle_start, cycle_end, amount, note in entries:
        key = (cycle_start, cycle_end)
        if key not in valid_cycles:
            raise FinanceError("Billing cycle range is outside the target month")
        normalized_amount = amount.quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)
        entry = entry_map.get(key)
        if entry:
            entry.amount = normalized_amount
            entry.note = note
            entry.auto_generated = False
        else:
            entry = CashflowBillingEntry(
                user_id=user_id,
                source_id=source_id,
                cycle_start=cycle_start,
                cycle_end=cycle_end,
                posted_month=month_start,
                amount=normalized_amount,
                note=note,
                auto_generated=False,
            )
            db.add(entry)
            entry_map[key] = entry

    user_timezone = await _resolve_user_timezone(db, user_id)
    snapshot = await _get_or_create_month_snapshot(
        db,
        user_id,
        primary_currency,
        month_start,
        month_end,
        source.tree_id,
        user_timezone=user_timezone,
    )

    total_amount = Decimal("0")
    cycle_summary: List[Dict[str, object]] = []
    for cycle_start, cycle_end in sorted(valid_cycles):
        entry = entry_map.get((cycle_start, cycle_end))
        amount_value = entry.amount if entry else Decimal("0")
        total_amount += amount_value
        cycle_summary.append(
            {
                "cycle_start": cycle_start.isoformat(),
                "cycle_end": cycle_end.isoformat(),
                "amount": to_json_number(amount_value) if entry else None,
                "note": entry.note if entry else None,
                "auto_generated": bool(entry.auto_generated) if entry else False,
            }
        )

    billing_summary = (
        snapshot.summary.get("billing_cycles", {}) if snapshot.summary else {}
    )
    billing_summary[str(source.id)] = cycle_summary

    await _upsert_snapshot_entry(db, snapshot, source, total_amount, None)
    await _recalculate_snapshot_totals(db, snapshot, billing_summary=billing_summary)
    await commit_safely(db)
    await db.refresh(snapshot)

    history = await get_billing_cycle_history(
        db,
        user_id,
        source_id=source_id,
        month=month_start,
    )
    return snapshot, history


__all__ = [
    "apply_billing_cycles",
    "compare_cashflow_snapshots",
    "create_cashflow_snapshot",
    "create_cashflow_source",
    "delete_cashflow_snapshot",
    "delete_cashflow_source",
    "get_billing_cycle_history",
    "get_billing_cycle_history_bulk",
    "get_cashflow_snapshot_detail",
    "list_billing_months",
    "list_cashflow_snapshots",
    "list_cashflow_snapshots_with_total",
    "list_cashflow_sources",
    "update_cashflow_snapshot",
    "update_cashflow_source",
    "upsert_billing_cycle_entries",
]
