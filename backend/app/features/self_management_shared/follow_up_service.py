"""Durable follow-up substrate for the built-in self-management agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict, cast
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.built_in_follow_up_task import BuiltInFollowUpTask
from app.db.models.conversation_thread import ConversationThread
from app.db.models.user import User
from app.db.transaction import commit_safely
from app.features.self_management_shared.capability_catalog import (
    SELF_FOLLOWUPS_GET,
    SELF_FOLLOWUPS_SET_SESSIONS,
)
from app.features.self_management_shared.tool_gateway import SelfManagementToolGateway
from app.utils.timezone_util import utc_now


class TargetAgentMessageAnchor(TypedDict):
    """Persisted follow-up anchor for one target conversation."""

    message_id: str
    updated_at: str
    status: str


@dataclass(frozen=True)
class BuiltInFollowUpWakeRequest:
    """One durable follow-up task ready to wake the built-in agent."""

    task_id: UUID
    user_id: UUID
    built_in_conversation_id: str
    tracked_conversation_ids: tuple[str, ...]
    previous_target_agent_message_anchors: dict[str, TargetAgentMessageAnchor]
    observed_target_agent_message_anchors: dict[str, TargetAgentMessageAnchor]
    changed_conversation_ids: tuple[str, ...]


class BuiltInFollowUpService:
    """Persist and dispatch durable follow-up substrate state."""

    async def add_tracked_sessions(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        built_in_conversation_id: str,
        conversation_ids: list[str],
    ) -> dict[str, Any]:
        """Host-level helper that merges new tracked sessions into follow-up state."""

        user_id = self._user_id(current_user)
        task = await self._get_task_by_conversation(
            db=db,
            user_id=user_id,
            built_in_conversation_id=built_in_conversation_id,
            for_update=True,
        )
        existing_ids = self._dedupe_ids(
            cast(list[str] | None, getattr(task, "tracked_conversation_ids", None))
            or []
        )
        merged_ids = self._dedupe_ids(existing_ids + list(conversation_ids))
        return await self._set_tracked_sessions(
            db=db,
            user_id=user_id,
            built_in_conversation_id=built_in_conversation_id,
            conversation_ids=merged_ids,
        )

    async def get_follow_up_state(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
    ) -> dict[str, Any]:
        built_in_conversation_id = self._require_built_in_conversation_id(gateway)
        gateway.authorize(
            operation=SELF_FOLLOWUPS_GET,
            resource_id=built_in_conversation_id,
        )
        task = await self._get_task_by_conversation(
            db=db,
            user_id=self._user_id(current_user),
            built_in_conversation_id=built_in_conversation_id,
        )
        if task is None:
            return {
                "status": "inactive",
                "built_in_conversation_id": built_in_conversation_id,
                "tracked_sessions": [],
            }
        return await self._serialize_task(
            db=db,
            user_id=self._user_id(current_user),
            task=task,
        )

    async def set_tracked_sessions(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        conversation_ids: list[str],
    ) -> dict[str, Any]:
        built_in_conversation_id = self._require_built_in_conversation_id(gateway)
        gateway.authorize(
            operation=SELF_FOLLOWUPS_SET_SESSIONS,
            resource_id=built_in_conversation_id,
        )
        return await self._set_tracked_sessions(
            db=db,
            user_id=self._user_id(current_user),
            built_in_conversation_id=built_in_conversation_id,
            conversation_ids=conversation_ids,
        )

    async def _set_tracked_sessions(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        built_in_conversation_id: str,
        conversation_ids: list[str],
    ) -> dict[str, Any]:
        deduped_ids = self._dedupe_ids(conversation_ids)
        task = await self._get_task_by_conversation(
            db=db,
            user_id=user_id,
            built_in_conversation_id=built_in_conversation_id,
            for_update=True,
        )
        if task is None:
            task = BuiltInFollowUpTask(
                user_id=user_id,
                built_in_conversation_id=UUID(built_in_conversation_id),
            )
            db.add(task)
            await db.flush()

        if not deduped_ids:
            setattr(task, "status", BuiltInFollowUpTask.STATUS_COMPLETED)
            setattr(task, "tracked_conversation_ids", [])
            setattr(task, "target_agent_message_anchors", {})
            setattr(task, "last_run_error", None)
            await commit_safely(db)
            await db.refresh(task)
            return await self._serialize_task(db=db, user_id=user_id, task=task)

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
        setattr(task, "status", BuiltInFollowUpTask.STATUS_WAITING)
        setattr(
            task,
            "tracked_conversation_ids",
            [item["conversation_id"] for item in tracked_items],
        )
        setattr(task, "target_agent_message_anchors", anchors)
        setattr(task, "last_run_error", None)
        await commit_safely(db)
        await db.refresh(task)
        payload = await self._serialize_task(db=db, user_id=user_id, task=task)
        payload["tracked_sessions"] = tracked_items
        return payload

    async def recover_stale_running_tasks(
        self, *, db: AsyncSession, timeout_seconds: int
    ) -> int:
        cutoff = utc_now()
        recovered = 0
        rows = list(
            (
                await db.scalars(
                    select(BuiltInFollowUpTask)
                    .where(
                        BuiltInFollowUpTask.status == BuiltInFollowUpTask.STATUS_RUNNING
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for task in rows:
            started_at = cast(Any, task.last_run_started_at)
            if started_at is None:
                setattr(task, "status", BuiltInFollowUpTask.STATUS_WAITING)
                recovered += 1
                continue
            if (cutoff - started_at).total_seconds() < timeout_seconds:
                continue
            setattr(task, "status", BuiltInFollowUpTask.STATUS_WAITING)
            recovered += 1
        if recovered:
            await commit_safely(db)
        return recovered

    async def claim_due_follow_up_tasks(
        self,
        *,
        db: AsyncSession,
        batch_size: int,
    ) -> list[BuiltInFollowUpWakeRequest]:
        rows = list(
            (
                await db.scalars(
                    select(BuiltInFollowUpTask)
                    .where(
                        BuiltInFollowUpTask.status == BuiltInFollowUpTask.STATUS_WAITING
                    )
                    .order_by(BuiltInFollowUpTask.updated_at.asc())
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        requests: list[BuiltInFollowUpWakeRequest] = []
        now = utc_now()
        for task in rows:
            user_id = cast(UUID, task.user_id)
            tracked_conversation_ids = self._dedupe_ids(
                cast(list[str] | None, task.tracked_conversation_ids) or []
            )
            if not tracked_conversation_ids:
                setattr(task, "status", BuiltInFollowUpTask.STATUS_COMPLETED)
                continue
            latest_anchors: dict[str, TargetAgentMessageAnchor] = {}
            changed = False
            changed_conversation_ids: list[str] = []
            existing_anchors = self._normalize_anchor_map(
                task.target_agent_message_anchors or {}
            )
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
                continue
            setattr(task, "status", BuiltInFollowUpTask.STATUS_RUNNING)
            setattr(task, "last_run_started_at", now)
            setattr(task, "last_run_error", None)
            requests.append(
                BuiltInFollowUpWakeRequest(
                    task_id=cast(UUID, task.id),
                    user_id=user_id,
                    built_in_conversation_id=str(
                        cast(UUID, task.built_in_conversation_id)
                    ),
                    tracked_conversation_ids=tuple(tracked_conversation_ids),
                    previous_target_agent_message_anchors=dict(existing_anchors),
                    observed_target_agent_message_anchors=dict(latest_anchors),
                    changed_conversation_ids=tuple(changed_conversation_ids),
                )
            )
        if requests:
            await commit_safely(db)
        elif any(task.status == BuiltInFollowUpTask.STATUS_COMPLETED for task in rows):
            await commit_safely(db)
        return requests

    async def complete_follow_up_run(
        self,
        *,
        db: AsyncSession,
        task_id: UUID,
        next_target_agent_message_anchors: dict[str, TargetAgentMessageAnchor],
    ) -> None:
        task = await db.get(BuiltInFollowUpTask, task_id)
        if task is None:
            return
        if task.status != BuiltInFollowUpTask.STATUS_RUNNING:
            return
        tracked_conversation_ids = (
            cast(list[str] | None, task.tracked_conversation_ids) or []
        )
        normalized_anchors = self._normalize_anchor_map(
            next_target_agent_message_anchors
        )
        setattr(
            task,
            "target_agent_message_anchors",
            {
                conversation_id: anchor
                for conversation_id, anchor in normalized_anchors.items()
                if conversation_id in tracked_conversation_ids
                and self._anchor_message_id(anchor) is not None
            },
        )
        setattr(
            task,
            "status",
            (
                BuiltInFollowUpTask.STATUS_WAITING
                if tracked_conversation_ids
                else BuiltInFollowUpTask.STATUS_COMPLETED
            ),
        )
        setattr(task, "last_run_finished_at", utc_now())
        setattr(task, "last_run_error", None)
        await commit_safely(db)

    async def fail_follow_up_run(
        self,
        *,
        db: AsyncSession,
        task_id: UUID,
        error: str,
    ) -> None:
        task = await db.get(BuiltInFollowUpTask, task_id)
        if task is None:
            return
        setattr(task, "status", BuiltInFollowUpTask.STATUS_FAILED)
        setattr(task, "last_run_finished_at", utc_now())
        setattr(task, "last_run_error", error[:255])
        await commit_safely(db)

    async def _serialize_task(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        task: BuiltInFollowUpTask,
    ) -> dict[str, Any]:
        tracked_items: list[dict[str, Any]] = []
        anchor_by_conversation = self._normalize_anchor_map(
            task.target_agent_message_anchors or {}
        )
        for conversation_id in self._dedupe_ids(
            cast(list[str] | None, task.tracked_conversation_ids) or []
        ):
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
            "built_in_conversation_id": str(cast(UUID, task.built_in_conversation_id)),
            "tracked_sessions": tracked_items,
            "last_run_started_at": task.last_run_started_at,
            "last_run_finished_at": task.last_run_finished_at,
            "last_run_error": cast(str | None, task.last_run_error),
        }

    async def _get_task_by_conversation(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        built_in_conversation_id: str,
        for_update: bool = False,
    ) -> BuiltInFollowUpTask | None:
        stmt = select(BuiltInFollowUpTask).where(
            BuiltInFollowUpTask.user_id == user_id,
            BuiltInFollowUpTask.built_in_conversation_id
            == UUID(built_in_conversation_id),
        )
        if for_update:
            stmt = stmt.with_for_update()
        return cast(BuiltInFollowUpTask | None, await db.scalar(stmt.limit(1)))

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

    @staticmethod
    def _require_built_in_conversation_id(gateway: SelfManagementToolGateway) -> str:
        if gateway.web_agent_conversation_id is None:
            raise ValueError("built_in_conversation_context_required")
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


built_in_follow_up_service = BuiltInFollowUpService()


__all__ = [
    "BuiltInFollowUpWakeRequest",
    "BuiltInFollowUpService",
    "TargetAgentMessageAnchor",
    "built_in_follow_up_service",
]
