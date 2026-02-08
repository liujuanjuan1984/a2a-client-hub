"""
Agentic-friendly API facade.

This router exposes narrative-first endpoints designed for direct LLM consumption.
Internally it reuses existing export handlers, so the business formatting logic stays
in one place while we keep a stable agent-focused contract under `/agentic`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.handlers.actual_events import ActualEventResultTooLargeError
from app.handlers.exports.finance_accounts_export import export_finance_accounts_data
from app.handlers.exports.finance_cashflow_export import export_finance_cashflow_data
from app.handlers.exports.finance_trading_export import export_finance_trading_data
from app.handlers.exports.notes_export import export_notes_data
from app.handlers.exports.planning_export import export_planning_data
from app.handlers.exports.timelog_export import export_timelog_data
from app.handlers.exports.vision_export import export_vision_data
from app.schemas.agentic import AgenticTextResult
from app.schemas.export import (
    FinanceAccountsExportParams,
    FinanceCashflowExportParams,
    FinanceTradingExportParams,
    NotesExportParams,
    PlanningExportParams,
    TimeLogExportParams,
    VisionExportParams,
)

router = StrictAPIRouter(
    prefix="/agentic",
    tags=["agentic"],
    responses={404: {"description": "Not found"}},
)

logger = get_logger(__name__)


@router.post("/timelog", response_model=AgenticTextResult)
async def agentic_timelog(
    params: TimeLogExportParams,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> AgenticTextResult:
    """Narrative timelog report for a given time range."""
    try:
        content, metadata = await export_timelog_data(
            db,
            params=params,
            user_id=str(current_user.id),
        )
        return AgenticTextResult(
            module="timelog",
            content=content,
            params=params.model_dump(mode="json"),
            metadata=metadata,
        )
    except ActualEventResultTooLargeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Agentic timelog export failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export timelog data: {str(exc)}",
        ) from exc


@router.post("/notes", response_model=AgenticTextResult)
async def agentic_notes(
    params: NotesExportParams,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> AgenticTextResult:
    """Narrative notes export optimized for LLM consumption."""
    try:
        content = await export_notes_data(
            db,
            params=params,
            user_id=str(current_user.id),
        )
        return AgenticTextResult(
            module="notes",
            content=content,
            params=params.model_dump(mode="json"),
        )
    except Exception as exc:
        logger.exception("Agentic notes export failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export notes data: {str(exc)}",
        ) from exc


@router.post("/planning", response_model=AgenticTextResult)
async def agentic_planning(
    params: PlanningExportParams,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> AgenticTextResult:
    """Narrative planning export optimized for LLM consumption."""
    try:
        content = await export_planning_data(
            db,
            params=params,
            user_id=str(current_user.id),
        )
        return AgenticTextResult(
            module="planning",
            content=content,
            params=params.model_dump(mode="json"),
        )
    except Exception as exc:
        logger.exception("Agentic planning export failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export planning data: {str(exc)}",
        ) from exc


@router.post("/finance/accounts", response_model=AgenticTextResult)
async def agentic_finance_accounts(
    params: FinanceAccountsExportParams,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> AgenticTextResult:
    """Narrative finance accounts export optimized for LLM consumption."""

    try:
        content, content_type, filename = await export_finance_accounts_data(
            db,
            params=params,
            user_id=current_user.id,
        )
        return AgenticTextResult(
            module="finance-accounts",
            content=content,
            content_type=content_type,
            params=params.model_dump(mode="json"),
            metadata={"filename": filename},
        )
    except Exception as exc:
        logger.exception("Agentic finance accounts export failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export finance accounts: {str(exc)}",
        ) from exc


@router.post("/finance/cashflow", response_model=AgenticTextResult)
async def agentic_finance_cashflow(
    params: FinanceCashflowExportParams,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> AgenticTextResult:
    """Narrative finance cashflow export optimized for LLM consumption."""

    try:
        content, content_type, filename = await export_finance_cashflow_data(
            db,
            params=params,
            user_id=current_user.id,
        )
        return AgenticTextResult(
            module="finance-cashflow",
            content=content,
            content_type=content_type,
            params=params.model_dump(mode="json"),
            metadata={"filename": filename},
        )
    except Exception as exc:
        logger.exception("Agentic finance cashflow export failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export finance cashflow: {str(exc)}",
        ) from exc


@router.post("/finance/trading", response_model=AgenticTextResult)
async def agentic_finance_trading(
    params: FinanceTradingExportParams,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> AgenticTextResult:
    """Narrative finance trading export optimized for LLM consumption."""

    try:
        content, content_type, filename = await export_finance_trading_data(
            db,
            params=params,
            user_id=current_user.id,
        )
        return AgenticTextResult(
            module="finance-trading",
            content=content,
            content_type=content_type,
            params=params.model_dump(mode="json"),
            metadata={"filename": filename},
        )
    except Exception as exc:
        logger.exception("Agentic finance trading export failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export finance trading: {str(exc)}",
        ) from exc


@router.get("/visions/{vision_id}", response_model=AgenticTextResult)
async def agentic_vision(
    vision_id: UUID,
    include_subtasks: bool = Query(True),
    include_notes: bool = Query(True),
    include_time_records: bool = Query(True),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> AgenticTextResult:
    """Narrative vision export with a task tree and optional related sections."""
    try:
        params = VisionExportParams(
            include_subtasks=include_subtasks,
            include_notes=include_notes,
            include_time_records=include_time_records,
        )
        content = await export_vision_data(
            db,
            params=params,
            user_id=str(current_user.id),
            vision_id=str(vision_id),
        )
        return AgenticTextResult(
            module="vision",
            content=content,
            params={"vision_id": str(vision_id), **params.model_dump(mode="json")},
        )
    except Exception as exc:
        logger.exception("Agentic vision export failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export vision data: {str(exc)}",
        ) from exc
