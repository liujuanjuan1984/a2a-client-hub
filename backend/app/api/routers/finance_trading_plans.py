"""API routes for trading plan management."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.user import User
from app.handlers import finance_exchange_rates as exchange_service
from app.handlers import finance_trading as trading_service
from app.handlers.finance_common import (
    MissingExchangeRateError,
    RateSnapshotNotReadyError,
)
from app.handlers.metrics import trading_metrics as metrics_service
from app.handlers.user_preferences import get_finance_primary_currency
from app.schemas.finance_trading import (
    TradingEntryCreate,
    TradingEntryListResponse,
    TradingEntryResponse,
    TradingEntryUpdate,
    TradingInstrumentCreate,
    TradingInstrumentListResponse,
    TradingInstrumentResponse,
    TradingInstrumentUpdate,
    TradingPlanCreate,
    TradingPlanListResponse,
    TradingPlanResponse,
    TradingPlanSummaryResponse,
    TradingPlanUpdate,
)

router = StrictAPIRouter()
plans_router = StrictAPIRouter(
    prefix="/finance/trading-plans", tags=["finance-trading"]
)
entries_router = StrictAPIRouter(
    prefix="/finance/trading-entries", tags=["finance-trading"]
)


def _handle_trading_error(exc: Exception) -> HTTPException:
    if isinstance(exc, trading_service.TradingPlanNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, trading_service.TradingInstrumentNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, trading_service.TradingEntryNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, trading_service.TradingInstrumentConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, trading_service.TradingInstrumentMismatchError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@plans_router.get("", response_model=TradingPlanListResponse)
async def list_plans(
    include_archived: bool = Query(False),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TradingPlanListResponse:
    offset = (page - 1) * size
    plans, total = await trading_service.list_trading_plans(
        db,
        current_user.id,
        include_archived=include_archived,
        offset=offset,
        limit=size,
    )
    pages = (total + size - 1) // size if size else 0
    return TradingPlanListResponse(
        items=[TradingPlanResponse.model_validate(plan) for plan in plans],
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={"include_archived": include_archived},
    )


@plans_router.post(
    "",
    response_model=TradingPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_plan(
    payload: TradingPlanCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TradingPlanResponse:
    try:
        plan = await trading_service.create_trading_plan(
            db,
            current_user.id,
            name=payload.name,
            period_start=payload.period_start,
            period_end=payload.period_end,
            target_roi=payload.target_roi,
            note=payload.note,
            status=payload.status,
        )
    except trading_service.TradingPlanError as exc:
        raise _handle_trading_error(exc) from exc
    return TradingPlanResponse.model_validate(plan)


@plans_router.patch("/{plan_id}", response_model=TradingPlanResponse)
async def update_plan(
    plan_id: UUID,
    payload: TradingPlanUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TradingPlanResponse:
    try:
        plan = await trading_service.update_trading_plan(
            db,
            current_user.id,
            plan_id,
            name=payload.name,
            period_start=payload.period_start,
            period_end=payload.period_end,
            target_roi=payload.target_roi,
            note=payload.note,
            status=payload.status,
        )
    except trading_service.TradingPlanError as exc:
        raise _handle_trading_error(exc) from exc
    return TradingPlanResponse.model_validate(plan)


@plans_router.post(
    "/{plan_id}/archive",
    response_model=TradingPlanResponse,
)
async def archive_plan(
    plan_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TradingPlanResponse:
    try:
        plan = await trading_service.archive_trading_plan(db, current_user.id, plan_id)
    except trading_service.TradingPlanError as exc:
        raise _handle_trading_error(exc) from exc
    return TradingPlanResponse.model_validate(plan)


@plans_router.post(
    "/{plan_id}/rate-snapshot",
    response_model=TradingPlanResponse,
    summary="Refresh trading plan rate snapshot timestamp",
)
async def refresh_plan_rate_snapshot(
    plan_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TradingPlanResponse:
    try:
        plan = await trading_service.touch_rate_snapshot(db, current_user.id, plan_id)
    except MissingExchangeRateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except trading_service.TradingPlanError as exc:
        raise _handle_trading_error(exc) from exc
    return TradingPlanResponse.model_validate(plan)


@plans_router.get(
    "/{plan_id}/instruments",
    response_model=TradingInstrumentListResponse,
)
async def list_instruments(
    plan_id: UUID,
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TradingInstrumentListResponse:
    try:
        await trading_service.get_trading_plan(db, current_user.id, plan_id)
        offset = (page - 1) * size
        instruments, total = await trading_service.list_trading_instruments(
            db,
            current_user.id,
            plan_id=plan_id,
            offset=offset,
            limit=size,
        )
    except trading_service.TradingPlanError as exc:
        raise _handle_trading_error(exc) from exc
    pages = (total + size - 1) // size if size else 0
    return TradingInstrumentListResponse(
        items=[TradingInstrumentResponse.model_validate(inst) for inst in instruments],
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={"plan_id": plan_id},
    )


@plans_router.post(
    "/{plan_id}/instruments",
    response_model=TradingInstrumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_instrument(
    plan_id: UUID,
    payload: TradingInstrumentCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TradingInstrumentResponse:
    try:
        instrument = await trading_service.create_trading_instrument(
            db,
            current_user.id,
            plan_id=plan_id,
            symbol=payload.symbol,
            base_asset=payload.base_asset,
            quote_asset=payload.quote_asset,
            exchange=payload.exchange,
            strategy_tag=payload.strategy_tag,
            note=payload.note,
        )
    except trading_service.TradingPlanError as exc:
        raise _handle_trading_error(exc) from exc
    return TradingInstrumentResponse.model_validate(instrument)


@plans_router.patch(
    "/{plan_id}/instruments/{instrument_id}",
    response_model=TradingInstrumentResponse,
)
async def update_instrument(
    plan_id: UUID,
    instrument_id: UUID,
    payload: TradingInstrumentUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TradingInstrumentResponse:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No fields provided for update")
    try:
        instrument = await trading_service.get_trading_instrument(
            db, current_user.id, instrument_id
        )
        if instrument.plan_id != plan_id:
            raise trading_service.TradingInstrumentMismatchError(
                "Instrument does not belong to plan"
            )
        instrument = await trading_service.update_trading_instrument(
            db,
            current_user.id,
            instrument_id,
            symbol=payload.symbol,
            base_asset=payload.base_asset,
            quote_asset=payload.quote_asset,
            exchange=payload.exchange,
            strategy_tag=payload.strategy_tag,
            note=payload.note,
        )
    except trading_service.TradingPlanError as exc:
        raise _handle_trading_error(exc) from exc
    return TradingInstrumentResponse.model_validate(instrument)


@plans_router.delete(
    "/{plan_id}/instruments/{instrument_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_instrument(
    plan_id: UUID,
    instrument_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        instrument = await trading_service.get_trading_instrument(
            db, current_user.id, instrument_id
        )
        if instrument.plan_id != plan_id:
            raise trading_service.TradingInstrumentMismatchError(
                "Instrument does not belong to plan"
            )
        await trading_service.delete_trading_instrument(
            db,
            current_user.id,
            instrument_id,
        )
    except trading_service.TradingPlanError as exc:
        raise _handle_trading_error(exc) from exc


@plans_router.get(
    "/{plan_id}/summary",
    response_model=TradingPlanSummaryResponse,
)
async def get_plan_summary(
    plan_id: UUID,
    currency: Optional[str] = Query(None, description="Primary currency override"),
    at: Optional[datetime] = Query(None, description="Effective timestamp"),
    rate_mode: Literal["snapshot", "source"] = Query(
        "snapshot", description="Rate mode: snapshot or source"
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TradingPlanSummaryResponse:
    preferred_currency = currency or await get_finance_primary_currency(
        db, user_id=current_user.id
    )
    try:
        summary = await metrics_service.get_trading_plan_summary(
            db,
            current_user.id,
            plan_id,
            primary_currency=preferred_currency,
            effective_at=at,
            rate_mode=rate_mode,
        )
    except RateSnapshotNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MissingExchangeRateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except exchange_service.ExchangeRateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except trading_service.TradingPlanError as exc:
        raise _handle_trading_error(exc) from exc
    return summary


@entries_router.get("", response_model=TradingEntryListResponse)
async def list_entries(
    plan_id: Optional[UUID] = Query(None),
    instrument_id: Optional[UUID] = Query(None),
    direction: Optional[str] = Query(None, pattern="^(buy|sell|transfer)$"),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TradingEntryListResponse:
    offset = (page - 1) * size
    try:
        entries, total = await trading_service.list_trading_entries(
            db,
            current_user.id,
            plan_id=plan_id,
            instrument_id=instrument_id,
            direction=direction,
            start_time=start_time,
            end_time=end_time,
            limit=size,
            offset=offset,
        )
    except trading_service.TradingPlanError as exc:
        raise _handle_trading_error(exc) from exc
    pages = (total + size - 1) // size if size else 0
    return TradingEntryListResponse(
        items=[TradingEntryResponse.model_validate(entry) for entry in entries],
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={
            "plan_id": plan_id,
            "instrument_id": instrument_id,
            "direction": direction,
            "start_time": start_time,
            "end_time": end_time,
        },
    )


@entries_router.post(
    "",
    response_model=TradingEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_entry(
    payload: TradingEntryCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TradingEntryResponse:
    try:
        entry = await trading_service.create_trading_entry(
            db,
            current_user.id,
            plan_id=payload.plan_id,
            instrument_id=payload.instrument_id,
            trade_time=payload.trade_time,
            direction=payload.direction,
            base_delta=payload.base_delta,
            quote_delta=payload.quote_delta,
            price=payload.price,
            fee_asset=payload.fee_asset,
            fee_amount=payload.fee_amount,
            source=payload.source,
            note=payload.note,
        )
    except trading_service.TradingPlanError as exc:
        raise _handle_trading_error(exc) from exc
    return TradingEntryResponse.model_validate(entry)


@entries_router.put(
    "/{entry_id}",
    response_model=TradingEntryResponse,
)
async def update_entry(
    entry_id: UUID,
    payload: TradingEntryUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TradingEntryResponse:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No fields provided for update")
    try:
        entry = await trading_service.update_trading_entry(
            db,
            current_user.id,
            entry_id,
            trade_time=payload.trade_time,
            direction=payload.direction,
            base_delta=payload.base_delta,
            quote_delta=payload.quote_delta,
            price=payload.price,
            fee_asset=payload.fee_asset,
            fee_amount=payload.fee_amount,
            source=payload.source,
            note=payload.note,
        )
    except trading_service.TradingPlanError as exc:
        raise _handle_trading_error(exc) from exc
    return TradingEntryResponse.model_validate(entry)


@entries_router.delete(
    "/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        await trading_service.delete_trading_entry(db, current_user.id, entry_id)
    except trading_service.TradingPlanError as exc:
        raise _handle_trading_error(exc) from exc


router.include_router(plans_router)
router.include_router(entries_router)

__all__ = ["router"]
