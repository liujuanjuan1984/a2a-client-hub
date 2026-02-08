"""A2A client session listing endpoints (/me/sessions)."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.config import settings
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.agent_session import AgentSession
from app.db.models.user import User
from app.handlers import agent_message as agent_message_handler
from app.schemas.me_sessions import (
    MeSessionItem,
    MeSessionListResponse,
    MeSessionMessageItem,
    MeSessionMessageListResponse,
    MeSessionSource,
)

router = StrictAPIRouter(prefix="/me/sessions", tags=["me-sessions"])


def _ensure_a2a_enabled() -> None:
    if not settings.a2a_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A2A integration is disabled",
        )


def _sender_to_role(sender: str) -> str:
    normalized = (sender or "").strip().lower()
    if normalized in {"user", "automation"}:
        return "user"
    if normalized == "agent":
        return "agent"
    return "system"


async def _get_scheduled_session(
    db: AsyncSession, *, user_id: UUID, session_id: UUID
) -> AgentSession:
    stmt = select(AgentSession).where(
        and_(
            AgentSession.id == session_id,
            AgentSession.user_id == user_id,
            AgentSession.session_type == AgentSession.TYPE_SCHEDULED,
            AgentSession.deleted_at.is_(None),
        )
    )
    session = await db.scalar(stmt)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


async def _latest_execution_for_session(
    db: AsyncSession, *, user_id: UUID, session_id: UUID
) -> Optional[A2AScheduleExecution]:
    stmt = (
        select(A2AScheduleExecution)
        .where(
            and_(
                A2AScheduleExecution.user_id == user_id,
                A2AScheduleExecution.session_id == session_id,
            )
        )
        .order_by(
            A2AScheduleExecution.created_at.desc(),
            A2AScheduleExecution.id.desc(),
        )
        .limit(1)
    )
    return await db.scalar(stmt)


async def _agent_id_for_task(db: AsyncSession, *, task_id: UUID) -> Optional[UUID]:
    stmt = select(A2AScheduleTask.agent_id).where(A2AScheduleTask.id == task_id)
    return await db.scalar(stmt)


@router.get("", response_model=MeSessionListResponse)
async def list_sessions(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    size: int = Query(20, ge=1, le=100, description="Number of sessions per page"),
    source: Optional[MeSessionSource] = Query(
        None, description="Filter sessions by source (manual or scheduled)"
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> MeSessionListResponse:
    _ensure_a2a_enabled()

    # We only expose scheduled sessions in phase 1. Manual sessions may exist for
    # Compass agents, but A2A manual history is intentionally not included yet.
    if source == "manual":
        return MeSessionListResponse(
            items=[],
            pagination={
                "page": page,
                "size": size,
                "total": 0,
                "pages": 0,
            },
            meta={},
        )

    offset = (page - 1) * size
    user_id = current_user.id

    latest_exec_key = (
        select(
            A2AScheduleExecution.session_id.label("session_id"),
            func.max(A2AScheduleExecution.created_at).label("max_created_at"),
        )
        .where(
            and_(
                A2AScheduleExecution.user_id == user_id,
                A2AScheduleExecution.session_id.is_not(None),
            )
        )
        .group_by(A2AScheduleExecution.session_id)
        .subquery()
    )

    latest_exec = A2AScheduleExecution.__table__.alias("latest_exec")

    stmt = (
        select(
            AgentSession,
            latest_exec.c.id.label("run_id"),
            latest_exec.c.task_id.label("task_id"),
            A2AScheduleTask.agent_id.label("agent_id"),
        )
        .outerjoin(
            latest_exec_key,
            latest_exec_key.c.session_id == AgentSession.id,
        )
        .outerjoin(
            latest_exec,
            and_(
                latest_exec.c.session_id == latest_exec_key.c.session_id,
                latest_exec.c.created_at == latest_exec_key.c.max_created_at,
            ),
        )
        .outerjoin(A2AScheduleTask, A2AScheduleTask.id == latest_exec.c.task_id)
        .where(
            and_(
                AgentSession.user_id == user_id,
                AgentSession.session_type == AgentSession.TYPE_SCHEDULED,
                AgentSession.deleted_at.is_(None),
            )
        )
        .order_by(
            AgentSession.last_activity_at.desc(),
            AgentSession.created_at.desc(),
        )
        .offset(offset)
        .limit(size)
    )

    count_stmt = (
        select(func.count(AgentSession.id))
        .where(
            and_(
                AgentSession.user_id == user_id,
                AgentSession.session_type == AgentSession.TYPE_SCHEDULED,
                AgentSession.deleted_at.is_(None),
            )
        )
        .select_from(AgentSession)
    )

    rows = (await db.execute(stmt)).all()
    total = int(await db.scalar(count_stmt) or 0)
    pages = (total + size - 1) // size if size else 0

    items = []
    for session, run_id, task_id, agent_id in rows:
        items.append(
            MeSessionItem(
                id=session.id,
                agent_id=agent_id,
                title=session.name or None,
                source="scheduled",
                job_id=task_id,
                run_id=run_id,
                last_active_at=session.last_activity_at,
                created_at=session.created_at,
            )
        )

    return MeSessionListResponse(
        items=items,
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={},
    )


@router.get("/{session_id}", response_model=MeSessionItem)
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> MeSessionItem:
    _ensure_a2a_enabled()
    session = await _get_scheduled_session(
        db, user_id=current_user.id, session_id=session_id
    )
    latest = await _latest_execution_for_session(
        db, user_id=current_user.id, session_id=session_id
    )
    agent_id = None
    job_id = None
    run_id = None
    if latest is not None:
        job_id = latest.task_id
        run_id = latest.id
        agent_id = await _agent_id_for_task(db, task_id=latest.task_id)

    return MeSessionItem(
        id=session.id,
        agent_id=agent_id,
        title=session.name or None,
        source="scheduled",
        job_id=job_id,
        run_id=run_id,
        last_active_at=session.last_activity_at,
        created_at=session.created_at,
    )


@router.get("/{session_id}/messages", response_model=MeSessionMessageListResponse)
async def list_session_messages(
    session_id: UUID,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    size: int = Query(50, ge=1, le=200, description="Page size"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> MeSessionMessageListResponse:
    _ensure_a2a_enabled()
    await _get_scheduled_session(db, user_id=current_user.id, session_id=session_id)

    offset = (page - 1) * size
    messages = await agent_message_handler.list_agent_messages(
        db,
        user_id=current_user.id,
        limit=size,
        offset=offset,
        session_id=session_id,
    )
    total = await agent_message_handler.count_agent_messages(
        db,
        user_id=current_user.id,
        session_id=session_id,
    )
    pages = (total + size - 1) // size if size else 0

    items = []
    for message in messages:
        metadata_raw = getattr(message, "message_metadata", None) or {}
        if not isinstance(metadata_raw, dict):
            metadata_raw = {}
        items.append(
            MeSessionMessageItem(
                id=message.id,
                role=_sender_to_role(getattr(message, "sender", "")),
                content=message.content or "",
                created_at=message.created_at,
                metadata=dict(metadata_raw),
            )
        )

    return MeSessionMessageListResponse(
        items=items,
        pagination={
            "page": page,
            "size": size,
            "total": int(total),
            "pages": pages,
        },
        meta={
            "session_id": str(session_id),
        },
    )


__all__ = ["router"]
