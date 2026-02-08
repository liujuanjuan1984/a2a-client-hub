"""Daily review workflow API router."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Union
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import Column
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.review.daily_review_service import DailyReviewError, run_daily_review
from app.schemas.review import (
    DailyReviewCardSummary,
    DailyReviewRunRequest,
    DailyReviewRunResponse,
    DailyReviewRunResult,
)

logger = get_logger(__name__)

router = StrictAPIRouter(tags=["review"])


@router.post("/agent/review/run", response_model=DailyReviewRunResult)
async def trigger_daily_review(
    request: DailyReviewRunRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> DailyReviewRunResult:
    """Trigger daily review generation for the specified user/date."""

    target_user_id = _resolve_target_user(request.user_id, current_user)
    target_date = _resolve_target_date(request.date)

    try:
        result = await run_daily_review(
            db,
            user_id=target_user_id,
            target_date=target_date,
            force=request.force,
            trigger_source="api",
        )
    except DailyReviewError as exc:
        logger.error(
            "Daily review failed",
            extra={
                "user_id": str(target_user_id),
                "target_date": target_date.isoformat(),
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        )

    response = DailyReviewRunResponse(
        status=result.status,
        output_box=result.output_box,
        summaries=[
            DailyReviewCardSummary(
                stage=summary.stage,
                card_id=summary.card_id,
                content=summary.content,
                metadata=summary.metadata,
            )
            for summary in result.summaries
        ],
        chat_markdown=result.chat_markdown,
        error=result.error,
    )

    return DailyReviewRunResult(
        user_id=target_user_id,
        target_date=target_date,
        trigger_source="api",
        detail=response,
    )


def _resolve_target_user(
    requested_user: Optional[UUID], current_user: User
) -> Union[UUID, Column]:
    if requested_user is None:
        return current_user.id

    if requested_user != current_user.id:
        if not current_user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can specify other users",
            )
    return requested_user


def _resolve_target_date(requested_date: Optional[date]) -> date:
    if requested_date:
        return requested_date
    today = date.today()
    return today - timedelta(days=1)
