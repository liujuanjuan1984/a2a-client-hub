"""Administrative endpoints for agent audit logs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_admin_user
from app.api.routing import StrictAPIRouter
from app.db.models.agent_audit_log import AgentAuditLog
from app.schemas.agent_audit import (
    AgentAuditLogItem,
    AgentAuditLogListResponse,
    AgentAuditRetentionRequest,
    AgentAuditRetentionResponse,
    AgentAuditRollbackPreview,
)
from app.utils.timezone_util import utc_now

router = StrictAPIRouter(
    prefix="/admin/agent-audit",
    tags=["admin-agent-audit"],
    dependencies=[Depends(get_current_admin_user)],
)


def _serialize_log(entry: AgentAuditLog) -> AgentAuditLogItem:
    return AgentAuditLogItem(
        id=entry.id,
        run_id=entry.run_id,
        trigger_user_id=entry.trigger_user_id,
        session_id=entry.session_id,
        message_id=entry.message_id,
        agent_name=entry.agent_name,
        tool_name=entry.tool_name,
        tool_call_id=entry.tool_call_id,
        operation=entry.operation,
        status=entry.status,
        error=entry.error,
        duration_ms=entry.duration_ms,
        target_entities=entry.target_entities,
        before_snapshot=entry.before_snapshot,
        after_snapshot=entry.after_snapshot,
        extra=entry.extra,
        created_at=entry.created_at,
    )


def _build_filters(
    *,
    user_id: Optional[UUID],
    tool_name: Optional[str],
    operation: Optional[str],
    status_filter: Optional[str],
    run_id: Optional[UUID],
    created_before: Optional[datetime],
    created_after: Optional[datetime],
):
    filters = []
    if user_id:
        filters.append(AgentAuditLog.trigger_user_id == user_id)
    if tool_name:
        filters.append(AgentAuditLog.tool_name == tool_name)
    if operation:
        filters.append(AgentAuditLog.operation == operation)
    if status_filter:
        filters.append(AgentAuditLog.status == status_filter)
    if run_id:
        filters.append(AgentAuditLog.run_id == run_id)
    if created_before:
        filters.append(AgentAuditLog.created_at < created_before)
    if created_after:
        filters.append(AgentAuditLog.created_at >= created_after)
    return filters


def _normalize_dt(candidate: Optional[datetime]) -> Optional[datetime]:
    if candidate is None:
        return None
    if candidate.tzinfo is None:
        return candidate.replace(tzinfo=timezone.utc)
    return candidate


@router.get("/logs", response_model=AgentAuditLogListResponse)
async def list_agent_audit_logs(
    *,
    db: AsyncSession = Depends(get_async_db),
    user_id: Optional[UUID] = Query(None, description="Filter by target user id"),
    tool_name: Optional[str] = Query(None, description="Filter by tool name"),
    operation: Optional[str] = Query(None, description="Filter by operation label"),
    status_filter: Optional[str] = Query(None, description="Filter by status value"),
    run_id: Optional[UUID] = Query(None, description="Filter by run identifier"),
    created_before: Optional[datetime] = Query(
        None, description="Return entries created before this timestamp"
    ),
    created_after: Optional[datetime] = Query(
        None, description="Return entries created on/after this timestamp"
    ),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
) -> AgentAuditLogListResponse:
    offset = (page - 1) * size
    filters = _build_filters(
        user_id=user_id,
        tool_name=tool_name,
        operation=operation,
        status_filter=status_filter,
        run_id=run_id,
        created_before=_normalize_dt(created_before),
        created_after=_normalize_dt(created_after),
    )
    list_stmt = (
        select(AgentAuditLog)
        .where(*filters)
        .order_by(AgentAuditLog.created_at.desc())
        .offset(offset)
        .limit(size)
    )
    rows = (await db.execute(list_stmt)).scalars().all()
    count_stmt = select(func.count()).select_from(AgentAuditLog).where(*filters)
    total = (await db.execute(count_stmt)).scalar_one()
    pages = (total + size - 1) // size if size else 0
    return AgentAuditLogListResponse(
        items=[_serialize_log(row) for row in rows],
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={
            "user_id": user_id,
            "tool_name": tool_name,
            "operation": operation,
            "status_filter": status_filter,
            "run_id": run_id,
            "created_before": created_before,
            "created_after": created_after,
        },
    )


@router.get("/logs/export", response_model=AgentAuditLogListResponse)
async def export_agent_audit_logs(
    *,
    db: AsyncSession = Depends(get_async_db),
    user_id: Optional[UUID] = Query(None, description="Filter by target user id"),
    tool_name: Optional[str] = Query(None, description="Filter by tool name"),
    operation: Optional[str] = Query(None, description="Filter by operation label"),
    status_filter: Optional[str] = Query(None, description="Filter by status value"),
    run_id: Optional[UUID] = Query(None, description="Filter by run identifier"),
    created_before: Optional[datetime] = Query(
        None, description="Return entries created before this timestamp"
    ),
    created_after: Optional[datetime] = Query(
        None, description="Return entries created on/after this timestamp"
    ),
    page: int = Query(1, ge=1),
    size: int = Query(500, ge=1, le=5000),
) -> AgentAuditLogListResponse:
    offset = (page - 1) * size
    filters = _build_filters(
        user_id=user_id,
        tool_name=tool_name,
        operation=operation,
        status_filter=status_filter,
        run_id=run_id,
        created_before=_normalize_dt(created_before),
        created_after=_normalize_dt(created_after),
    )
    list_stmt = (
        select(AgentAuditLog)
        .where(*filters)
        .order_by(AgentAuditLog.created_at.desc())
        .offset(offset)
        .limit(size)
    )
    rows = (await db.execute(list_stmt)).scalars().all()
    count_stmt = select(func.count()).select_from(AgentAuditLog).where(*filters)
    total = (await db.execute(count_stmt)).scalar_one()
    pages = (total + size - 1) // size if size else 0
    return AgentAuditLogListResponse(
        items=[_serialize_log(row) for row in rows],
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={
            "user_id": user_id,
            "tool_name": tool_name,
            "operation": operation,
            "status_filter": status_filter,
            "run_id": run_id,
            "created_before": created_before,
            "created_after": created_after,
        },
    )


@router.get("/logs/{log_id}", response_model=AgentAuditLogItem)
async def get_agent_audit_log(
    *,
    db: AsyncSession = Depends(get_async_db),
    log_id: UUID,
) -> AgentAuditLogItem:
    stmt = select(AgentAuditLog).where(AgentAuditLog.id == log_id)
    entry = (await db.execute(stmt)).scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Audit log not found"
        )
    return _serialize_log(entry)


@router.post(
    "/logs/{log_id}/rollback-preview",
    response_model=AgentAuditRollbackPreview,
)
async def preview_agent_audit_rollback(
    *,
    db: AsyncSession = Depends(get_async_db),
    log_id: UUID,
) -> AgentAuditRollbackPreview:
    stmt = select(AgentAuditLog).where(AgentAuditLog.id == log_id)
    entry = (await db.execute(stmt)).scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Audit log not found"
        )

    log_item = _serialize_log(entry)
    if not log_item.before_snapshot:
        guidance = "No before_snapshot available; manual rollback is not supported for this entry."
    else:
        target_info = log_item.target_entities or {}
        guidance = (
            "Use the before_snapshot payload to restore the impacted entities. "
            f"Operation={log_item.operation}, Targets={target_info}. "
            "Apply changes via the domain-specific admin tooling or SQL console."
        )

    return AgentAuditRollbackPreview(log=log_item, suggested_actions=guidance)


@router.post("/retention/purge", response_model=AgentAuditRetentionResponse)
async def purge_agent_audit_logs(
    *,
    db: AsyncSession = Depends(get_async_db),
    payload: AgentAuditRetentionRequest,
) -> AgentAuditRetentionResponse:
    cutoff = utc_now() - timedelta(days=payload.before_days)

    filters = [AgentAuditLog.created_at < cutoff]
    if payload.dry_run:
        count_stmt = select(func.count()).select_from(AgentAuditLog).where(*filters)
        total = (await db.execute(count_stmt)).scalar_one()
        return AgentAuditRetentionResponse(deleted_rows=total, cutoff=cutoff)

    delete_stmt = delete(AgentAuditLog).where(*filters)
    result = await db.execute(delete_stmt)
    await db.commit()
    return AgentAuditRetentionResponse(deleted_rows=result.rowcount or 0, cutoff=cutoff)


__all__ = ["router"]
