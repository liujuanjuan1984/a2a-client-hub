"""Handlers for finance balance snapshots and exchange rates."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.finance_accounts import FinanceAccount
from app.db.models.finance_balance_snapshots import (
    FinanceSnapshot,
    FinanceSnapshotEntry,
)
from app.db.transaction import commit_safely
from app.handlers import finance_exchange_rates as exchange_service
from app.handlers.finance_account_trees import resolve_account_tree
from app.handlers.finance_common import (
    EIGHT_PLACES,
    EmptySnapshotPayloadError,
    FinanceError,
    MissingExchangeRateError,
    from_json_number,
    to_json_number,
)
from app.handlers.finance_exchange_rate_utils import (
    build_exchange_rate_map,
    ensure_rates_for_currencies,
)
from app.handlers.finance_rate_snapshots import collect_rates_to_primary
from app.utils.timezone_util import utc_now


def _calculate_snapshot_state(
    *,
    primary_currency: str,
    rates: Dict[str, Decimal],
    accounts_payload: List[Tuple[FinanceAccount, Decimal, Optional[str]]],
) -> Tuple[
    List[Tuple[str, FinanceAccount, Decimal, Decimal, Optional[str]]],
    Dict[str, object],
    Optional[Dict[str, float]],
]:
    if not accounts_payload:
        raise EmptySnapshotPayloadError("至少需要一个账户余额")

    currencies = {account.currency_code for account, _, _ in accounts_payload}
    ensure_rates_for_currencies(
        primary_currency=primary_currency,
        currencies=currencies,
        rate_map=rates,
    )

    total_assets = Decimal("0")
    total_liabilities = Decimal("0")
    by_type: Dict[str, Decimal] = {}
    by_currency: Dict[str, Decimal] = {}
    entry_payloads: List[
        Tuple[str, FinanceAccount, Decimal, Decimal, Optional[str]]
    ] = []

    for account, raw_balance, account_note in accounts_payload:
        balance = raw_balance.quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)
        currency_code = account.currency_code.upper()
        if currency_code == primary_currency:
            converted = balance
        else:
            rate = rates.get(currency_code)
            if rate is None:
                raise MissingExchangeRateError(
                    f"缺少 {currency_code} 对 {primary_currency} 的汇率"
                )
            converted = (balance * rate).quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)

        if converted > 0:
            total_assets += converted
        elif converted < 0:
            total_liabilities += converted

        by_type[account.type] = by_type.get(account.type, Decimal("0")) + converted
        by_currency[currency_code] = (
            by_currency.get(currency_code, Decimal("0")) + balance
        )

        entry_payloads.append(
            (currency_code, account, balance, converted, account_note)
        )

    net_worth = total_assets + total_liabilities
    summary = {
        "total_assets": to_json_number(total_assets),
        "total_liabilities": to_json_number(total_liabilities),
        "net_worth": to_json_number(net_worth),
        "by_type": {k: to_json_number(v) for k, v in by_type.items()},
        "by_currency": {k: to_json_number(v) for k, v in by_currency.items()},
    }
    exchange_rates_json = (
        {k: to_json_number(v) for k, v in rates.items()} if rates else None
    )

    return entry_payloads, summary, exchange_rates_json


def _resolve_tree_id_from_accounts(
    tree_id: Optional[UUID], accounts: List[FinanceAccount]
) -> UUID:
    if tree_id:
        if any(account.tree_id != tree_id for account in accounts):
            raise FinanceError("账户不属于当前账户树")
        return tree_id
    if not accounts:
        raise FinanceError("无法确定账户树")
    inferred = accounts[0].tree_id
    if any(account.tree_id != inferred for account in accounts):
        raise FinanceError("账户不属于同一账户树")
    return inferred


async def _build_balance_snapshots_query(
    db: AsyncSession,
    *,
    user_id: UUID,
    tree_id: Optional[UUID],
):
    tree = await resolve_account_tree(db, user_id, tree_id)
    return select(FinanceSnapshot).where(
        FinanceSnapshot.user_id == user_id,
        FinanceSnapshot.tree_id == tree.id,
        FinanceSnapshot.deleted_at.is_(None),
    )


async def create_balance_snapshot(
    db: AsyncSession,
    user_id: UUID,
    *,
    tree_id: Optional[UUID],
    primary_currency: str,
    accounts_payload: List[Tuple[FinanceAccount, Decimal, Optional[str]]],
    exchange_rates_payload: List[Tuple[str, Decimal]],
    note: Optional[str],
    snapshot_ts: Optional[datetime],
) -> FinanceSnapshot:
    primary_currency = primary_currency.upper()
    if exchange_rates_payload:
        rates = build_exchange_rate_map(exchange_rates_payload)
        rates.pop(primary_currency, None)
    else:
        effective_at = snapshot_ts or utc_now()
        resolver = exchange_service.ExchangeRateResolver(
            db,
            user_id,
            effective_at=effective_at,
        )
        rates = await collect_rates_to_primary(
            resolver,
            primary_currency=primary_currency,
            currencies={account.currency_code for account, _, _ in accounts_payload},
        )

    entry_payloads, summary, exchange_rates_json = _calculate_snapshot_state(
        primary_currency=primary_currency,
        rates=rates,
        accounts_payload=accounts_payload,
    )
    resolved_tree_id = _resolve_tree_id_from_accounts(
        tree_id, [account for account, _, _ in accounts_payload]
    )

    snapshot = FinanceSnapshot(
        user_id=user_id,
        tree_id=resolved_tree_id,
        primary_currency=primary_currency,
        note=note,
        summary=summary,
        exchange_rates=exchange_rates_json,
        snapshot_ts=snapshot_ts,
    )
    db.add(snapshot)
    await db.flush()

    for currency_code, account, balance, converted, account_note in entry_payloads:
        entry = FinanceSnapshotEntry(
            snapshot_id=snapshot.id,
            account_id=account.id,
            balance_original=balance,
            currency_code=currency_code,
            balance_converted=converted,
            note=account_note,
        )
        db.add(entry)

    await commit_safely(db)
    await db.refresh(snapshot)
    return snapshot


async def update_balance_snapshot(
    db: AsyncSession,
    user_id: UUID,
    snapshot_id: UUID,
    *,
    tree_id: Optional[UUID],
    primary_currency: Optional[str],
    accounts_payload: List[Tuple[FinanceAccount, Decimal, Optional[str]]],
    exchange_rates_payload: List[Tuple[str, Decimal]],
    note: Optional[str],
    snapshot_ts: Optional[datetime],
) -> FinanceSnapshot:
    stmt = (
        select(FinanceSnapshot)
        .where(
            FinanceSnapshot.id == snapshot_id,
            FinanceSnapshot.user_id == user_id,
            FinanceSnapshot.deleted_at.is_(None),
        )
        .limit(1)
    )
    snapshot = (await db.execute(stmt)).scalars().first()
    if not snapshot:
        raise FinanceError("快照不存在")
    if tree_id and snapshot.tree_id != tree_id:
        raise FinanceError("快照不存在")

    resolved_currency = (primary_currency or snapshot.primary_currency).upper()
    if exchange_rates_payload:
        rates = build_exchange_rate_map(exchange_rates_payload)
        rates.pop(resolved_currency, None)
    else:
        effective_at = snapshot_ts or snapshot.snapshot_ts or utc_now()
        resolver = exchange_service.ExchangeRateResolver(
            db,
            user_id,
            effective_at=effective_at,
        )
        rates = await collect_rates_to_primary(
            resolver,
            primary_currency=resolved_currency,
            currencies={account.currency_code for account, _, _ in accounts_payload},
        )

    entry_payloads, summary, exchange_rates_json = _calculate_snapshot_state(
        primary_currency=resolved_currency,
        rates=rates,
        accounts_payload=accounts_payload,
    )
    resolved_tree_id = _resolve_tree_id_from_accounts(
        tree_id, [account for account, _, _ in accounts_payload]
    )
    if snapshot.tree_id != resolved_tree_id:
        raise FinanceError("快照不存在")

    snapshot.primary_currency = resolved_currency
    snapshot.note = note
    snapshot.summary = summary
    snapshot.exchange_rates = exchange_rates_json
    if snapshot_ts is not None:
        snapshot.snapshot_ts = snapshot_ts

    entries_stmt = select(FinanceSnapshotEntry).where(
        FinanceSnapshotEntry.snapshot_id == snapshot.id
    )
    existing_entries = {
        entry.account_id: entry
        for entry in (await db.execute(entries_stmt)).scalars().all()
    }
    seen_accounts: Set[UUID] = set()

    for currency_code, account, balance, converted, account_note in entry_payloads:
        entry = existing_entries.get(account.id)
        if entry:
            entry.balance_original = balance
            entry.currency_code = currency_code
            entry.balance_converted = converted
            entry.note = account_note
            entry.deleted_at = None
        else:
            entry = FinanceSnapshotEntry(
                snapshot_id=snapshot.id,
                account_id=account.id,
                balance_original=balance,
                currency_code=currency_code,
                balance_converted=converted,
                note=account_note,
            )
            db.add(entry)
        seen_accounts.add(account.id)

    for account_id, entry in existing_entries.items():
        if account_id not in seen_accounts:
            await db.delete(entry)

    await commit_safely(db)
    await db.refresh(snapshot)
    return snapshot


async def soft_delete_snapshot(
    db: AsyncSession,
    user_id: UUID,
    snapshot_id: UUID,
) -> None:
    stmt = (
        select(FinanceSnapshot)
        .where(
            FinanceSnapshot.id == snapshot_id,
            FinanceSnapshot.user_id == user_id,
            FinanceSnapshot.deleted_at.is_(None),
        )
        .limit(1)
    )
    snapshot = (await db.execute(stmt)).scalars().first()
    if not snapshot:
        raise FinanceError("快照不存在")

    snapshot.soft_delete()

    entries_stmt = select(FinanceSnapshotEntry).where(
        FinanceSnapshotEntry.snapshot_id == snapshot.id
    )
    entries = (await db.execute(entries_stmt)).scalars().all()
    for entry in entries:
        entry.soft_delete()

    await commit_safely(db)


async def list_balance_snapshots(
    db: AsyncSession,
    user_id: UUID,
    *,
    tree_id: Optional[UUID],
    skip: int = 0,
    limit: int = 20,
) -> List[FinanceSnapshot]:
    stmt = await _build_balance_snapshots_query(
        db,
        user_id=user_id,
        tree_id=tree_id,
    )
    stmt = stmt.order_by(FinanceSnapshot.snapshot_ts.desc()).offset(skip).limit(limit)
    return (await db.execute(stmt)).scalars().all()


async def list_balance_snapshots_with_total(
    db: AsyncSession,
    user_id: UUID,
    *,
    tree_id: Optional[UUID],
    skip: int = 0,
    limit: int = 20,
) -> Tuple[List[FinanceSnapshot], int]:
    stmt = await _build_balance_snapshots_query(
        db,
        user_id=user_id,
        tree_id=tree_id,
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    stmt = stmt.order_by(FinanceSnapshot.snapshot_ts.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    total = await db.scalar(count_stmt)
    return result.scalars().all(), int(total or 0)


async def get_snapshot_detail(
    db: AsyncSession,
    user_id: UUID,
    snapshot_id: UUID,
    *,
    tree_id: Optional[UUID] = None,
) -> Tuple[FinanceSnapshot, List[Tuple[FinanceSnapshotEntry, FinanceAccount]]]:
    stmt_snapshot = (
        select(FinanceSnapshot)
        .where(
            FinanceSnapshot.id == snapshot_id,
            FinanceSnapshot.user_id == user_id,
            FinanceSnapshot.deleted_at.is_(None),
        )
        .limit(1)
    )
    snapshot = (await db.execute(stmt_snapshot)).scalars().first()
    if not snapshot:
        raise FinanceError("快照不存在")
    if tree_id and snapshot.tree_id != tree_id:
        raise FinanceError("快照不存在")

    stmt_entries = (
        select(FinanceSnapshotEntry, FinanceAccount)
        .join(FinanceAccount, FinanceSnapshotEntry.account_id == FinanceAccount.id)
        .where(
            FinanceSnapshotEntry.snapshot_id == snapshot_id,
            FinanceSnapshotEntry.deleted_at.is_(None),
        )
    )
    entries = (await db.execute(stmt_entries)).all()
    return snapshot, entries


async def compare_snapshots(
    db: AsyncSession,
    user_id: UUID,
    base_snapshot_id: UUID,
    compare_snapshot_id: UUID,
    *,
    tree_id: Optional[UUID] = None,
) -> Tuple[
    FinanceSnapshot,
    FinanceSnapshot,
    Dict[UUID, FinanceSnapshotEntry],
    Dict[UUID, FinanceSnapshotEntry],
    Dict[UUID, FinanceAccount],
]:
    stmt_base = (
        select(FinanceSnapshot)
        .where(
            FinanceSnapshot.id == base_snapshot_id,
            FinanceSnapshot.user_id == user_id,
            FinanceSnapshot.deleted_at.is_(None),
        )
        .limit(1)
    )
    stmt_compare = (
        select(FinanceSnapshot)
        .where(
            FinanceSnapshot.id == compare_snapshot_id,
            FinanceSnapshot.user_id == user_id,
            FinanceSnapshot.deleted_at.is_(None),
        )
        .limit(1)
    )
    base_snapshot = (await db.execute(stmt_base)).scalars().first()
    compare_snapshot = (await db.execute(stmt_compare)).scalars().first()
    if not base_snapshot or not compare_snapshot:
        raise FinanceError("快照不存在")
    if base_snapshot.tree_id != compare_snapshot.tree_id:
        raise FinanceError("快照不存在")
    if tree_id and (
        base_snapshot.tree_id != tree_id or compare_snapshot.tree_id != tree_id
    ):
        raise FinanceError("快照不存在")

    base_entries_stmt = select(FinanceSnapshotEntry).where(
        FinanceSnapshotEntry.snapshot_id == base_snapshot.id,
        FinanceSnapshotEntry.deleted_at.is_(None),
    )
    compare_entries_stmt = select(FinanceSnapshotEntry).where(
        FinanceSnapshotEntry.snapshot_id == compare_snapshot.id,
        FinanceSnapshotEntry.deleted_at.is_(None),
    )
    base_entries = (await db.execute(base_entries_stmt)).scalars().all()
    compare_entries = (await db.execute(compare_entries_stmt)).scalars().all()
    account_ids = {entry.account_id for entry in base_entries} | {
        entry.account_id for entry in compare_entries
    }
    if account_ids:
        stmt_accounts = select(FinanceAccount).where(FinanceAccount.id.in_(account_ids))
        accounts = (await db.execute(stmt_accounts)).scalars().all()
    else:
        accounts = []
    account_map = {account.id: account for account in accounts}
    return (
        base_snapshot,
        compare_snapshot,
        {entry.account_id: entry for entry in base_entries},
        {entry.account_id: entry for entry in compare_entries},
        account_map,
    )


async def get_latest_exchange_rates(
    db: AsyncSession, user_id: UUID, *, tree_id: Optional[UUID]
) -> Tuple[Optional[FinanceSnapshot], Dict[str, Decimal]]:
    tree = await resolve_account_tree(db, user_id, tree_id)
    stmt = (
        select(FinanceSnapshot)
        .where(
            FinanceSnapshot.user_id == user_id,
            FinanceSnapshot.tree_id == tree.id,
            FinanceSnapshot.deleted_at.is_(None),
        )
        .order_by(FinanceSnapshot.snapshot_ts.desc())
        .limit(1)
    )
    snapshot = (await db.execute(stmt)).scalars().first()
    if not snapshot:
        return None, {}
    rates = snapshot.exchange_rates or {}
    return snapshot, {k: from_json_number(v) for k, v in rates.items()}


__all__ = [
    "_calculate_snapshot_state",
    "create_balance_snapshot",
    "update_balance_snapshot",
    "soft_delete_snapshot",
    "list_balance_snapshots",
    "list_balance_snapshots_with_total",
    "get_snapshot_detail",
    "compare_snapshots",
    "get_latest_exchange_rates",
]
