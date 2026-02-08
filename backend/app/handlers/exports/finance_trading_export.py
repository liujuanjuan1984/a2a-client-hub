"""
Finance trading export service and helpers.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.finance_trading import TradingEntry, TradingInstrument, TradingPlan
from app.handlers.exports.export_base import BaseExportService, ExportFormatter
from app.handlers.finance_trading import TradingPlanNotFoundError
from app.schemas.export import FinanceTradingExportParams

AVG_RECORD_TEXT_BYTES = 512  # conservative average size per trading entry


def _safe_decimal(value: Optional[Decimal]) -> str:
    return "" if value is None else str(value)


class FinanceTradingExportService(BaseExportService):
    """Export service for finance trading entries."""

    def generate_export_text(
        self, params: FinanceTradingExportParams, data: Tuple[List[Any], Dict[str, Any]]
    ) -> str:
        entries, ctx = data
        plan_name = ctx.get("plan_name", "")
        instrument_map: Dict[str, str] = ctx.get("instrument_map", {})

        if params.format == "csv":
            return self._to_csv(entries, instrument_map, plan_name)
        if params.format == "json":
            return json.dumps(
                self._to_json(entries, instrument_map, plan_name),
                ensure_ascii=False,
                indent=2,
            )

        # default text
        return self._to_text(entries, instrument_map, plan_name)

    def _to_csv(
        self, entries: List[Any], instrument_map: Dict[str, str], plan_name: str
    ) -> str:
        headers = [
            "trade_time",
            "plan",
            "instrument",
            "direction",
            "base_delta",
            "quote_delta",
            "price",
            "fee_asset",
            "fee_amount",
            "source",
            "note",
        ]
        rows = [ExportFormatter.create_table_header(headers)]
        for entry in entries:
            rows.append(
                ExportFormatter.format_table_row(
                    [
                        entry.trade_time.isoformat() if entry.trade_time else "",
                        plan_name,
                        instrument_map.get(str(entry.instrument_id), ""),
                        entry.direction,
                        _safe_decimal(entry.base_delta),
                        _safe_decimal(entry.quote_delta),
                        _safe_decimal(entry.price),
                        entry.fee_asset or "",
                        _safe_decimal(entry.fee_amount),
                        entry.source or "",
                        ExportFormatter.clean_text(entry.note or ""),
                    ]
                )
            )
        return "\n".join(rows)

    def _to_json(
        self, entries: List[Any], instrument_map: Dict[str, str], plan_name: str
    ) -> List[Dict[str, Any]]:
        payload: List[Dict[str, Any]] = []
        for entry in entries:
            payload.append(
                {
                    "trade_time": (
                        entry.trade_time.isoformat() if entry.trade_time else None
                    ),
                    "plan": plan_name,
                    "instrument": instrument_map.get(str(entry.instrument_id), None),
                    "direction": entry.direction,
                    "base_delta": _safe_decimal(entry.base_delta),
                    "quote_delta": _safe_decimal(entry.quote_delta),
                    "price": _safe_decimal(entry.price),
                    "fee_asset": entry.fee_asset,
                    "fee_amount": _safe_decimal(entry.fee_amount),
                    "source": entry.source,
                    "note": entry.note,
                }
            )
        return payload

    def _to_text(
        self, entries: List[Any], instrument_map: Dict[str, str], plan_name: str
    ) -> str:
        lines: List[str] = []
        header = self.t("export.finance.trading.header", default="Trading Entries")
        lines.extend(self.create_export_header(header))
        lines.append(f"计划: {plan_name}")
        lines.append("")

        if not entries:
            lines.append(self.t("export.common.no_data", default="No data"))
            return "\n".join(lines)

        for entry in entries:
            lines.append(
                self.format_datetime(entry.trade_time) if entry.trade_time else ""
            )
            instrument_name = instrument_map.get(str(entry.instrument_id), "")
            line = f"{entry.direction} {instrument_name} base:{_safe_decimal(entry.base_delta)} quote:{_safe_decimal(entry.quote_delta)} price:{_safe_decimal(entry.price)}"
            lines.append(line)
            if entry.fee_asset or entry.fee_amount:
                lines.append(f"fee: {entry.fee_amount} {entry.fee_asset or ''}")
            if entry.source:
                lines.append(f"source: {entry.source}")
            if entry.note:
                lines.append(f"note: {entry.note}")
            lines.append("")

        return "\n".join(lines)


async def _get_trading_plan(
    db: AsyncSession, user_id: UUID, plan_id: UUID
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
    plan = (await db.execute(stmt)).scalars().first()
    if not plan:
        raise TradingPlanNotFoundError("Trading plan not found")
    return plan


async def _list_trading_entries(
    db: AsyncSession,
    *,
    user_id: UUID,
    plan_id: UUID,
    instrument_id: Optional[UUID],
    start_time,
    end_time,
    limit: int,
) -> List[TradingEntry]:
    stmt = (
        select(TradingEntry)
        .where(
            TradingEntry.user_id == user_id,
            TradingEntry.plan_id == plan_id,
            TradingEntry.deleted_at.is_(None),
        )
        .order_by(TradingEntry.trade_time.asc())
    )
    if instrument_id:
        stmt = stmt.where(TradingEntry.instrument_id == instrument_id)
    if start_time:
        stmt = stmt.where(TradingEntry.trade_time >= start_time)
    if end_time:
        stmt = stmt.where(TradingEntry.trade_time <= end_time)
    if limit:
        stmt = stmt.limit(limit)
    return (await db.execute(stmt)).scalars().all()


async def _load_instrument_map(
    db: AsyncSession, *, user_id: UUID, plan_id: UUID
) -> Dict[str, str]:
    stmt = (
        select(TradingInstrument.id, TradingInstrument.symbol)
        .where(
            TradingInstrument.user_id == user_id,
            TradingInstrument.plan_id == plan_id,
            TradingInstrument.deleted_at.is_(None),
        )
        .order_by(TradingInstrument.symbol.asc())
    )
    rows = (await db.execute(stmt)).all()
    return {str(row[0]): row[1] for row in rows}


async def export_finance_trading_data(
    db: AsyncSession,
    params: FinanceTradingExportParams,
    user_id: UUID,
) -> Tuple[str, str, str]:
    """Export trading entries; returns (content, content_type, filename)."""

    service = FinanceTradingExportService(locale=params.locale or "zh-CN")

    plan = await _get_trading_plan(db, user_id=user_id, plan_id=params.plan_id)

    start_time = params.start_time
    end_time = params.end_time

    entries = await _list_trading_entries(
        db,
        user_id=user_id,
        plan_id=params.plan_id,
        instrument_id=params.instrument_id,
        start_time=start_time,
        end_time=end_time,
        limit=100000,
    )

    instrument_map = await _load_instrument_map(
        db, user_id=user_id, plan_id=params.plan_id
    )

    content = service.generate_export_text(
        params, (entries, {"plan_name": plan.name, "instrument_map": instrument_map})
    )

    content_type = "text/plain"
    if params.format == "csv":
        content_type = "text/csv"
    elif params.format == "json":
        content_type = "application/json"

    filename = f"trading_export_{plan.name or 'plan'}.{ 'txt' if params.format == 'text' else params.format }"
    return content, content_type, filename


async def estimate_finance_trading_export(
    db: AsyncSession,
    params: FinanceTradingExportParams,
    user_id: UUID,
) -> Tuple[int, int]:
    """Return (record_count, estimated_size_bytes)."""

    start_time = params.start_time
    end_time = params.end_time
    stmt = select(func.count(TradingEntry.id)).where(
        TradingEntry.user_id == user_id,
        TradingEntry.plan_id == params.plan_id,
        TradingEntry.deleted_at.is_(None),
    )
    if params.instrument_id:
        stmt = stmt.where(TradingEntry.instrument_id == params.instrument_id)
    if start_time:
        stmt = stmt.where(TradingEntry.trade_time >= start_time)
    if end_time:
        stmt = stmt.where(TradingEntry.trade_time <= end_time)
    total = (await db.execute(stmt)).scalar_one()

    estimated_size = total * AVG_RECORD_TEXT_BYTES
    return total, estimated_size
