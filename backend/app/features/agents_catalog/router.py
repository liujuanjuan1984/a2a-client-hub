"""Unified current-user agent catalog routes."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from fastapi import Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.features.agents_catalog.schemas import (
    UnifiedAgentCatalogItem,
    UnifiedAgentCatalogResponse,
    UnifiedAgentHealthCheckItem,
    UnifiedAgentHealthCheckResponse,
    UnifiedAgentHealthCheckSummary,
)
from app.features.agents_catalog.service import unified_agent_catalog_service

router = StrictAPIRouter(prefix="/me/agents", tags=["agents-catalog"])
logger = get_logger(__name__)


@router.get("/catalog", response_model=UnifiedAgentCatalogResponse)
async def list_current_user_agent_catalog(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> UnifiedAgentCatalogResponse:
    current_user_id = cast(UUID, current_user.id)
    items = await unified_agent_catalog_service.list_catalog(
        db,
        user_id=current_user_id,
    )
    return UnifiedAgentCatalogResponse(
        items=[UnifiedAgentCatalogItem(**item) for item in items]
    )


@router.post(
    "/check-health",
    response_model=UnifiedAgentHealthCheckResponse,
    status_code=status.HTTP_200_OK,
)
async def check_current_user_agent_catalog_health(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    force: bool = Query(
        False,
        description="Set to true to bypass cooldown for eligible personal agents.",
    ),
) -> UnifiedAgentHealthCheckResponse:
    current_user_id = cast(UUID, current_user.id)
    logger.info(
        "Unified agent catalog health check requested",
        extra={
            "user_id": str(current_user_id),
            "force": force,
        },
    )
    summary, items = await unified_agent_catalog_service.check_catalog_health(
        db,
        user_id=current_user_id,
        force=force,
    )
    return UnifiedAgentHealthCheckResponse(
        summary=UnifiedAgentHealthCheckSummary(
            requested=summary.requested,
            checked=summary.checked,
            skipped_cooldown=summary.skipped_cooldown,
            healthy=summary.healthy,
            degraded=summary.degraded,
            unavailable=summary.unavailable,
            unknown=summary.unknown,
        ),
        items=[
            UnifiedAgentHealthCheckItem(
                agent_id=item.agent_id,
                agent_source=cast(Any, item.agent_source),
                health_status=cast(Any, item.health_status),
                checked_at=item.checked_at,
                skipped_cooldown=item.skipped_cooldown,
                error=item.error,
                reason_code=cast(Any, item.reason_code),
            )
            for item in items
        ],
    )
