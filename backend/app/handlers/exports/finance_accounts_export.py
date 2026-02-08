"""Export helpers for finance accounts (account tree)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.finance_accounts import FinanceAccount
from app.handlers.exports.export_base import BaseExportService, ExportFormatter
from app.handlers.finance_account_trees import resolve_account_tree
from app.schemas.export import FinanceAccountsExportParams

AVG_ACCOUNT_TEXT_BYTES = 256  # heuristic: average bytes per account row when exported

FORMAT_METADATA = {
    "csv": ("text/csv", "finance_accounts.csv"),
    "json": ("application/json", "finance_accounts.json"),
}
DEFAULT_FORMAT_METADATA = ("text/plain", "finance_accounts.txt")


async def _fetch_accounts(
    db: AsyncSession, user_id: UUID, *, tree_id: Optional[UUID]
) -> List[FinanceAccount]:
    tree = await resolve_account_tree(db, user_id, tree_id)
    stmt = (
        select(FinanceAccount)
        .where(
            FinanceAccount.user_id == user_id,
            FinanceAccount.tree_id == tree.id,
            FinanceAccount.deleted_at.is_(None),
        )
        .order_by(FinanceAccount.depth.asc(), FinanceAccount.display_order.asc())
    )
    return (await db.execute(stmt)).scalars().all()


class FinanceAccountsExportService(BaseExportService):
    def generate_export_text(
        self, params: FinanceAccountsExportParams, data: List[FinanceAccount]
    ) -> str:
        if params.format == "csv":
            return self._to_csv(data)
        if params.format == "json":
            return json.dumps(self._to_json(data), ensure_ascii=False, indent=2)
        return self._to_text(data)

    def _to_csv(self, accounts: List[FinanceAccount]) -> str:
        headers = [
            "name",
            "path",
            "type",
            "nature",
            "currency",
            "interest_rate",
            "parent_id",
        ]
        rows = [ExportFormatter.create_table_header(headers)]
        for acc in accounts:
            rows.append(
                ExportFormatter.format_table_row(
                    [
                        acc.name,
                        acc.path,
                        acc.type or "",
                        acc.nature or "",
                        acc.currency_code,
                        acc.interest_rate or "",
                        acc.parent_id or "",
                    ]
                )
            )
        return "\n".join(rows)

    def _to_json(self, accounts: List[FinanceAccount]) -> List[Dict[str, Any]]:
        payload: List[Dict[str, Any]] = []
        for acc in accounts:
            payload.append(
                {
                    "id": str(acc.id),
                    "name": acc.name,
                    "path": acc.path,
                    "type": acc.type,
                    "nature": acc.nature,
                    "currency": acc.currency_code,
                    "interest_rate": (
                        str(acc.interest_rate) if acc.interest_rate else None
                    ),
                    "parent_id": str(acc.parent_id) if acc.parent_id else None,
                }
            )
        return payload

    def _to_text(self, accounts: List[FinanceAccount]) -> str:
        lines: List[str] = []
        lines.extend(
            self.create_export_header(
                self.t("export.finance.accounts.header", default="Accounts")
            )
        )
        if not accounts:
            lines.append(self.t("export.common.no_data", default="No data"))
            return "\n".join(lines)
        for acc in accounts:
            indent = "  " * max(acc.depth - 1, 0)
            lines.append(f"{indent}- {acc.name} [{acc.currency_code}] ({acc.type})")
        return "\n".join(lines)


async def export_finance_accounts_data(
    db: AsyncSession,
    params: FinanceAccountsExportParams,
    user_id: UUID,
) -> Tuple[str, str, str]:
    service = FinanceAccountsExportService(locale=params.locale or "zh-CN")
    accounts = await _fetch_accounts(db, user_id, tree_id=params.tree_id)
    content = service.generate_export_text(params, accounts)

    content_type, filename = FORMAT_METADATA.get(params.format, DEFAULT_FORMAT_METADATA)
    return content, content_type, filename


async def estimate_finance_accounts_export(
    db: AsyncSession,
    params: FinanceAccountsExportParams,
    user_id: UUID,
) -> Tuple[int, int]:
    tree = await resolve_account_tree(db, user_id, params.tree_id)
    stmt = select(func.count(FinanceAccount.id)).where(
        FinanceAccount.user_id == user_id,
        FinanceAccount.tree_id == tree.id,
        FinanceAccount.deleted_at.is_(None),
    )
    total = (await db.execute(stmt)).scalar_one()
    estimated_size = total * AVG_ACCOUNT_TEXT_BYTES
    return total, estimated_size
