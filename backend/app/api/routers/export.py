"""
Export API endpoints
"""

from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.i18n import get_translator
from app.core.logging import get_logger
from app.db.models.user import User
from app.handlers import user_preferences as user_preferences_service
from app.handlers.actual_events import ActualEventResultTooLargeError
from app.handlers.exports.export_full import export_full_all
from app.handlers.exports.finance_accounts_export import (
    estimate_finance_accounts_export,
    export_finance_accounts_data,
)
from app.handlers.exports.finance_cashflow_export import (
    estimate_finance_cashflow_export,
    export_finance_cashflow_data,
)
from app.handlers.exports.finance_trading_export import (
    estimate_finance_trading_export,
    export_finance_trading_data,
)
from app.handlers.exports.notes_export import estimate_notes_export, export_notes_data
from app.handlers.exports.planning_export import (
    estimate_planning_export,
    export_planning_data,
)
from app.handlers.exports.timelog_export import (
    estimate_timelog_export,
    export_timelog_data,
)
from app.handlers.exports.vision_export import (
    estimate_vision_export,
    export_vision_data,
)
from app.schemas.export import (
    ExportEstimateRequest,
    ExportEstimateResult,
    ExportResult,
    FinanceAccountsExportParams,
    FinanceCashflowExportParams,
    FinanceTradingExportParams,
    NotesExportParams,
    PlanningExportParams,
    TimeLogExportParams,
    VisionExportParams,
)

router = StrictAPIRouter(
    prefix="/export",
    tags=["export"],
    responses={404: {"description": "Not found"}},
    dependencies=[Depends(get_current_user)],
)

logger = get_logger(__name__)


async def _resolve_translator(db: AsyncSession, user_id: UUID | str):
    locale = await user_preferences_service.resolve_language_preference(
        db, user_id=user_id
    )
    return get_translator(locale)


@router.post("/estimate", response_model=ExportEstimateResult)
async def export_estimate(
    request: ExportEstimateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """Estimate size for export to decide clipboard/file strategy."""

    module = request.module
    params_dict = request.params or {}

    if module == "finance-trading":
        params = FinanceTradingExportParams(**params_dict)
        record_count, estimated_size = await estimate_finance_trading_export(
            db, params=params, user_id=current_user.id
        )
    elif module == "finance-accounts":
        params = FinanceAccountsExportParams(**params_dict)
        record_count, estimated_size = await estimate_finance_accounts_export(
            db,
            params=params,
            user_id=current_user.id,
        )
    elif module == "finance-cashflow":
        params = FinanceCashflowExportParams(**params_dict)
        record_count, estimated_size = await estimate_finance_cashflow_export(
            db,
            params=params,
            user_id=current_user.id,
        )
    elif module == "notes":
        params = NotesExportParams(**params_dict)
        record_count, estimated_size = await estimate_notes_export(
            db,
            params=params,
            user_id=str(current_user.id),
        )
    elif module == "planning":
        params = PlanningExportParams(**params_dict)
        record_count, estimated_size = await estimate_planning_export(
            db,
            params=params,
            user_id=str(current_user.id),
        )
    elif module == "timelog":
        params = TimeLogExportParams(**params_dict)
        try:
            record_count, estimated_size = await estimate_timelog_export(
                db,
                params=params,
                user_id=str(current_user.id),
            )
        except ActualEventResultTooLargeError as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif module.startswith("vision:"):
        vision_id = module.split(":", 1)[1]
        params = VisionExportParams(**params_dict)
        record_count, estimated_size = await estimate_vision_export(
            db,
            params=params,
            user_id=str(current_user.id),
            vision_id=vision_id,
        )
    else:
        # Fallback conservative estimate
        record_count = 0
        estimated_size = 0

    can_clipboard = estimated_size <= 20000

    return ExportEstimateResult(
        estimated_size_bytes=estimated_size,
        record_count=record_count,
        can_clipboard=can_clipboard,
    )


@router.post("/timelog", response_model=ExportResult)
async def export_timelog(
    params: TimeLogExportParams,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """Export timelog data."""
    try:
        export_text, metadata = await export_timelog_data(
            db,
            params=params,
            user_id=str(current_user.id),
        )
        translator = await _resolve_translator(db, current_user.id)

        return ExportResult(
            success=True,
            message=translator("export.api.timelog.success"),
            export_text=export_text,
            content_type="text/plain",
            filename=f"timelog_export_{params.start_date.strftime('%Y%m%d')}.txt",
            metadata=metadata,
        )
    except ActualEventResultTooLargeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Export timelog failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export timelog data: {str(e)}",
        )


@router.post("/notes", response_model=ExportResult)
async def export_notes(
    params: NotesExportParams,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Export notes data.
    """
    try:
        export_text = await export_notes_data(
            db,
            params=params,
            user_id=str(current_user.id),
        )
        translator = await _resolve_translator(db, current_user.id)

        return ExportResult(
            success=True,
            message=translator("export.api.notes.success"),
            export_text=export_text,
            content_type="text/plain",
            filename=f"notes_export_{params.search_keyword or 'all'}.txt",
        )

    except Exception as e:
        logger.exception("Export notes failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export notes data: {str(e)}",
        )


@router.post("/planning", response_model=ExportResult)
async def export_planning(
    params: PlanningExportParams,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Export planning data.
    """
    try:
        export_text = await export_planning_data(
            db,
            params=params,
            user_id=str(current_user.id),
        )
        translator = await _resolve_translator(db, current_user.id)

        return ExportResult(
            success=True,
            message=translator("export.api.planning.success"),
            export_text=export_text,
            content_type="text/plain",
            filename=f"planning_export_{params.view_type}_{params.selected_date.strftime('%Y%m%d')}.txt",
        )

    except Exception as e:
        logger.exception("Export planning failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export planning data: {str(e)}",
        )


@router.get("/visions/{vision_id}", response_model=ExportResult)
async def export_vision(
    vision_id: str,
    include_subtasks: bool = True,
    include_notes: bool = True,
    include_time_records: bool = True,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Export vision data with task tree.
    """
    try:
        params = VisionExportParams(
            include_subtasks=include_subtasks,
            include_notes=include_notes,
            include_time_records=include_time_records,
        )

        export_text = await export_vision_data(
            db,
            params=params,
            user_id=str(current_user.id),
            vision_id=vision_id,
        )
        translator = await _resolve_translator(db, current_user.id)

        return ExportResult(
            success=True,
            message=translator("export.api.vision.success"),
            export_text=export_text,
            content_type="text/plain",
            filename=f"vision_export_{vision_id}.txt",
        )

    except Exception as e:
        logger.exception("Export vision failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export vision data: {str(e)}",
        )


@router.post("/finance/trading", response_model=ExportResult)
async def export_finance_trading(
    params: FinanceTradingExportParams,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """Export finance trading entries."""

    try:
        content, content_type, filename = await export_finance_trading_data(
            db,
            params=params,
            user_id=current_user.id,
        )

        translator = await _resolve_translator(db, current_user.id)

        return ExportResult(
            success=True,
            message=translator(
                "export.api.finance.trading.success", default="Export success"
            ),
            export_text=content,
            content_type=content_type,
            filename=filename,
        )
    except Exception as e:
        logger.exception("Export finance trading failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export finance trading data: {str(e)}",
        )


@router.post("/finance/accounts", response_model=ExportResult)
async def export_finance_accounts(
    params: FinanceAccountsExportParams,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    try:
        content, content_type, filename = await export_finance_accounts_data(
            db,
            params=params,
            user_id=current_user.id,
        )

        translator = await _resolve_translator(db, current_user.id)

        return ExportResult(
            success=True,
            message=translator(
                "export.api.finance.accounts.success", default="Export success"
            ),
            export_text=content,
            content_type=content_type,
            filename=filename,
        )
    except Exception as e:
        logger.exception("Export finance accounts failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export finance accounts: {str(e)}",
        )


@router.post("/finance/cashflow", response_model=ExportResult)
async def export_finance_cashflow(
    params: FinanceCashflowExportParams,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    try:
        content, content_type, filename = await export_finance_cashflow_data(
            db,
            params=params,
            user_id=current_user.id,
        )
        translator = await _resolve_translator(db, current_user.id)

        return ExportResult(
            success=True,
            message=translator(
                "export.api.finance.cashflow.success", default="Export success"
            ),
            export_text=content,
            content_type=content_type,
            filename=filename,
        )
    except Exception as e:
        logger.exception("Export finance cashflow failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export finance cashflow: {str(e)}",
        )


@router.post("/full", response_model=ExportResult)
async def export_full(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """Full export (finance-focused)."""

    try:
        content = await export_full_all(
            db,
            user_id=current_user.id,
        )

        translator = await _resolve_translator(db, current_user.id)

        return ExportResult(
            success=True,
            message=translator("export.api.full.success", default="Export success"),
            export_text=content,
            content_type="text/plain",
            filename="full_export.txt",
        )
    except ActualEventResultTooLargeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Export full failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export full data: {str(e)}",
        )
