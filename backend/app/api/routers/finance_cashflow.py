"""Finance cashflow API routes."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.finance_cashflow import CashflowSnapshotEntry, CashflowSource
from app.db.models.user import User
from app.handlers import finance_cashflow as cashflow_service
from app.handlers import finance_cashflow_trees as cashflow_tree_service
from app.handlers.finance_common import (
    CashflowSourceNameConflictError,
    CashflowSourceNotFoundError,
    EmptySnapshotPayloadError,
    FinanceError,
    FinanceTreeDeleteForbiddenError,
    FinanceTreeNameConflictError,
    FinanceTreeNotEmptyError,
    FinanceTreeNotFoundError,
    MissingExchangeRateError,
)
from app.handlers.user_preferences import get_finance_primary_currency
from app.schemas.finance_cashflow import (
    BillingApplyRequest,
    BillingCycleHistoryBulkResponse,
    BillingCycleHistoryResponse,
    BillingCycleUpsertRequest,
    BillingMonthListResponse,
    CashflowSnapshotComparisonResponse,
    CashflowSnapshotCreateRequest,
    CashflowSnapshotDetailResponse,
    CashflowSnapshotEntryResponse,
    CashflowSnapshotExchangeRateResponse,
    CashflowSnapshotListResponse,
    CashflowSnapshotSourceChange,
    CashflowSnapshotSummaryResponse,
    CashflowSnapshotUpdateRequest,
    CashflowSourceCreate,
    CashflowSourceNode,
    CashflowSourceTreeCreate,
    CashflowSourceTreeItem,
    CashflowSourceTreeResponse,
    CashflowSourceTreeUpdate,
    CashflowSourceUpdate,
)

router = StrictAPIRouter(prefix="/finance/cashflow", tags=["finance-cashflow"])


async def _get_sources_map(
    db: AsyncSession,
    user_id: UUID,
    source_ids: List[UUID],
    *,
    tree_id: Optional[UUID],
) -> Dict[UUID, CashflowSource]:
    if not source_ids:
        return {}

    stmt = select(CashflowSource).where(
        CashflowSource.user_id == user_id,
        CashflowSource.deleted_at.is_(None),
        CashflowSource.id.in_(source_ids),
    )
    if tree_id:
        stmt = stmt.where(CashflowSource.tree_id == tree_id)
    rows = (await db.execute(stmt)).scalars().all()
    return {source.id: source for source in rows}


@router.get("/sources", response_model=CashflowSourceTreeResponse)
async def get_cashflow_sources(
    tree_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> CashflowSourceTreeResponse:
    sources = await cashflow_service.list_cashflow_sources(
        db=db, user_id=current_user.id, tree_id=tree_id
    )
    nodes = _build_cashflow_source_tree(sources)
    return CashflowSourceTreeResponse(sources=nodes)


@router.post(
    "/sources",
    response_model=CashflowSourceNode,
    status_code=status.HTTP_201_CREATED,
)
async def create_cashflow_source(
    payload: CashflowSourceCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> CashflowSourceNode:
    try:
        source = await cashflow_service.create_cashflow_source(
            db=db,
            user_id=current_user.id,
            name=payload.name,
            parent_id=payload.parent_id,
            tree_id=payload.tree_id,
            metadata=payload.metadata,
            sort_order=payload.sort_order,
            kind=payload.kind,
            currency_code=payload.currency_code,
            billing_cycle_type=payload.billing_cycle_type,
            billing_cycle_interval=payload.billing_cycle_interval,
            billing_anchor_day=payload.billing_anchor_day,
            billing_anchor_date=payload.billing_anchor_date,
            billing_post_to=payload.billing_post_to,
            billing_default_amount=payload.billing_default_amount,
            billing_default_note=payload.billing_default_note,
            billing_requires_manual_input=payload.billing_requires_manual_input,
        )
    except CashflowSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CashflowSourceNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return _build_cashflow_source_node(source)


@router.patch("/sources/{source_id}", response_model=CashflowSourceNode)
async def update_cashflow_source(
    source_id: UUID,
    payload: CashflowSourceUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> CashflowSourceNode:
    try:
        source = await cashflow_service.update_cashflow_source(
            db=db,
            user_id=current_user.id,
            source_id=source_id,
            name=payload.name,
            parent_id=payload.parent_id,
            metadata=payload.metadata,
            sort_order=payload.sort_order,
            kind=payload.kind,
            currency_code=payload.currency_code,
            billing_cycle_type=payload.billing_cycle_type,
            billing_cycle_interval=payload.billing_cycle_interval,
            billing_anchor_day=payload.billing_anchor_day,
            billing_anchor_date=payload.billing_anchor_date,
            billing_post_to=payload.billing_post_to,
            billing_default_amount=payload.billing_default_amount,
            billing_default_note=payload.billing_default_note,
            billing_requires_manual_input=payload.billing_requires_manual_input,
        )
    except CashflowSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CashflowSourceNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return _build_cashflow_source_node(source)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cashflow_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        await cashflow_service.delete_cashflow_source(
            db=db, user_id=current_user.id, source_id=source_id
        )
    except CashflowSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/trees", response_model=list[CashflowSourceTreeItem])
async def list_cashflow_trees(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> list[CashflowSourceTreeItem]:
    trees = await cashflow_tree_service.list_cashflow_trees(db, current_user.id)
    return [CashflowSourceTreeItem.model_validate(tree) for tree in trees]


@router.post(
    "/trees",
    response_model=CashflowSourceTreeItem,
    status_code=status.HTTP_201_CREATED,
)
async def create_cashflow_tree(
    payload: CashflowSourceTreeCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> CashflowSourceTreeItem:
    try:
        tree = await cashflow_tree_service.create_cashflow_tree(
            db,
            current_user.id,
            name=payload.name,
            is_default=bool(payload.is_default),
            display_order=payload.display_order,
        )
    except FinanceTreeNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return CashflowSourceTreeItem.model_validate(tree)


@router.patch("/trees/{tree_id}", response_model=CashflowSourceTreeItem)
async def update_cashflow_tree(
    tree_id: UUID,
    payload: CashflowSourceTreeUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> CashflowSourceTreeItem:
    try:
        tree = await cashflow_tree_service.update_cashflow_tree(
            db,
            current_user.id,
            tree_id,
            name=payload.name,
            is_default=payload.is_default,
            display_order=payload.display_order,
        )
    except FinanceTreeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FinanceTreeNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return CashflowSourceTreeItem.model_validate(tree)


@router.delete("/trees/{tree_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cashflow_tree(
    tree_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        await cashflow_tree_service.delete_cashflow_tree(
            db,
            current_user.id,
            tree_id,
        )
    except FinanceTreeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (FinanceTreeNotEmptyError, FinanceTreeDeleteForbiddenError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/billing/apply",
    response_model=CashflowSnapshotDetailResponse,
    status_code=status.HTTP_200_OK,
)
async def apply_billing_cycles(
    payload: BillingApplyRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> CashflowSnapshotDetailResponse:
    user_primary_currency = await get_finance_primary_currency(
        db, user_id=current_user.id
    )
    try:
        snapshot = await cashflow_service.apply_billing_cycles(
            db=db,
            user_id=current_user.id,
            tree_id=payload.tree_id,
            month=payload.month,
            source_ids=payload.source_ids,
            primary_currency=user_primary_currency,
        )
    except FinanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    snapshot, rows = await cashflow_service.get_cashflow_snapshot_detail(
        db=db,
        user_id=current_user.id,
        snapshot_id=snapshot.id,
        tree_id=payload.tree_id,
    )
    return _build_cashflow_snapshot_detail(snapshot, rows)


def _parse_month_string(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="month parameters must use YYYY-MM format"
        ) from exc
    return parsed.date().replace(day=1)


@router.get(
    "/billing/{source_id}/months",
    response_model=BillingMonthListResponse,
)
async def list_billing_months(
    source_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(6, ge=1, le=120, description="Page size"),
    before: Optional[str] = Query(None, description="Earlier than YYYY-MM"),
    after: Optional[str] = Query(None, description="Later than YYYY-MM"),
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> BillingMonthListResponse:
    direction_normalized = direction.lower()
    try:
        offset = (page - 1) * size
        months, total = await cashflow_service.list_billing_months(
            db=db,
            user_id=current_user.id,
            source_id=source_id,
            limit=size,
            offset=offset,
            before=_parse_month_string(before),
            after=_parse_month_string(after),
            direction=direction_normalized,
        )
    except CashflowSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    pages = (total + size - 1) // size if size else 0
    return BillingMonthListResponse(
        items=[month.strftime("%Y-%m") for month in months],
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={"source_id": source_id},
    )


@router.get(
    "/billing/{source_id}",
    response_model=BillingCycleHistoryResponse,
)
async def list_billing_cycle_history(
    source_id: UUID,
    month: str = Query(..., description="Natural month in YYYY-MM format"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> BillingCycleHistoryResponse:
    try:
        parsed_month = BillingApplyRequest(month=month).month
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        history = await cashflow_service.get_billing_cycle_history(
            db=db,
            user_id=current_user.id,
            source_id=source_id,
            month=parsed_month,
        )
    except FinanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return BillingCycleHistoryResponse(
        source_id=source_id,
        month=parsed_month,
        cycles=[
            {
                "cycle_start": item["cycle_start"],
                "cycle_end": item["cycle_end"],
                "posted_month": item["posted_month"],
                "amount": item["amount"],
                "note": item["note"],
                "auto_generated": item["auto_generated"],
            }
            for item in history
        ],
    )


@router.get(
    "/billing/{source_id}/history",
    response_model=BillingCycleHistoryBulkResponse,
)
async def list_billing_cycle_history_bulk(
    source_id: UUID,
    months: List[str] = Query(..., description="List of YYYY-MM months"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> BillingCycleHistoryBulkResponse:
    if not months:
        raise HTTPException(
            status_code=400, detail="months query parameter is required"
        )

    parsed_months: List[date] = []
    for value in months:
        try:
            parsed_months.append(BillingApplyRequest(month=value).month)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    try:
        history_map = await cashflow_service.get_billing_cycle_history_bulk(
            db=db,
            user_id=current_user.id,
            source_id=source_id,
            months=parsed_months,
        )
    except FinanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    formatted_months = {
        month.strftime("%Y-%m"): [
            {
                "cycle_start": item["cycle_start"],
                "cycle_end": item["cycle_end"],
                "posted_month": item["posted_month"],
                "amount": item["amount"],
                "note": item["note"],
                "auto_generated": item["auto_generated"],
            }
            for item in entries
        ]
        for month, entries in history_map.items()
    }

    return BillingCycleHistoryBulkResponse(
        source_id=source_id,
        months=formatted_months,
    )


@router.post(
    "/billing/{source_id}",
    response_model=BillingCycleHistoryResponse,
)
async def upsert_billing_cycles(
    source_id: UUID,
    payload: BillingCycleUpsertRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> BillingCycleHistoryResponse:
    entries_payload = [
        (item.cycle_start, item.cycle_end, item.amount, item.note)
        for item in payload.entries
    ]
    user_primary_currency = await get_finance_primary_currency(
        db, user_id=current_user.id
    )
    try:
        _, history = await cashflow_service.upsert_billing_cycle_entries(
            db=db,
            user_id=current_user.id,
            source_id=source_id,
            month=payload.month,
            entries=entries_payload,
            primary_currency=user_primary_currency,
        )
    except FinanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return BillingCycleHistoryResponse(
        source_id=source_id,
        month=payload.month,
        cycles=[
            {
                "cycle_start": item["cycle_start"],
                "cycle_end": item["cycle_end"],
                "posted_month": item["posted_month"],
                "amount": item["amount"],
                "note": item["note"],
                "auto_generated": item["auto_generated"],
            }
            for item in history
        ],
    )


@router.post(
    "/snapshots",
    response_model=CashflowSnapshotDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_cashflow_snapshot(
    payload: CashflowSnapshotCreateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> CashflowSnapshotDetailResponse:
    user_primary_currency = await get_finance_primary_currency(
        db, user_id=current_user.id
    )
    primary_currency = payload.primary_currency or user_primary_currency

    source_ids = [entry.source_id for entry in payload.entries]
    sources_map = await _get_sources_map(
        db, current_user.id, source_ids, tree_id=payload.tree_id
    )
    missing = [sid for sid in source_ids if sid not in sources_map]
    if missing:
        raise HTTPException(
            status_code=404,
            detail="Some sources do not exist or have been deleted",
        )

    entries_payload = [
        (
            sources_map[item.source_id],
            item.amount,
            item.note,
            item.currency_code,
        )
        for item in payload.entries
    ]
    exchange_rates_payload = [
        (item.quote_currency, item.rate) for item in payload.exchange_rates
    ]

    try:
        snapshot = await cashflow_service.create_cashflow_snapshot(
            db=db,
            user_id=current_user.id,
            tree_id=payload.tree_id,
            primary_currency=primary_currency,
            period_start=payload.period_start,
            period_end=payload.period_end,
            entries_payload=entries_payload,
            exchange_rates_payload=exchange_rates_payload,
            note=payload.note,
        )
    except EmptySnapshotPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except MissingExchangeRateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FinanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    snapshot, rows = await cashflow_service.get_cashflow_snapshot_detail(
        db=db,
        user_id=current_user.id,
        snapshot_id=snapshot.id,
        tree_id=payload.tree_id,
    )
    return _build_cashflow_snapshot_detail(snapshot, rows)


@router.patch(
    "/snapshots/{snapshot_id}",
    response_model=CashflowSnapshotDetailResponse,
)
async def update_cashflow_snapshot(
    snapshot_id: UUID,
    payload: CashflowSnapshotUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> CashflowSnapshotDetailResponse:
    source_ids = [entry.source_id for entry in payload.entries]
    sources_map = await _get_sources_map(
        db, current_user.id, source_ids, tree_id=payload.tree_id
    )
    missing = [sid for sid in source_ids if sid not in sources_map]
    if missing:
        raise HTTPException(
            status_code=404,
            detail="Some sources do not exist or have been deleted",
        )

    entries_payload = [
        (
            sources_map[item.source_id],
            item.amount,
            item.note,
            item.currency_code,
        )
        for item in payload.entries
    ]
    exchange_rates_payload = [
        (item.quote_currency, item.rate) for item in payload.exchange_rates
    ]

    user_primary_currency = await get_finance_primary_currency(
        db, user_id=current_user.id
    )
    try:
        snapshot = await cashflow_service.update_cashflow_snapshot(
            db=db,
            user_id=current_user.id,
            snapshot_id=snapshot_id,
            tree_id=payload.tree_id,
            primary_currency=payload.primary_currency or user_primary_currency,
            period_start=payload.period_start,
            period_end=payload.period_end,
            entries_payload=entries_payload,
            exchange_rates_payload=exchange_rates_payload,
            note=payload.note,
        )
    except EmptySnapshotPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except MissingExchangeRateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FinanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    snapshot, rows = await cashflow_service.get_cashflow_snapshot_detail(
        db=db,
        user_id=current_user.id,
        snapshot_id=snapshot.id,
        tree_id=payload.tree_id,
    )
    return _build_cashflow_snapshot_detail(snapshot, rows)


@router.delete(
    "/snapshots/{snapshot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_cashflow_snapshot(
    snapshot_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        await cashflow_service.delete_cashflow_snapshot(
            db=db, user_id=current_user.id, snapshot_id=snapshot_id
        )
    except FinanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get(
    "/snapshots",
    response_model=CashflowSnapshotListResponse,
)
async def list_cashflow_snapshots(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tree_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> CashflowSnapshotListResponse:
    offset = (page - 1) * size
    snapshots, total = await cashflow_service.list_cashflow_snapshots_with_total(
        db=db,
        user_id=current_user.id,
        tree_id=tree_id,
        skip=offset,
        limit=size,
    )
    items = [_build_cashflow_snapshot_summary(snapshot) for snapshot in snapshots]
    pages = (total + size - 1) // size if size else 0
    return CashflowSnapshotListResponse(
        items=items,
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
    "/snapshots/{snapshot_id}",
    response_model=CashflowSnapshotDetailResponse,
)
async def get_cashflow_snapshot(
    snapshot_id: UUID,
    tree_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> CashflowSnapshotDetailResponse:
    try:
        snapshot, rows = await cashflow_service.get_cashflow_snapshot_detail(
            db=db,
            user_id=current_user.id,
            snapshot_id=snapshot_id,
            tree_id=tree_id,
        )
    except FinanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _build_cashflow_snapshot_detail(snapshot, rows)


@router.get(
    "/snapshots/{snapshot_id}/compare/{other_id}",
    response_model=CashflowSnapshotComparisonResponse,
)
async def compare_cashflow_snapshots(
    snapshot_id: UUID,
    other_id: UUID,
    tree_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> CashflowSnapshotComparisonResponse:
    (
        base_snapshot,
        compare_snapshot,
        base_map,
        compare_map,
        source_map,
    ) = await cashflow_service.compare_cashflow_snapshots(
        db=db,
        user_id=current_user.id,
        base_snapshot_id=snapshot_id,
        compare_snapshot_id=other_id,
        tree_id=tree_id,
    )

    base_summary = _build_cashflow_snapshot_summary(base_snapshot)
    compare_summary = _build_cashflow_snapshot_summary(compare_snapshot)

    source_ids = set(base_map) | set(compare_map)
    changes: List[CashflowSnapshotSourceChange] = []
    for source_id in source_ids:
        base_entry = base_map.get(source_id)
        compare_entry = compare_map.get(source_id)
        base_amount = Decimal(str(base_entry.amount)) if base_entry else Decimal("0")
        compare_amount = (
            Decimal(str(compare_entry.amount)) if compare_entry else Decimal("0")
        )
        delta = compare_amount - base_amount
        source = source_map.get(source_id)
        source_name = source.name if source else "Unknown"
        changes.append(
            CashflowSnapshotSourceChange(
                source_id=source_id,
                source_name=source_name,
                previous_amount=base_amount,
                current_amount=compare_amount,
                delta=delta,
            )
        )

    return CashflowSnapshotComparisonResponse(
        base_snapshot_id=base_snapshot.id,
        compare_snapshot_id=compare_snapshot.id,
        base_period_start=base_snapshot.period_start.isoformat(),
        base_period_end=base_snapshot.period_end.isoformat(),
        compare_period_start=compare_snapshot.period_start.isoformat(),
        compare_period_end=compare_snapshot.period_end.isoformat(),
        base_totals=base_summary,
        compare_totals=compare_summary,
        source_changes=changes,
    )


def _build_cashflow_source_node(source: CashflowSource) -> CashflowSourceNode:
    return CashflowSourceNode.model_validate(
        {
            "id": source.id,
            "tree_id": source.tree_id,
            "parent_id": source.parent_id,
            "name": source.name,
            "path": source.path,
            "depth": source.depth,
            "sort_order": source.display_order,
            "metadata": source.metadata_json,
            "kind": source.kind,
            "is_rollup": source.is_rollup,
            "children_count": source.children_count,
            "currency_code": source.currency_code,
            "billing_cycle_type": source.billing_cycle_type,
            "billing_cycle_interval": source.billing_cycle_interval,
            "billing_anchor_day": source.billing_anchor_day,
            "billing_anchor_date": source.billing_anchor_date,
            "billing_post_to": source.billing_post_to,
            "billing_default_amount": source.billing_default_amount,
            "billing_default_note": source.billing_default_note,
            "billing_requires_manual_input": source.billing_requires_manual_input,
            "aggregated_amount": None,
            "children": [],
        }
    )


def _build_cashflow_source_tree(
    sources: List[CashflowSource],
) -> List[CashflowSourceNode]:
    node_map: Dict[UUID, CashflowSourceNode] = {}
    roots: List[CashflowSourceNode] = []

    for source in sources:
        node_map[source.id] = _build_cashflow_source_node(source)

    for source in sources:
        node = node_map[source.id]
        if source.parent_id and source.parent_id in node_map:
            node_map[source.parent_id].children.append(node)
        else:
            roots.append(node)

    def sort_children(children: List[CashflowSourceNode]) -> None:
        children.sort(
            key=lambda item: (
                item.sort_order if item.sort_order is not None else float("inf"),
                item.name,
            )
        )
        for child in children:
            sort_children(child.children)

    sort_children(roots)
    return roots


def _decimal_from(value: object) -> Decimal:
    return Decimal(str(value))


def _build_cashflow_snapshot_summary(
    snapshot,
) -> CashflowSnapshotSummaryResponse:
    return CashflowSnapshotSummaryResponse(
        id=snapshot.id,
        period_start=snapshot.period_start.isoformat(),
        period_end=snapshot.period_end.isoformat(),
        primary_currency=snapshot.primary_currency,
        tree_id=snapshot.tree_id,
        snapshot_ts=snapshot.snapshot_ts.isoformat() if snapshot.snapshot_ts else None,
        total_income=_decimal_from(snapshot.total_income),
        total_expense=_decimal_from(snapshot.total_expense),
        total_positive=_decimal_from(snapshot.total_positive),
        total_negative=_decimal_from(snapshot.total_negative),
        net_cashflow=_decimal_from(snapshot.net_cashflow),
        summary=snapshot.summary,
        note=snapshot.note,
    )


def _build_cashflow_snapshot_detail(
    snapshot,
    rows: List[Tuple[CashflowSnapshotEntry, CashflowSource]],
) -> CashflowSnapshotDetailResponse:
    entries: List[CashflowSnapshotEntryResponse] = []
    for entry, source in rows:
        entries.append(
            CashflowSnapshotEntryResponse(
                source_id=entry.source_id,
                source_name=source.name,
                amount=_decimal_from(entry.amount),
                currency_code=entry.currency_code,
                note=entry.note,
                is_auto_generated=entry.is_auto_generated,
            )
        )

    summary = _build_cashflow_snapshot_summary(snapshot)
    exchange_rates = [
        CashflowSnapshotExchangeRateResponse(
            quote_currency=currency,
            rate=_decimal_from(rate),
        )
        for currency, rate in (snapshot.exchange_rates or {}).items()
    ]
    return CashflowSnapshotDetailResponse(
        id=snapshot.id,
        period_start=summary.period_start,
        period_end=summary.period_end,
        primary_currency=summary.primary_currency,
        tree_id=summary.tree_id,
        snapshot_ts=summary.snapshot_ts,
        total_income=summary.total_income,
        total_expense=summary.total_expense,
        total_positive=summary.total_positive,
        total_negative=summary.total_negative,
        net_cashflow=summary.net_cashflow,
        summary=summary.summary,
        note=summary.note,
        entries=entries,
        exchange_rates=exchange_rates,
    )


__all__ = ["router"]
