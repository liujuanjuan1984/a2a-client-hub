"""Full export aggregator (finance-focused initial version)."""

from __future__ import annotations

from typing import List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.finance_trading import TradingPlan
from app.db.models.vision import Vision
from app.handlers.exports.finance_accounts_export import export_finance_accounts_data
from app.handlers.exports.finance_cashflow_export import export_finance_cashflow_data
from app.handlers.exports.finance_trading_export import export_finance_trading_data
from app.handlers.exports.notes_export import export_notes_data
from app.handlers.exports.planning_export import export_planning_data
from app.handlers.exports.timelog_export import export_timelog_data
from app.handlers.exports.vision_export import export_vision_data
from app.schemas.export import (
    FinanceAccountsExportParams,
    FinanceCashflowExportParams,
    FinanceTradingExportParams,
    NotesExportParams,
    PlanningExportParams,
    TimeLogExportParams,
    VisionExportParams,
)
from app.utils.timezone_util import utc_now


async def export_full_finance(db: AsyncSession, user_id: UUID) -> str:
    sections: List[str] = []

    # Accounts
    acc_content, _, _ = await export_finance_accounts_data(
        db,
        FinanceAccountsExportParams(format="text"),
        user_id,
    )
    sections.append("## Accounts\n" + acc_content)

    # Cashflow
    cash_content, _, _ = await export_finance_cashflow_data(
        db,
        FinanceCashflowExportParams(format="text"),
        user_id,
    )
    sections.append("## Cashflow\n" + cash_content)

    # Trading per plan
    stmt = (
        select(TradingPlan)
        .where(
            TradingPlan.user_id == user_id,
            TradingPlan.deleted_at.is_(None),
        )
        .order_by(TradingPlan.created_at.desc())
    )
    plans = (await db.execute(stmt)).scalars().all()
    for plan in plans:
        trading_params = FinanceTradingExportParams(
            plan_id=plan.id,
            format="text",
        )
        content, _, _ = await export_finance_trading_data(db, trading_params, user_id)
        sections.append(f"## Trading Plan: {plan.name}\n" + content)

    return "\n\n".join(sections)


async def export_full_all(db: AsyncSession, user_id: UUID) -> str:
    sections: List[str] = []

    # Finance
    sections.append(await export_full_finance(db, user_id))

    # Notes (all)
    notes_content = await export_notes_data(
        db,
        NotesExportParams(
            selected_filter_tags=[],
            selected_filter_persons=[],
            search_keyword="",
            filter_summary=[],
        ),
        str(user_id),
    )
    sections.append("## Notes\n" + notes_content)

    # Timelog (all time)
    epoch = utc_now().replace(year=1970, month=1, day=1, hour=0, minute=0, second=0)
    now = utc_now()
    timelog_content, _ = await export_timelog_data(
        db,
        TimeLogExportParams(
            start_date=epoch,
            end_date=now,
            dimension_id=None,
            description_keyword=None,
        ),
        str(user_id),
    )
    sections.append("## TimeLogs\n" + timelog_content)

    # Planning (today/day view)
    now_dt = utc_now()
    planning_content = await export_planning_data(
        db,
        PlanningExportParams(view_type="day", selected_date=now_dt, include_notes=True),
        str(user_id),
    )
    sections.append("## Planning (today)\n" + planning_content)

    # Visions
    stmt = select(Vision).where(
        Vision.user_id == user_id,
        Vision.deleted_at.is_(None),
    )
    visions = (await db.execute(stmt)).scalars().all()
    for vision in visions:
        vision_content = await export_vision_data(
            db,
            VisionExportParams(
                include_subtasks=True,
                include_notes=True,
                include_time_records=True,
            ),
            str(user_id),
            str(vision.id),
        )
        sections.append(f"## Vision: {vision.name}\n" + vision_content)

    return "\n\n".join(sections)
