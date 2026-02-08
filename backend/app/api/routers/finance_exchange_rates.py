"""Finance exchange rate API routes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Literal, Optional, Tuple
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.finance_trading import ExchangeRate
from app.db.models.user import User
from app.handlers import finance_balance_snapshots as balance_service
from app.handlers import finance_exchange_rates as exchange_service
from app.handlers import finance_trading as trading_service
from app.handlers.user_preferences import get_finance_primary_currency
from app.schemas.finance_balance_snapshots import LatestExchangeRateResponse
from app.schemas.finance_exchange_rates import (
    ExchangeRateCreateRequest,
    ExchangeRateListResponse,
    ExchangeRateQueryResponse,
    ExchangeRateQueryResult,
    ExchangeRateResponse,
)
from app.utils.timezone_util import utc_now

router = StrictAPIRouter(prefix="/finance/exchange-rates", tags=["finance-exchange"])


@router.get("/latest", response_model=LatestExchangeRateResponse)
async def get_latest_exchange_rates(
    currencies: Optional[str] = Query(
        None, description="Comma separated currency list"
    ),
    scope: Literal["snapshot", "source"] = Query(
        ..., description="Rate scope: snapshot or source"
    ),
    tree_id: Optional[UUID] = Query(None, description="Account tree id"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> LatestExchangeRateResponse:
    if scope == "source":
        if not currencies or not currencies.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="currencies is required when scope=source",
            )
        base_currency = await get_finance_primary_currency(db, user_id=current_user.id)
        result_rates: Dict[str, Decimal] = {base_currency: Decimal("1")}
        requested = (
            {c.strip().upper() for c in currencies.split(",") if c.strip()}
            if currencies
            else set()
        )
        missing: list[str] = []
        for currency in requested:
            if currency == base_currency:
                continue
            try:
                rate_map = await exchange_service.query_exchange_rates(
                    db,
                    current_user.id,
                    pairs=[(currency, base_currency)],
                )
            except exchange_service.ExchangeRateNotFoundError:
                missing.append(currency)
                continue
            result_rates[currency] = rate_map[(currency, base_currency)][0]
        if missing:
            missing_pairs = ", ".join(
                f"{currency}/{base_currency}" for currency in sorted(set(missing))
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"缺少汇率：{missing_pairs}",
            )
        return LatestExchangeRateResponse(
            snapshot_id=None,
            snapshot_ts=None,
            base_currency=base_currency,
            rates=result_rates,
            scope=scope,
        )

    snapshot, rates = await balance_service.get_latest_exchange_rates(
        db, current_user.id, tree_id=tree_id
    )
    if snapshot:
        base_currency = snapshot.primary_currency
    else:
        base_currency = await get_finance_primary_currency(db, user_id=current_user.id)
    result_rates: Dict[str, Decimal] = {**rates}
    result_rates[base_currency] = Decimal("1")

    if currencies:
        requested = {c.strip().upper() for c in currencies.split(",") if c.strip()}
        filtered: Dict[str, Decimal] = {}
        missing: list[str] = []
        for currency in requested:
            if currency == base_currency:
                filtered[currency] = Decimal("1")
            elif currency in result_rates:
                filtered[currency] = result_rates[currency]
            else:
                missing.append(currency)
        if missing:
            missing_pairs = ", ".join(
                f"{currency}/{base_currency}" for currency in sorted(set(missing))
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"缺少汇率：{missing_pairs}",
            )
        result_rates = filtered

    return LatestExchangeRateResponse(
        snapshot_id=snapshot.id if snapshot else None,
        snapshot_ts=snapshot.snapshot_ts.isoformat() if snapshot else None,
        base_currency=base_currency,
        rates=result_rates,
        scope=scope,
    )


def _parse_pairs(
    base: Optional[str],
    quote: Optional[str],
    pairs: Optional[List[str]],
) -> List[Tuple[str, str]]:
    parsed: List[Tuple[str, str]] = []
    if base and quote:
        parsed.append((base, quote))
    if pairs:
        for item in pairs:
            if not item:
                continue
            if "/" not in item:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="pairs must use BASE/QUOTE format",
                )
            base_part, quote_part = item.split("/", 1)
            parsed.append((base_part.strip(), quote_part.strip()))
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide base/quote or at least one pair",
        )
    return parsed


@router.get("", response_model=ExchangeRateQueryResponse)
async def query_exchange_rates_endpoint(
    base: Optional[str] = Query(None, description="Base asset e.g. BTC"),
    quote: Optional[str] = Query(None, description="Quote asset e.g. USDT"),
    pairs: Optional[List[str]] = Query(
        None, description="List of BASE/QUOTE pairs, e.g. BTC/USDT"
    ),
    at: Optional[datetime] = Query(None, description="Effective timestamp (UTC)"),
    plan_id: Optional[UUID] = Query(
        None, description="Restrict lookups to this trading plan context"
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ExchangeRateQueryResponse:
    pair_list = _parse_pairs(base, quote, pairs)
    try:
        rate_map = await exchange_service.query_exchange_rates(
            db,
            current_user.id,
            pairs=pair_list,
            effective_at=at,
            plan_id=plan_id,
        )
    except exchange_service.ExchangeRateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    response_pairs: List[ExchangeRateQueryResult] = []
    for pair in pair_list:
        base_asset = pair[0].strip().upper()
        quote_asset = pair[1].strip().upper()
        rate_value, source, captured_at = rate_map[(base_asset, quote_asset)]
        response_pairs.append(
            ExchangeRateQueryResult(
                base_asset=base_asset,
                quote_asset=quote_asset,
                rate=rate_value,
                source=source,
                captured_at=captured_at,
            )
        )

    return ExchangeRateQueryResponse(
        requested_at=(at or utc_now()),
        pairs=response_pairs,
    )


@router.post(
    "", response_model=ExchangeRateResponse, status_code=status.HTTP_201_CREATED
)
async def create_exchange_rate_endpoint(
    payload: ExchangeRateCreateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ExchangeRateResponse:
    plan_id = payload.plan_id
    if plan_id is not None:
        try:
            await trading_service.get_trading_plan(db, current_user.id, plan_id)
        except trading_service.TradingPlanError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    rate = await exchange_service.create_exchange_rate(
        db,
        current_user.id,
        plan_id=plan_id,
        base_asset=payload.base_asset,
        quote_asset=payload.quote_asset,
        rate=payload.rate,
        source=payload.source,
        captured_at=payload.captured_at,
    )
    return ExchangeRateResponse.model_validate(rate)


@router.get(
    "/plans/{plan_id}",
    response_model=ExchangeRateListResponse,
    summary="List exchange rates scoped to a trading plan",
)
async def list_plan_exchange_rates(
    plan_id: UUID,
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ExchangeRateListResponse:
    try:
        await trading_service.get_trading_plan(db, current_user.id, plan_id)
    except trading_service.TradingPlanError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    stmt = (
        select(ExchangeRate)
        .where(ExchangeRate.plan_id == plan_id)
        .where(
            or_(
                ExchangeRate.user_id == current_user.id,
                ExchangeRate.user_id.is_(None),
            )
        )
        .order_by(ExchangeRate.captured_at.desc())
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    offset = (page - 1) * size
    stmt = stmt.offset(offset).limit(size)
    records = (await db.execute(stmt)).scalars().all()
    total = await db.scalar(count_stmt)
    items = [ExchangeRateResponse.model_validate(record) for record in records]
    pages = (total + size - 1) // size if size else 0
    return ExchangeRateListResponse(
        items=items,
        pagination={
            "page": page,
            "size": size,
            "total": int(total or 0),
            "pages": pages,
        },
        meta={
            "plan_id": plan_id,
        },
    )


__all__ = ["router"]
