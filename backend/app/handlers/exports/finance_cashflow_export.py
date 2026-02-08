"""Export helpers for finance cashflow snapshots."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.finance_cashflow import CashflowSnapshot, CashflowSnapshotEntry
from app.handlers.exports.export_base import BaseExportService, ExportFormatter
from app.handlers.finance_cashflow import (
    get_cashflow_snapshot_detail,
    list_cashflow_snapshots,
)
from app.handlers.finance_cashflow_trees import resolve_cashflow_tree
from app.handlers.finance_common import FinanceError
from app.schemas.export import FinanceCashflowExportParams

logger = get_logger(__name__)

AVG_SNAPSHOT_TEXT_BYTES = 800


class FinanceCashflowExportService(BaseExportService):
    def generate_export_text(
        self,
        params: FinanceCashflowExportParams,
        data: List[Tuple[CashflowSnapshot, List[Tuple[CashflowSnapshotEntry, Any]]]],
    ) -> str:
        if params.format == "csv":
            return self._to_csv(data)
        if params.format == "json":
            return json.dumps(self._to_json(data), ensure_ascii=False, indent=2)
        return self._to_text(data)

    def _entry_to_row(self, entry: CashflowSnapshotEntry, source: Any) -> List[str]:
        return [
            getattr(source, "kind", "") or "",
            getattr(source, "name", "") or "",
            str(entry.amount) if entry.amount is not None else "",
            entry.currency_code or "",
            getattr(source, "path", "") or "",
        ]

    def _to_csv(
        self,
        snapshots: List[
            Tuple[CashflowSnapshot, List[Tuple[CashflowSnapshotEntry, Any]]]
        ],
    ) -> str:
        headers = [
            "snapshot_ts",
            "net_cashflow",
            "currency",
            "entry_type",
            "title",
            "amount",
            "entry_currency",
            "category",
        ]
        rows = [ExportFormatter.create_table_header(headers)]
        for snap, row_pairs in snapshots:
            for entry, source in row_pairs:
                rows.append(
                    ExportFormatter.format_table_row(
                        [
                            snap.period_start.isoformat() if snap.period_start else "",
                            snap.net_cashflow,
                            snap.primary_currency,
                            *self._entry_to_row(entry, source),
                        ]
                    )
                )
        return "\n".join(rows)

    def _to_json(
        self,
        snapshots: List[
            Tuple[CashflowSnapshot, List[Tuple[CashflowSnapshotEntry, Any]]]
        ],
    ) -> List[Dict[str, Any]]:
        payload: List[Dict[str, Any]] = []
        for snap, row_pairs in snapshots:
            payload.append(
                {
                    "period_start": (
                        snap.period_start.isoformat() if snap.period_start else None
                    ),
                    "period_end": (
                        snap.period_end.isoformat() if snap.period_end else None
                    ),
                    "primary_currency": snap.primary_currency,
                    "net_cashflow": (
                        str(snap.net_cashflow)
                        if snap.net_cashflow is not None
                        else None
                    ),
                    "entries": [
                        {
                            "type": getattr(src, "kind", None),
                            "title": getattr(src, "name", None),
                            "amount": str(e.amount) if e.amount is not None else None,
                            "currency_code": e.currency_code,
                            "category": getattr(src, "path", None),
                        }
                        for e, src in row_pairs
                    ],
                }
            )
        return payload

    def _to_text(
        self,
        snapshots: List[
            Tuple[CashflowSnapshot, List[Tuple[CashflowSnapshotEntry, Any]]]
        ],
    ) -> str:
        lines: List[str] = []
        lines.extend(
            self.create_export_header(
                self.t("export.finance.cashflow.header", default="Cashflow")
            )
        )
        if not snapshots:
            lines.append(self.t("export.common.no_data", default="No data"))
            return "\n".join(lines)
        for snap, row_pairs in snapshots:
            ts = self.format_datetime(snap.period_start) if snap.period_start else ""
            lines.append(f"[{ts}] net: {snap.net_cashflow} {snap.primary_currency}")
            for entry, source in row_pairs:
                lines.append(
                    f"  - {getattr(source, 'kind', '')}: {getattr(source, 'name', '')} {entry.amount} {entry.currency_code} ({getattr(source, 'path', '') or ''})"
                )
            lines.append("")
        return "\n".join(lines)


async def export_finance_cashflow_data(
    db: AsyncSession,
    params: FinanceCashflowExportParams,
    user_id: UUID,
) -> Tuple[str, str, str]:
    service = FinanceCashflowExportService(locale=params.locale or "zh-CN")

    tree = await resolve_cashflow_tree(db, user_id, params.tree_id)
    snapshots_raw = await list_cashflow_snapshots(
        db,
        user_id=user_id,
        tree_id=tree.id,
        start_time=params.start_time,
        end_time=params.end_time,
        limit=200,
        offset=0,
    )

    snapshots: List[
        Tuple[CashflowSnapshot, List[Tuple[CashflowSnapshotEntry, Any]]]
    ] = []
    for summary in snapshots_raw:
        try:
            snapshot_obj, rows = await get_cashflow_snapshot_detail(
                db, user_id=user_id, snapshot_id=summary.id, tree_id=tree.id
            )
        except FinanceError as exc:
            logger.warning(
                "Skipping cashflow snapshot %s due to detail lookup failure: %s",
                summary.id,
                exc,
            )
            continue
        snapshots.append((snapshot_obj, rows))

    content = service.generate_export_text(params, snapshots)
    content_type = "text/plain"
    filename = "cashflow.txt"
    if params.format == "csv":
        content_type = "text/csv"
        filename = "cashflow.csv"
    elif params.format == "json":
        content_type = "application/json"
        filename = "cashflow.json"
    return content, content_type, filename


async def estimate_finance_cashflow_export(
    db: AsyncSession,
    params: FinanceCashflowExportParams,
    user_id: UUID,
) -> Tuple[int, int]:
    tree = await resolve_cashflow_tree(db, user_id, params.tree_id)
    stmt = select(func.count(CashflowSnapshot.id)).where(
        CashflowSnapshot.user_id == user_id,
        CashflowSnapshot.tree_id == tree.id,
    )
    if params.start_time:
        stmt = stmt.where(CashflowSnapshot.period_start >= params.start_time)
    if params.end_time:
        stmt = stmt.where(CashflowSnapshot.period_start <= params.end_time)
    total = (await db.execute(stmt)).scalar_one()
    estimated_size = total * AVG_SNAPSHOT_TEXT_BYTES
    return total, estimated_size
