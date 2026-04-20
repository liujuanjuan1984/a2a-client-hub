"""Durable self-management dispatch task persistence helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.self_management_dispatch_task import SelfManagementDispatchTask
from app.db.transaction import commit_safely
from app.utils.timezone_util import utc_now

SelfManagementDispatchKind = Literal[
    "permission_reply_continuation",
    "delegated_invoke",
]


@dataclass(frozen=True)
class PermissionReplyContinuationDispatchRequest:
    """All state required to resume one accepted permission reply durably."""

    current_user_id: UUID
    conversation_id: str
    message: str
    request_id: str
    agent_message_id: UUID
    approved_operation_ids: frozenset[str]


@dataclass(frozen=True)
class DelegatedInvokeDispatchRequest:
    """One durable delegated handoff request owned by the built-in agent."""

    current_user_id: UUID
    agent_id: UUID
    agent_source: Literal["personal", "shared"]
    message: str
    conversation_id: str | None
    target_kind: Literal["session", "agent"]
    target_id: str


@dataclass(frozen=True)
class SelfManagementDispatchWorkItem:
    """One claimed durable dispatch task ready for execution."""

    task_id: UUID
    user_id: UUID
    task_kind: SelfManagementDispatchKind
    request: PermissionReplyContinuationDispatchRequest | DelegatedInvokeDispatchRequest


class SelfManagementDispatchService:
    """Persist and claim durable self-management background requests."""

    async def enqueue_permission_reply_continuation(
        self,
        *,
        db: AsyncSession,
        request: PermissionReplyContinuationDispatchRequest,
    ) -> UUID:
        dedupe_key = self._permission_reply_dedupe_key(request.request_id)
        existing = await self._get_task_by_dedupe_key(
            db=db,
            dedupe_key=dedupe_key,
            for_update=True,
        )
        if existing is not None:
            return cast(UUID, existing.id)
        task = SelfManagementDispatchTask(
            user_id=request.current_user_id,
            task_kind=SelfManagementDispatchTask.KIND_PERMISSION_REPLY_CONTINUATION,
            dedupe_key=dedupe_key,
            task_payload={
                "conversation_id": request.conversation_id,
                "message": request.message,
                "request_id": request.request_id,
                "agent_message_id": str(request.agent_message_id),
                "approved_operation_ids": sorted(request.approved_operation_ids),
            },
        )
        db.add(task)
        await db.flush()
        return cast(UUID, task.id)

    async def enqueue_delegated_invoke(
        self,
        *,
        db: AsyncSession,
        request: DelegatedInvokeDispatchRequest,
    ) -> UUID:
        task = SelfManagementDispatchTask(
            user_id=request.current_user_id,
            task_kind=SelfManagementDispatchTask.KIND_DELEGATED_INVOKE,
            task_payload={
                "agent_id": str(request.agent_id),
                "agent_source": request.agent_source,
                "message": request.message,
                "conversation_id": request.conversation_id,
                "target_kind": request.target_kind,
                "target_id": request.target_id,
            },
        )
        db.add(task)
        await db.flush()
        return cast(UUID, task.id)

    async def recover_stale_running_tasks(
        self, *, db: AsyncSession, timeout_seconds: int
    ) -> int:
        cutoff = utc_now()
        recovered = 0
        rows = list(
            (
                await db.scalars(
                    select(SelfManagementDispatchTask)
                    .where(
                        SelfManagementDispatchTask.status
                        == SelfManagementDispatchTask.STATUS_RUNNING
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for task in rows:
            started_at = cast(Any, task.last_run_started_at)
            if started_at is None:
                setattr(task, "status", SelfManagementDispatchTask.STATUS_WAITING)
                recovered += 1
                continue
            if (cutoff - started_at).total_seconds() < timeout_seconds:
                continue
            setattr(task, "status", SelfManagementDispatchTask.STATUS_WAITING)
            recovered += 1
        if recovered:
            await commit_safely(db)
        return recovered

    async def claim_due_dispatch_tasks(
        self,
        *,
        db: AsyncSession,
        batch_size: int,
    ) -> list[SelfManagementDispatchWorkItem]:
        rows = list(
            (
                await db.scalars(
                    select(SelfManagementDispatchTask)
                    .where(
                        SelfManagementDispatchTask.status
                        == SelfManagementDispatchTask.STATUS_WAITING
                    )
                    .order_by(SelfManagementDispatchTask.updated_at.asc())
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        claimed: list[SelfManagementDispatchWorkItem] = []
        now = utc_now()
        for task in rows:
            setattr(task, "status", SelfManagementDispatchTask.STATUS_RUNNING)
            setattr(task, "last_run_started_at", now)
            setattr(task, "last_run_finished_at", None)
            setattr(task, "last_run_error", None)
            claimed.append(self._deserialize_task(task))
        if rows:
            await commit_safely(db)
        return claimed

    async def complete_dispatch_task(
        self,
        *,
        db: AsyncSession,
        task_id: UUID,
    ) -> None:
        task = await self._get_task_by_id(db=db, task_id=task_id, for_update=True)
        if task is None:
            return
        setattr(task, "status", SelfManagementDispatchTask.STATUS_COMPLETED)
        setattr(task, "last_run_finished_at", utc_now())
        setattr(task, "last_run_error", None)
        await commit_safely(db)

    async def fail_dispatch_task(
        self,
        *,
        db: AsyncSession,
        task_id: UUID,
        error: str,
    ) -> None:
        task = await self._get_task_by_id(db=db, task_id=task_id, for_update=True)
        if task is None:
            return
        setattr(task, "status", SelfManagementDispatchTask.STATUS_FAILED)
        setattr(task, "last_run_finished_at", utc_now())
        setattr(task, "last_run_error", self._truncate_error(error))
        await commit_safely(db)

    async def _get_task_by_id(
        self,
        *,
        db: AsyncSession,
        task_id: UUID,
        for_update: bool = False,
    ) -> SelfManagementDispatchTask | None:
        statement = select(SelfManagementDispatchTask).where(
            SelfManagementDispatchTask.id == task_id
        )
        if for_update:
            statement = statement.with_for_update()
        return cast(SelfManagementDispatchTask | None, await db.scalar(statement))

    async def _get_task_by_dedupe_key(
        self,
        *,
        db: AsyncSession,
        dedupe_key: str,
        for_update: bool = False,
    ) -> SelfManagementDispatchTask | None:
        statement = select(SelfManagementDispatchTask).where(
            SelfManagementDispatchTask.dedupe_key == dedupe_key
        )
        if for_update:
            statement = statement.with_for_update()
        return cast(SelfManagementDispatchTask | None, await db.scalar(statement))

    def _deserialize_task(
        self,
        task: SelfManagementDispatchTask,
    ) -> SelfManagementDispatchWorkItem:
        payload = cast(dict[str, Any], task.task_payload or {})
        task_kind = cast(SelfManagementDispatchKind, task.task_kind)
        request: (
            PermissionReplyContinuationDispatchRequest | DelegatedInvokeDispatchRequest
        )
        if task_kind == SelfManagementDispatchTask.KIND_PERMISSION_REPLY_CONTINUATION:
            request = PermissionReplyContinuationDispatchRequest(
                current_user_id=cast(UUID, task.user_id),
                conversation_id=str(payload["conversation_id"]),
                message=str(payload["message"]),
                request_id=str(payload["request_id"]),
                agent_message_id=UUID(str(payload["agent_message_id"])),
                approved_operation_ids=frozenset(
                    str(item) for item in payload.get("approved_operation_ids", [])
                ),
            )
        elif task_kind == SelfManagementDispatchTask.KIND_DELEGATED_INVOKE:
            request = DelegatedInvokeDispatchRequest(
                current_user_id=cast(UUID, task.user_id),
                agent_id=UUID(str(payload["agent_id"])),
                agent_source=cast(
                    Literal["personal", "shared"], payload["agent_source"]
                ),
                message=str(payload["message"]),
                conversation_id=cast(str | None, payload.get("conversation_id")),
                target_kind=cast(Literal["session", "agent"], payload["target_kind"]),
                target_id=str(payload["target_id"]),
            )
        else:
            raise ValueError(
                f"Unsupported self-management dispatch task kind: {task_kind}"
            )
        return SelfManagementDispatchWorkItem(
            task_id=cast(UUID, task.id),
            user_id=cast(UUID, task.user_id),
            task_kind=task_kind,
            request=request,
        )

    @staticmethod
    def _permission_reply_dedupe_key(request_id: str) -> str:
        digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
        return f"permission_reply:{digest}"

    @staticmethod
    def _truncate_error(error: str) -> str:
        normalized = error.strip() or "dispatch_failed"
        return normalized[:255]


self_management_dispatch_service = SelfManagementDispatchService()
