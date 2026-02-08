"""Finance balance snapshot API routes."""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.config import settings
from app.db.models.finance_accounts import FinanceAccount
from app.db.models.finance_balance_snapshots import FinanceSnapshotEntry
from app.db.models.user import User
from app.handlers import finance_balance_snapshots as balance_service
from app.handlers.finance_common import (
    DuplicateExchangeRateError,
    EmptySnapshotPayloadError,
    FinanceError,
    MissingExchangeRateError,
    from_json_number,
)
from app.handlers.user_preferences import get_finance_primary_currency
from app.schemas.finance_balance_snapshots import (
    AccountSnapshotResponse,
    BalanceSnapshotAccountChange,
    BalanceSnapshotComparisonResponse,
    BalanceSnapshotCreateRequest,
    BalanceSnapshotDetailResponse,
    BalanceSnapshotListResponse,
    BalanceSnapshotSummaryResponse,
    BalanceSnapshotUpdateRequest,
    ExchangeRateSnapshotResponse,
    SnapshotMetricResponse,
)

router = StrictAPIRouter(prefix="/finance/balance-snapshots", tags=["finance-balance"])


async def _get_accounts_map(
    db: AsyncSession, user_id: UUID, account_ids: List[UUID], *, tree_id: Optional[UUID]
) -> Dict[UUID, FinanceAccount]:
    stmt = (
        select(FinanceAccount)
        .where(
            FinanceAccount.user_id == user_id,
            FinanceAccount.deleted_at.is_(None),
        )
        .order_by(FinanceAccount.created_at.asc())
    )
    if tree_id:
        stmt = stmt.where(FinanceAccount.tree_id == tree_id)
    if account_ids:
        stmt = stmt.where(FinanceAccount.id.in_(account_ids))
    accounts = (await db.execute(stmt)).scalars().all()
    return {account.id: account for account in accounts}


def _convert_metrics(summary: Dict[str, object]) -> SnapshotMetricResponse:
    total_assets = from_json_number(summary.get("total_assets", 0))
    total_liabilities = from_json_number(summary.get("total_liabilities", 0))
    net_worth = from_json_number(summary.get("net_worth", 0))

    by_type_raw = summary.get("by_type") or {}
    if not isinstance(by_type_raw, dict):
        by_type_raw = {}
    asset_breakdown = {
        key: from_json_number(value) for key, value in by_type_raw.items()
    }

    by_currency_raw = summary.get("by_currency") or {}
    if not isinstance(by_currency_raw, dict):
        by_currency_raw = {}
    currency_breakdown = {
        key: from_json_number(value) for key, value in by_currency_raw.items()
    }

    return SnapshotMetricResponse(
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        net_worth=net_worth,
        asset_breakdown=asset_breakdown or None,
        currency_breakdown=currency_breakdown or None,
    )


@router.post(
    "",
    response_model=BalanceSnapshotDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_balance_snapshot(
    payload: BalanceSnapshotCreateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> BalanceSnapshotDetailResponse:
    user_primary_currency = await get_finance_primary_currency(
        db, user_id=current_user.id
    )
    primary_currency = payload.primary_currency or user_primary_currency

    account_ids = [entry.account_id for entry in payload.accounts]
    accounts_map = await _get_accounts_map(
        db, current_user.id, account_ids, tree_id=payload.tree_id
    )
    missing_accounts = [aid for aid in account_ids if aid not in accounts_map]
    if missing_accounts:
        raise HTTPException(status_code=404, detail="账户不存在或已删除")

    accounts_payload = [
        (accounts_map[item.account_id], item.balance, item.note)
        for item in payload.accounts
    ]
    exchange_rates_payload = [
        (item.quote_currency, item.rate) for item in payload.exchange_rates
    ]

    try:
        snapshot = await balance_service.create_balance_snapshot(
            db,
            current_user.id,
            tree_id=payload.tree_id,
            primary_currency=primary_currency,
            accounts_payload=accounts_payload,
            exchange_rates_payload=exchange_rates_payload,
            note=payload.note,
            snapshot_ts=payload.snapshot_ts,
        )
    except MissingExchangeRateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except DuplicateExchangeRateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except EmptySnapshotPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover
        if settings.debug:
            raise
        raise HTTPException(
            status_code=500, detail="Failed to create snapshot"
        ) from exc

    detail_snapshot, entries = await balance_service.get_snapshot_detail(
        db, current_user.id, snapshot.id, tree_id=payload.tree_id
    )
    return _build_snapshot_detail_response(detail_snapshot, entries)


@router.patch(
    "/{snapshot_id}",
    response_model=BalanceSnapshotDetailResponse,
)
async def update_balance_snapshot(
    snapshot_id: UUID,
    payload: BalanceSnapshotUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> BalanceSnapshotDetailResponse:
    account_ids = [entry.account_id for entry in payload.accounts]
    accounts_map = await _get_accounts_map(
        db, current_user.id, account_ids, tree_id=payload.tree_id
    )
    missing_accounts = [aid for aid in account_ids if aid not in accounts_map]
    if missing_accounts:
        raise HTTPException(status_code=404, detail="账户不存在或已删除")

    accounts_payload = [
        (accounts_map[entry.account_id], entry.balance, entry.note)
        for entry in payload.accounts
    ]
    exchange_rates_payload = [
        (item.quote_currency, item.rate) for item in payload.exchange_rates
    ]

    try:
        snapshot = await balance_service.update_balance_snapshot(
            db,
            current_user.id,
            snapshot_id,
            tree_id=payload.tree_id,
            primary_currency=payload.primary_currency,
            accounts_payload=accounts_payload,
            exchange_rates_payload=exchange_rates_payload,
            note=payload.note,
            snapshot_ts=payload.snapshot_ts,
        )
    except MissingExchangeRateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except DuplicateExchangeRateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except EmptySnapshotPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FinanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # pragma: no cover
        if settings.debug:
            raise
        raise HTTPException(
            status_code=500, detail="Failed to update snapshot"
        ) from exc

    detail_snapshot, entries = await balance_service.get_snapshot_detail(
        db, current_user.id, snapshot.id, tree_id=payload.tree_id
    )
    return _build_snapshot_detail_response(detail_snapshot, entries)


@router.delete(
    "/{snapshot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_balance_snapshot(
    snapshot_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        await balance_service.soft_delete_snapshot(db, current_user.id, snapshot_id)
    except FinanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("", response_model=BalanceSnapshotListResponse)
async def list_balance_snapshots(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tree_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> BalanceSnapshotListResponse:
    offset = (page - 1) * size
    snapshots, total = await balance_service.list_balance_snapshots_with_total(
        db,
        current_user.id,
        tree_id=tree_id,
        skip=offset,
        limit=size,
    )
    response: List[BalanceSnapshotSummaryResponse] = []
    for snapshot in snapshots:
        metrics = _convert_metrics(snapshot.summary or {})
        response.append(
            BalanceSnapshotSummaryResponse(
                id=snapshot.id,
                snapshot_ts=snapshot.snapshot_ts.isoformat(),
                primary_currency=snapshot.primary_currency,
                tree_id=snapshot.tree_id,
                note=snapshot.note,
                metrics=metrics,
            )
        )
    pages = (total + size - 1) // size if size else 0
    return BalanceSnapshotListResponse(
        items=response,
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={
            "tree_id": tree_id,
        },
    )


@router.get(
    "/{snapshot_id}",
    response_model=BalanceSnapshotDetailResponse,
)
async def get_balance_snapshot(
    snapshot_id: UUID,
    tree_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> BalanceSnapshotDetailResponse:
    try:
        snapshot, entries = await balance_service.get_snapshot_detail(
            db, current_user.id, snapshot_id, tree_id=tree_id
        )
    except FinanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _build_snapshot_detail_response(snapshot, entries)


@router.get(
    "/{snapshot_id}/compare/{other_id}",
    response_model=BalanceSnapshotComparisonResponse,
)
async def compare_balance_snapshots(
    snapshot_id: UUID,
    other_id: UUID,
    tree_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> BalanceSnapshotComparisonResponse:
    (
        base_snapshot,
        compare_snapshot,
        base_map,
        compare_map,
        account_map,
    ) = await balance_service.compare_snapshots(
        db, current_user.id, snapshot_id, other_id, tree_id=tree_id
    )

    account_ids = set(base_map) | set(compare_map)
    changes: List[BalanceSnapshotAccountChange] = []
    for account_id in account_ids:
        previous = base_map.get(account_id)
        current = compare_map.get(account_id)
        prev_value = (
            Decimal(str(previous.balance_converted)) if previous else Decimal("0")
        )
        current_value = (
            Decimal(str(current.balance_converted)) if current else Decimal("0")
        )
        delta = current_value - prev_value
        delta_percent: Optional[Decimal]
        if prev_value == 0:
            delta_percent = None
        else:
            delta_percent = (delta / prev_value * Decimal("100")).quantize(
                Decimal("0.0001"),
            )
        account = account_map.get(account_id)
        name = account.name if account else "Unknown"
        currency = (
            account.currency_code
            if account
            else (
                previous.currency_code
                if previous
                else current.currency_code
                if current
                else ""
            )
        )
        account_type = (
            account.type
            if account
            else (
                previous.account.type if previous else current.account.type if current else "asset"  # type: ignore[attr-defined]
            )
        )
        changes.append(
            BalanceSnapshotAccountChange(
                account_id=account_id,
                account_name=name,
                currency_code=currency,
                type=account_type,
                previous_balance=prev_value,
                current_balance=current_value,
                delta=delta,
                delta_percent=delta_percent,
            )
        )

    base_metrics = _convert_metrics(base_snapshot.summary or {})
    compare_metrics = _convert_metrics(compare_snapshot.summary or {})
    delta_net_worth = compare_metrics.net_worth - base_metrics.net_worth

    return BalanceSnapshotComparisonResponse(
        base_snapshot_id=base_snapshot.id,
        compare_snapshot_id=compare_snapshot.id,
        base_snapshot_ts=base_snapshot.snapshot_ts.isoformat(),
        compare_snapshot_ts=compare_snapshot.snapshot_ts.isoformat(),
        delta_net_worth=delta_net_worth,
        base_metrics=base_metrics,
        compare_metrics=compare_metrics,
        account_changes=changes,
    )


def _build_snapshot_detail_response(
    snapshot,
    rows: List[Tuple[FinanceSnapshotEntry, FinanceAccount]],
) -> BalanceSnapshotDetailResponse:
    metrics = _convert_metrics(snapshot.summary or {})
    accounts_response: List[AccountSnapshotResponse] = []
    for entry, account in rows:
        accounts_response.append(
            AccountSnapshotResponse(
                account_id=entry.account_id,
                account_name=account.name,
                type=account.type,
                currency_code=entry.currency_code,
                balance_raw=Decimal(str(entry.balance_original)),
                balance_converted=Decimal(str(entry.balance_converted)),
                path=account.path,
                depth=account.depth,
                note=entry.note,
            )
        )

    exchange_rates = []
    for currency, rate in (snapshot.exchange_rates or {}).items():
        rate_value = from_json_number(rate)
        exchange_rates.append(
            ExchangeRateSnapshotResponse(
                id=f"{snapshot.id}-{currency}",
                quote_currency=currency,
                rate=rate_value,
            )
        )

    return BalanceSnapshotDetailResponse(
        id=snapshot.id,
        snapshot_ts=snapshot.snapshot_ts.isoformat(),
        primary_currency=snapshot.primary_currency,
        tree_id=snapshot.tree_id,
        note=snapshot.note,
        metrics=metrics,
        accounts=accounts_response,
        exchange_rates=exchange_rates,
    )


__all__ = ["router"]
