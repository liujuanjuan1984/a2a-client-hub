"""Durable background task substrate for the Hub Assistant."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal, TypedDict, cast
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.db.models.hub_assistant_task import HubAssistantTask
from app.db.models.user import User
from app.db.transaction import commit_safely
from app.features.hub_assistant_shared.capability_catalog import (
    HUB_ASSISTANT_FOLLOWUPS_GET,
    HUB_ASSISTANT_FOLLOWUPS_SET_SESSIONS,
)
from app.features.hub_assistant_shared.tool_gateway import HubAssistantToolGateway
from app.utils.timezone_util import utc_now

HubAssistantTaskKind = Literal[
    "follow_up_watch",
    "permission_reply_continuation",
    "delegated_invoke",
]


class TargetAgentMessageAnchor(TypedDict):
    """Persisted follow-up anchor for one target conversation."""

    message_id: str
    updated_at: str
    status: str


@dataclass(frozen=True)
class HubAssistantFollowUpTaskRequest:
    """One durable follow-up task ready to wake the Hub Assistant."""

    task_id: UUID
    user_id: UUID
    hub_assistant_conversation_id: str
    tracked_conversation_ids: tuple[str, ...]
    previous_target_agent_message_anchors: dict[str, TargetAgentMessageAnchor]
    observed_target_agent_message_anchors: dict[str, TargetAgentMessageAnchor]
    changed_conversation_ids: tuple[str, ...]


@dataclass(frozen=True)
class PermissionReplyContinuationTaskRequest:
    """All state required to resume one accepted permission reply durably."""

    current_user_id: UUID
    hub_assistant_conversation_id: str
    message: str
    request_id: str
    agent_message_id: UUID
    approved_operation_ids: frozenset[str]


@dataclass(frozen=True)
class DelegatedInvokeTaskRequest:
    """One durable delegated handoff request owned by the Hub Assistant."""

    current_user_id: UUID
    hub_assistant_conversation_id: str
    agent_id: UUID
    agent_source: Literal["personal", "shared"]
    message: str
    conversation_id: str | None
    target_kind: Literal["session", "agent"]
    target_id: str


@dataclass(frozen=True)
class HubAssistantTaskWorkItem:
    """One claimed durable task ready for execution."""

    task_id: UUID
    user_id: UUID
    hub_assistant_conversation_id: str
    task_kind: HubAssistantTaskKind
    request: (
        HubAssistantFollowUpTaskRequest
        | PermissionReplyContinuationTaskRequest
        | DelegatedInvokeTaskRequest
    )


@dataclass(frozen=True)
class HubAssistantFollowUpTaskCompletion:
    """Completion payload for one durable follow-up watch task."""

    next_target_agent_message_anchors: dict[str, TargetAgentMessageAnchor]


class HubAssistantTaskService:
    """Persist, inspect, and dispatch durable Hub Assistant tasks."""

    async def add_tracked_sessions(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        hub_assistant_conversation_id: str,
        conversation_ids: list[str],
    ) -> dict[str, Any]:
        """Host-level helper that merges new tracked sessions into follow-up state."""

        user_id = self._user_id(current_user)
        task = await self._get_follow_up_task_by_conversation(
            db=db,
            user_id=user_id,
            hub_assistant_conversation_id=hub_assistant_conversation_id,
            for_update=True,
        )
        existing_ids = self._follow_up_tracked_conversation_ids(task)
        merged_ids = self._dedupe_ids(existing_ids + list(conversation_ids))
        return await self._set_tracked_sessions(
            db=db,
            user_id=user_id,
            hub_assistant_conversation_id=hub_assistant_conversation_id,
            conversation_ids=merged_ids,
        )

    async def get_follow_up_state(
        self,
        *,
        db: AsyncSession,
        gateway: HubAssistantToolGateway,
        current_user: User,
    ) -> dict[str, Any]:
        hub_assistant_conversation_id = self._require_hub_assistant_conversation_id(
            gateway
        )
        gateway.authorize(
            operation=HUB_ASSISTANT_FOLLOWUPS_GET,
            resource_id=hub_assistant_conversation_id,
        )
        task = await self._get_follow_up_task_by_conversation(
            db=db,
            user_id=self._user_id(current_user),
            hub_assistant_conversation_id=hub_assistant_conversation_id,
        )
        if task is None:
            return {
                "status": "inactive",
                "hub_assistant_conversation_id": hub_assistant_conversation_id,
                "tracked_sessions": [],
            }
        return await self._serialize_follow_up_state(
            db=db,
            user_id=self._user_id(current_user),
            task=task,
        )

    async def set_tracked_sessions(
        self,
        *,
        db: AsyncSession,
        gateway: HubAssistantToolGateway,
        current_user: User,
        conversation_ids: list[str],
    ) -> dict[str, Any]:
        hub_assistant_conversation_id = self._require_hub_assistant_conversation_id(
            gateway
        )
        gateway.authorize(
            operation=HUB_ASSISTANT_FOLLOWUPS_SET_SESSIONS,
            resource_id=hub_assistant_conversation_id,
        )
        return await self._set_tracked_sessions(
            db=db,
            user_id=self._user_id(current_user),
            hub_assistant_conversation_id=hub_assistant_conversation_id,
            conversation_ids=conversation_ids,
        )

    async def enqueue_permission_reply_continuation(
        self,
        *,
        db: AsyncSession,
        request: PermissionReplyContinuationTaskRequest,
    ) -> UUID:
        dedupe_key = self._permission_reply_dedupe_key(request.request_id)
        existing = await self._get_task_by_dedupe_key(
            db=db,
            dedupe_key=dedupe_key,
            for_update=True,
        )
        if existing is not None:
            return cast(UUID, existing.id)
        task = HubAssistantTask(
            user_id=request.current_user_id,
            hub_assistant_conversation_id=UUID(request.hub_assistant_conversation_id),
            task_kind=HubAssistantTask.KIND_PERMISSION_REPLY_CONTINUATION,
            dedupe_key=dedupe_key,
            task_payload={
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
        request: DelegatedInvokeTaskRequest,
    ) -> UUID:
        task = HubAssistantTask(
            user_id=request.current_user_id,
            hub_assistant_conversation_id=UUID(request.hub_assistant_conversation_id),
            task_kind=HubAssistantTask.KIND_DELEGATED_INVOKE,
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
                    select(HubAssistantTask)
                    .where(HubAssistantTask.status == HubAssistantTask.STATUS_RUNNING)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for task in rows:
            started_at = cast(Any, task.last_run_started_at)
            if started_at is None:
                setattr(task, "status", HubAssistantTask.STATUS_WAITING)
                recovered += 1
                continue
            if (cutoff - started_at).total_seconds() < timeout_seconds:
                continue
            setattr(task, "status", HubAssistantTask.STATUS_WAITING)
            recovered += 1
        if recovered:
            await commit_safely(db)
        return recovered

    async def claim_due_tasks(
        self,
        *,
        db: AsyncSession,
        batch_size: int,
    ) -> list[HubAssistantTaskWorkItem]:
        now = utc_now()
        claimed: list[HubAssistantTaskWorkItem] = []
        mutated = False

        dispatch_rows = await self._get_waiting_rows(
            db=db,
            task_kinds=(
                HubAssistantTask.KIND_PERMISSION_REPLY_CONTINUATION,
                HubAssistantTask.KIND_DELEGATED_INVOKE,
            ),
            batch_size=batch_size,
        )
        for task in dispatch_rows:
            setattr(task, "status", HubAssistantTask.STATUS_RUNNING)
            setattr(task, "last_run_started_at", now)
            setattr(task, "last_run_finished_at", None)
            setattr(task, "last_run_error", None)
            claimed.append(self._deserialize_task(task))
        mutated = mutated or bool(dispatch_rows)

        remaining = max(batch_size - len(claimed), 0)
        if remaining:
            follow_up_rows = await self._get_waiting_rows(
                db=db,
                task_kinds=(HubAssistantTask.KIND_FOLLOW_UP_WATCH,),
                batch_size=remaining,
            )
            for task in follow_up_rows:
                work_item, task_mutated = await self._claim_follow_up_task(
                    db=db,
                    task=task,
                    now=now,
                )
                mutated = mutated or task_mutated
                if work_item is not None:
                    claimed.append(work_item)

        if mutated:
            await commit_safely(db)
        return claimed

    async def complete_task(
        self,
        *,
        db: AsyncSession,
        task_id: UUID,
        follow_up_completion: HubAssistantFollowUpTaskCompletion | None = None,
    ) -> None:
        task = await self._get_task_by_id(db=db, task_id=task_id, for_update=True)
        if task is None:
            return
        if task.task_kind == HubAssistantTask.KIND_FOLLOW_UP_WATCH:
            if follow_up_completion is None:
                raise ValueError("follow_up_completion_required")
            if task.status != HubAssistantTask.STATUS_RUNNING:
                return
            tracked_conversation_ids = self._follow_up_tracked_conversation_ids(task)
            normalized_anchors = self._normalize_anchor_map(
                follow_up_completion.next_target_agent_message_anchors
            )
            setattr(
                task,
                "task_payload",
                {
                    "tracked_conversation_ids": tracked_conversation_ids,
                    "target_agent_message_anchors": {
                        conversation_id: anchor
                        for conversation_id, anchor in normalized_anchors.items()
                        if conversation_id in tracked_conversation_ids
                        and self._anchor_message_id(anchor) is not None
                    },
                },
            )
            setattr(
                task,
                "status",
                (
                    HubAssistantTask.STATUS_WAITING
                    if tracked_conversation_ids
                    else HubAssistantTask.STATUS_COMPLETED
                ),
            )
            setattr(task, "last_run_finished_at", utc_now())
            setattr(task, "last_run_error", None)
            await commit_safely(db)
            return

        setattr(task, "status", HubAssistantTask.STATUS_COMPLETED)
        setattr(task, "last_run_finished_at", utc_now())
        setattr(task, "last_run_error", None)
        await commit_safely(db)

    async def fail_task(
        self,
        *,
        db: AsyncSession,
        task_id: UUID,
        error: str,
    ) -> None:
        task = await self._get_task_by_id(db=db, task_id=task_id, for_update=True)
        if task is None:
            return
        setattr(task, "status", HubAssistantTask.STATUS_FAILED)
        setattr(task, "last_run_finished_at", utc_now())
        setattr(task, "last_run_error", self._truncate_error(error))
        await commit_safely(db)

    async def _set_tracked_sessions(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        hub_assistant_conversation_id: str,
        conversation_ids: list[str],
    ) -> dict[str, Any]:
        deduped_ids = self._dedupe_ids(conversation_ids)
        task = await self._get_follow_up_task_by_conversation(
            db=db,
            user_id=user_id,
            hub_assistant_conversation_id=hub_assistant_conversation_id,
            for_update=True,
        )
        if task is None:
            task = HubAssistantTask(
                user_id=user_id,
                hub_assistant_conversation_id=UUID(hub_assistant_conversation_id),
                task_kind=HubAssistantTask.KIND_FOLLOW_UP_WATCH,
                task_payload={
                    "tracked_conversation_ids": [],
                    "target_agent_message_anchors": {},
                },
            )
            db.add(task)
            await db.flush()

        if not deduped_ids:
            setattr(task, "status", HubAssistantTask.STATUS_COMPLETED)
            setattr(
                task,
                "task_payload",
                {
                    "tracked_conversation_ids": [],
                    "target_agent_message_anchors": {},
                },
            )
            setattr(task, "last_run_error", None)
            await commit_safely(db)
            await db.refresh(task)
            return await self._serialize_follow_up_state(
                db=db,
                user_id=user_id,
                task=task,
            )

        tracked_items: list[dict[str, Any]] = []
        anchors: dict[str, TargetAgentMessageAnchor] = {}
        for conversation_id in deduped_ids:
            thread = await self._get_trackable_thread(
                db=db,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            latest_agent_message_anchor = (
                await self._find_latest_agent_text_message_anchor(
                    db=db,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
            )
            tracked_items.append(
                {
                    "conversation_id": conversation_id,
                    "title": cast(str, thread.title),
                    "status": cast(str, thread.status),
                    "latest_agent_message_id": self._anchor_message_id(
                        latest_agent_message_anchor
                    ),
                }
            )
            if latest_agent_message_anchor is not None:
                anchors[conversation_id] = latest_agent_message_anchor
        setattr(task, "status", HubAssistantTask.STATUS_WAITING)
        setattr(
            task,
            "task_payload",
            {
                "tracked_conversation_ids": [
                    item["conversation_id"] for item in tracked_items
                ],
                "target_agent_message_anchors": anchors,
            },
        )
        setattr(task, "last_run_error", None)
        await commit_safely(db)
        await db.refresh(task)
        payload = await self._serialize_follow_up_state(
            db=db, user_id=user_id, task=task
        )
        payload["tracked_sessions"] = tracked_items
        return payload

    async def _claim_follow_up_task(
        self,
        *,
        db: AsyncSession,
        task: HubAssistantTask,
        now: Any,
    ) -> tuple[HubAssistantTaskWorkItem | None, bool]:
        user_id = cast(UUID, task.user_id)
        tracked_conversation_ids = self._follow_up_tracked_conversation_ids(task)
        if not tracked_conversation_ids:
            setattr(task, "status", HubAssistantTask.STATUS_COMPLETED)
            return None, True

        latest_anchors: dict[str, TargetAgentMessageAnchor] = {}
        changed = False
        changed_conversation_ids: list[str] = []
        existing_anchors = self._follow_up_target_agent_message_anchors(task)
        for conversation_id in tracked_conversation_ids:
            latest_agent_message_anchor = (
                await self._find_latest_agent_text_message_anchor(
                    db=db,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
            )
            if latest_agent_message_anchor is None:
                continue
            latest_anchors[conversation_id] = latest_agent_message_anchor
            if self._anchor_changed(
                previous_anchor=existing_anchors.get(conversation_id),
                observed_anchor=latest_agent_message_anchor,
            ):
                changed = True
                changed_conversation_ids.append(conversation_id)
        if not changed:
            return None, False

        setattr(task, "status", HubAssistantTask.STATUS_RUNNING)
        setattr(task, "last_run_started_at", now)
        setattr(task, "last_run_finished_at", None)
        setattr(task, "last_run_error", None)
        return (
            HubAssistantTaskWorkItem(
                task_id=cast(UUID, task.id),
                user_id=user_id,
                hub_assistant_conversation_id=str(
                    cast(UUID, task.hub_assistant_conversation_id)
                ),
                task_kind=cast(
                    HubAssistantTaskKind,
                    HubAssistantTask.KIND_FOLLOW_UP_WATCH,
                ),
                request=HubAssistantFollowUpTaskRequest(
                    task_id=cast(UUID, task.id),
                    user_id=user_id,
                    hub_assistant_conversation_id=str(
                        cast(UUID, task.hub_assistant_conversation_id)
                    ),
                    tracked_conversation_ids=tuple(tracked_conversation_ids),
                    previous_target_agent_message_anchors=dict(existing_anchors),
                    observed_target_agent_message_anchors=dict(latest_anchors),
                    changed_conversation_ids=tuple(changed_conversation_ids),
                ),
            ),
            True,
        )

    async def _serialize_follow_up_state(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        task: HubAssistantTask,
    ) -> dict[str, Any]:
        tracked_items: list[dict[str, Any]] = []
        anchor_by_conversation = self._follow_up_target_agent_message_anchors(task)
        for conversation_id in self._follow_up_tracked_conversation_ids(task):
            title = None
            status = None
            try:
                thread = await self._get_trackable_thread(
                    db=db,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
            except ValueError:
                thread = None
            if thread is not None:
                title = cast(str, thread.title)
                status = cast(str, thread.status)
            tracked_items.append(
                {
                    "conversation_id": conversation_id,
                    "title": title,
                    "status": status,
                    "latest_agent_message_id": self._anchor_message_id(
                        anchor_by_conversation.get(conversation_id)
                    ),
                }
            )
        return {
            "task_id": str(cast(UUID, task.id)),
            "status": cast(str, task.status),
            "hub_assistant_conversation_id": str(
                cast(UUID, task.hub_assistant_conversation_id)
            ),
            "tracked_sessions": tracked_items,
            "last_run_started_at": task.last_run_started_at,
            "last_run_finished_at": task.last_run_finished_at,
            "last_run_error": cast(str | None, task.last_run_error),
        }

    async def _get_waiting_rows(
        self,
        *,
        db: AsyncSession,
        task_kinds: tuple[str, ...],
        batch_size: int,
    ) -> list[HubAssistantTask]:
        if batch_size <= 0:
            return []
        return list(
            (
                await db.scalars(
                    select(HubAssistantTask)
                    .where(
                        HubAssistantTask.status == HubAssistantTask.STATUS_WAITING,
                        HubAssistantTask.task_kind.in_(task_kinds),
                    )
                    .order_by(HubAssistantTask.updated_at.asc())
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )

    async def _get_task_by_id(
        self,
        *,
        db: AsyncSession,
        task_id: UUID,
        for_update: bool = False,
    ) -> HubAssistantTask | None:
        statement = select(HubAssistantTask).where(HubAssistantTask.id == task_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(HubAssistantTask | None, await db.scalar(statement))

    async def _get_task_by_dedupe_key(
        self,
        *,
        db: AsyncSession,
        dedupe_key: str,
        for_update: bool = False,
    ) -> HubAssistantTask | None:
        statement = select(HubAssistantTask).where(
            HubAssistantTask.dedupe_key == dedupe_key
        )
        if for_update:
            statement = statement.with_for_update()
        return cast(HubAssistantTask | None, await db.scalar(statement))

    async def _get_follow_up_task_by_conversation(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        hub_assistant_conversation_id: str,
        for_update: bool = False,
    ) -> HubAssistantTask | None:
        statement = select(HubAssistantTask).where(
            HubAssistantTask.user_id == user_id,
            HubAssistantTask.task_kind == HubAssistantTask.KIND_FOLLOW_UP_WATCH,
            HubAssistantTask.hub_assistant_conversation_id
            == UUID(hub_assistant_conversation_id),
        )
        if for_update:
            statement = statement.with_for_update()
        return cast(HubAssistantTask | None, await db.scalar(statement.limit(1)))

    def _deserialize_task(
        self,
        task: HubAssistantTask,
    ) -> HubAssistantTaskWorkItem:
        payload = cast(dict[str, Any], task.task_payload or {})
        task_kind = cast(HubAssistantTaskKind, task.task_kind)
        request: PermissionReplyContinuationTaskRequest | DelegatedInvokeTaskRequest
        if task_kind == HubAssistantTask.KIND_PERMISSION_REPLY_CONTINUATION:
            request = PermissionReplyContinuationTaskRequest(
                current_user_id=cast(UUID, task.user_id),
                hub_assistant_conversation_id=str(
                    cast(UUID, task.hub_assistant_conversation_id)
                ),
                message=str(payload["message"]),
                request_id=str(payload["request_id"]),
                agent_message_id=UUID(str(payload["agent_message_id"])),
                approved_operation_ids=frozenset(
                    str(item) for item in payload.get("approved_operation_ids", [])
                ),
            )
        elif task_kind == HubAssistantTask.KIND_DELEGATED_INVOKE:
            request = DelegatedInvokeTaskRequest(
                current_user_id=cast(UUID, task.user_id),
                hub_assistant_conversation_id=str(
                    cast(UUID, task.hub_assistant_conversation_id)
                ),
                agent_id=UUID(str(payload["agent_id"])),
                agent_source=cast(
                    Literal["personal", "shared"], payload["agent_source"]
                ),
                message=str(payload["message"]),
                conversation_id=cast(str | None, payload.get("conversation_id")),
                target_kind=cast(Literal["session", "agent"], payload["target_kind"]),
                target_id=str(payload["target_id"]),
            )
        else:  # pragma: no cover - defensive guard
            raise ValueError(f"Unsupported Hub Assistant task kind: {task_kind}")
        return HubAssistantTaskWorkItem(
            task_id=cast(UUID, task.id),
            user_id=cast(UUID, task.user_id),
            hub_assistant_conversation_id=str(
                cast(UUID, task.hub_assistant_conversation_id)
            ),
            task_kind=task_kind,
            request=request,
        )

    async def _get_trackable_thread(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        conversation_id: str,
    ) -> ConversationThread:
        thread = cast(
            ConversationThread | None,
            await db.scalar(
                select(ConversationThread).where(
                    ConversationThread.id == UUID(conversation_id),
                    ConversationThread.user_id == user_id,
                    ConversationThread.status.in_(
                        [
                            ConversationThread.STATUS_ACTIVE,
                            ConversationThread.STATUS_ARCHIVED,
                        ]
                    ),
                    ConversationThread.source.in_(
                        [
                            ConversationThread.SOURCE_MANUAL,
                            ConversationThread.SOURCE_SCHEDULED,
                        ]
                    ),
                )
            ),
        )
        if thread is None:
            raise ValueError("session_not_found")
        return thread

    async def _find_latest_agent_text_message_anchor(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        conversation_id: str,
    ) -> TargetAgentMessageAnchor | None:
        message = cast(
            AgentMessage | None,
            await db.scalar(
                select(AgentMessage)
                .where(
                    AgentMessage.user_id == user_id,
                    AgentMessage.conversation_id == UUID(conversation_id),
                    AgentMessage.sender == "agent",
                    exists(
                        select(1).where(
                            AgentMessageBlock.user_id == user_id,
                            AgentMessageBlock.message_id == AgentMessage.id,
                            AgentMessageBlock.block_type == "text",
                            func.length(func.btrim(AgentMessageBlock.content)) > 0,
                        )
                    ),
                )
                .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc())
                .limit(1)
            ),
        )
        if message is None:
            return None
        return self._build_anchor(
            message_id=str(cast(UUID, message.id)),
            updated_at=cast(Any, message.updated_at),
            status=cast(str, message.status),
        )

    def _follow_up_tracked_conversation_ids(
        self,
        task: HubAssistantTask | None,
    ) -> list[str]:
        if task is None:
            return []
        payload = cast(dict[str, Any], task.task_payload or {})
        return self._dedupe_ids(
            [str(item) for item in payload.get("tracked_conversation_ids", [])]
        )

    def _follow_up_target_agent_message_anchors(
        self,
        task: HubAssistantTask | None,
    ) -> dict[str, TargetAgentMessageAnchor]:
        if task is None:
            return {}
        payload = cast(dict[str, Any], task.task_payload or {})
        return self._normalize_anchor_map(payload.get("target_agent_message_anchors"))

    @staticmethod
    def _require_hub_assistant_conversation_id(gateway: HubAssistantToolGateway) -> str:
        if gateway.web_agent_conversation_id is None:
            raise ValueError("hub_assistant_conversation_context_required")
        return gateway.web_agent_conversation_id

    @staticmethod
    def _user_id(current_user: User) -> UUID:
        user_id = cast(UUID | None, current_user.id)
        if user_id is None:
            raise ValueError("Authenticated user id is required")
        return user_id

    @staticmethod
    def _dedupe_ids(values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    @staticmethod
    def _build_anchor(
        *, message_id: str, updated_at: Any, status: str | None
    ) -> TargetAgentMessageAnchor:
        return {
            "message_id": message_id.strip(),
            "updated_at": (
                updated_at.isoformat()
                if hasattr(updated_at, "isoformat")
                else str(updated_at or "").strip()
            ),
            "status": (status or "").strip(),
        }

    @staticmethod
    def _anchor_message_id(anchor: TargetAgentMessageAnchor | None) -> str | None:
        if anchor is None:
            return None
        message_id = str(anchor.get("message_id") or "").strip()
        return message_id or None

    @classmethod
    def _normalize_anchor_map(
        cls,
        raw_anchors: Any,
    ) -> dict[str, TargetAgentMessageAnchor]:
        if not isinstance(raw_anchors, dict):
            return {}
        normalized: dict[str, TargetAgentMessageAnchor] = {}
        for raw_conversation_id, raw_anchor in raw_anchors.items():
            conversation_id = str(raw_conversation_id or "").strip()
            if not conversation_id:
                continue
            anchor = cls._normalize_anchor(raw_anchor)
            if anchor is None:
                continue
            normalized[conversation_id] = anchor
        return normalized

    @classmethod
    def _normalize_anchor(cls, raw_anchor: Any) -> TargetAgentMessageAnchor | None:
        if isinstance(raw_anchor, str):
            message_id = raw_anchor.strip()
            if not message_id:
                return None
            return cls._build_anchor(message_id=message_id, updated_at="", status="")
        if not isinstance(raw_anchor, dict):
            return None
        message_id = str(raw_anchor.get("message_id") or "").strip()
        if not message_id:
            return None
        return cls._build_anchor(
            message_id=message_id,
            updated_at=raw_anchor.get("updated_at"),
            status=cast(str | None, raw_anchor.get("status")),
        )

    @staticmethod
    def _anchor_changed(
        previous_anchor: TargetAgentMessageAnchor | None,
        observed_anchor: TargetAgentMessageAnchor,
    ) -> bool:
        return previous_anchor != observed_anchor

    @staticmethod
    def _permission_reply_dedupe_key(request_id: str) -> str:
        digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
        return f"permission_reply:{digest}"

    @staticmethod
    def _truncate_error(error: str) -> str:
        normalized = error.strip() or "task_failed"
        return normalized[:255]


hub_assistant_task_service = HubAssistantTaskService()
