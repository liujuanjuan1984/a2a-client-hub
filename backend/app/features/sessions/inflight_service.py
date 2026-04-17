"""Inflight invoke state management for the unified session domain."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.features.sessions import common as session_common
from app.features.sessions.support import SessionHubSupport

logger = get_logger(__name__)


class SessionInflightService:
    """Tracks inflight invokes and coordinates cancellation/preemption."""

    def __init__(self, *, support: SessionHubSupport) -> None:
        self._support = support

    @staticmethod
    def _inflight_key(*, user_id: UUID, conversation_id: UUID) -> tuple[str, str]:
        return (str(user_id), str(conversation_id))

    @staticmethod
    def _copy_inflight_entry(
        entry: session_common.InflightInvokeEntry,
    ) -> session_common.InflightInvokeEntry:
        return session_common.InflightInvokeEntry(
            token=entry.token,
            task_id=entry.task_id,
            gateway=entry.gateway,
            resolved=entry.resolved,
            cancel_requested=entry.cancel_requested,
            cancel_reason=entry.cancel_reason,
            pending_preempt_event=SessionInflightService._copy_preempt_event(
                entry.pending_preempt_event
            ),
        )

    @staticmethod
    def _copy_preempt_event(
        event: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        normalized_event = session_common.normalize_preempt_event(event)
        if normalized_event is None:
            return None
        normalized_event["target_task_ids"] = list(
            normalized_event.get("target_task_ids") or []
        )
        normalized_event["failed_error_codes"] = list(
            normalized_event.get("failed_error_codes") or []
        )
        return normalized_event

    @classmethod
    def _build_pending_preempt_event(
        cls,
        event: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not isinstance(event, dict):
            return None
        return cls._copy_preempt_event(
            {
                **event,
                "status": "accepted",
                "target_task_ids": [],
                "failed_error_codes": [],
            }
        )

    @classmethod
    def _resolve_pending_preempt_event(
        cls,
        *,
        pending_event: dict[str, Any] | None,
        task_id: str,
        success: bool,
        error_code: str | None,
    ) -> dict[str, Any] | None:
        copied_event = cls._copy_preempt_event(pending_event)
        if copied_event is None:
            return None
        copied_event["status"] = "completed" if success else "failed"
        copied_event["target_task_ids"] = [task_id]
        copied_event["failed_error_codes"] = [error_code] if error_code else []
        return copied_event

    async def register_inflight_invoke(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        gateway: Any,
        resolved: Any,
    ) -> str:
        token = str(uuid4())
        key = self._inflight_key(user_id=user_id, conversation_id=conversation_id)
        async with session_common.inflight_invokes_lock:
            bucket = session_common.inflight_invokes.setdefault(key, {})
            bucket[token] = session_common.InflightInvokeEntry(
                token=token,
                task_id=None,
                gateway=gateway,
                resolved=resolved,
            )
        return token

    async def bind_inflight_task_id_report(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        token: str,
        task_id: str,
    ) -> session_common.BindInflightTaskReport:
        normalized_task_id = session_common.normalize_non_empty_text(task_id)
        if not normalized_task_id:
            return session_common.BindInflightTaskReport(bound=False)
        key = self._inflight_key(user_id=user_id, conversation_id=conversation_id)
        pending_cancel_snapshot: session_common.InflightInvokeEntry | None = None
        async with session_common.inflight_invokes_lock:
            bucket = session_common.inflight_invokes.get(key)
            current = bucket.get(token) if bucket is not None else None
            if current is None or current.token != token:
                return session_common.BindInflightTaskReport(bound=False)
            current.task_id = normalized_task_id
            if current.cancel_requested:
                pending_cancel_snapshot = self._copy_inflight_entry(current)
        deferred_preempt_event: dict[str, Any] | None = None
        if pending_cancel_snapshot is not None:
            try:
                success, error_code = await self._cancel_inflight_task(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    snapshot=pending_cancel_snapshot,
                    reason=pending_cancel_snapshot.cancel_reason or "hub_user_cancel",
                )
                deferred_preempt_event = self._resolve_pending_preempt_event(
                    pending_event=pending_cancel_snapshot.pending_preempt_event,
                    task_id=normalized_task_id,
                    success=success,
                    error_code=error_code,
                )
                if not success:
                    logger.warning(
                        "Deferred inflight cancellation failed after task binding",
                        extra={
                            "user_id": str(user_id),
                            "conversation_id": str(conversation_id),
                            "token": pending_cancel_snapshot.token,
                            "task_id": pending_cancel_snapshot.task_id,
                            "error_code": error_code,
                        },
                    )
            except Exception:
                deferred_preempt_event = self._resolve_pending_preempt_event(
                    pending_event=pending_cancel_snapshot.pending_preempt_event,
                    task_id=normalized_task_id,
                    success=False,
                    error_code="cancel_exception",
                )
                logger.warning(
                    "Deferred inflight cancellation raised after task binding",
                    exc_info=True,
                    extra={
                        "user_id": str(user_id),
                        "conversation_id": str(conversation_id),
                        "token": pending_cancel_snapshot.token,
                        "task_id": pending_cancel_snapshot.task_id,
                    },
                )
        return session_common.BindInflightTaskReport(
            bound=True,
            preempt_event=deferred_preempt_event,
        )

    async def bind_inflight_task_id(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        token: str,
        task_id: str,
    ) -> bool:
        report = await self.bind_inflight_task_id_report(
            user_id=user_id,
            conversation_id=conversation_id,
            token=token,
            task_id=task_id,
        )
        return report.bound

    async def unregister_inflight_invoke(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        token: str,
    ) -> bool:
        key = self._inflight_key(user_id=user_id, conversation_id=conversation_id)
        async with session_common.inflight_invokes_lock:
            bucket = session_common.inflight_invokes.get(key)
            if not bucket or token not in bucket:
                return False
            bucket.pop(token, None)
            if not bucket:
                session_common.inflight_invokes.pop(key, None)
            return True

    async def _list_inflight_invoke_snapshots(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
    ) -> list[session_common.InflightInvokeEntry]:
        key = self._inflight_key(user_id=user_id, conversation_id=conversation_id)
        async with session_common.inflight_invokes_lock:
            bucket = session_common.inflight_invokes.get(key) or {}
            return [self._copy_inflight_entry(entry) for entry in bucket.values()]

    async def _mark_inflight_cancel_requested(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        token: str,
        reason: str,
        pending_preempt_event: dict[str, Any] | None = None,
    ) -> session_common.InflightInvokeEntry | None:
        normalized_reason = (
            session_common.normalize_non_empty_text(reason) or "hub_user_cancel"
        )
        key = self._inflight_key(user_id=user_id, conversation_id=conversation_id)
        async with session_common.inflight_invokes_lock:
            bucket = session_common.inflight_invokes.get(key)
            current = bucket.get(token) if bucket is not None else None
            if current is None:
                return None
            current.cancel_requested = True
            current.cancel_reason = normalized_reason
            current.pending_preempt_event = self._copy_preempt_event(
                pending_preempt_event
            )
            return self._copy_inflight_entry(current)

    async def _cancel_inflight_task(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        snapshot: session_common.InflightInvokeEntry,
        reason: str,
    ) -> tuple[bool, str | None]:
        if (
            not snapshot.task_id
            or snapshot.gateway is None
            or snapshot.resolved is None
        ):
            return False, None
        normalized_reason = (
            session_common.normalize_non_empty_text(reason) or "hub_user_cancel"
        )
        cancel_result = await snapshot.gateway.cancel_task(
            resolved=snapshot.resolved,
            task_id=snapshot.task_id,
            metadata={"source": normalized_reason},
        )
        success = bool(cancel_result.get("success"))
        error_code = session_common.normalize_non_empty_text(
            str(cancel_result.get("error_code") or "")
        )
        if success or error_code in session_common.INFLIGHT_CANCEL_TERMINAL_ERROR_CODES:
            await self.unregister_inflight_invoke(
                user_id=user_id,
                conversation_id=conversation_id,
                token=snapshot.token,
            )
            return True, error_code or None
        return False, error_code or None

    @staticmethod
    def _status_error_for_cancel_error_code(error_code: str | None) -> str:
        if error_code in {"timeout", "agent_unavailable"}:
            return "upstream_unreachable"
        if error_code in {
            "upstream_http_error",
            "outbound_not_allowed",
            "client_reset",
        }:
            return "upstream_http_error"
        return "upstream_error"

    @classmethod
    def _resolve_status_error_from_cancel_errors(cls, error_codes: list[str]) -> str:
        mapped = [cls._status_error_for_cancel_error_code(code) for code in error_codes]
        if "upstream_unreachable" in mapped:
            return "upstream_unreachable"
        if "upstream_http_error" in mapped:
            return "upstream_http_error"
        return "upstream_error"

    async def preempt_inflight_invoke(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        reason: str,
    ) -> bool:
        report = await self.preempt_inflight_invoke_report(
            user_id=user_id,
            conversation_id=conversation_id,
            reason=reason,
        )
        if report.status == "failed":
            raise ValueError("invoke_interrupt_failed")
        return report.status in {"accepted", "completed"}

    async def preempt_inflight_invoke_report(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        reason: str,
        pending_event: dict[str, Any] | None = None,
    ) -> session_common.PreemptedInvokeReport:
        snapshots = await self._list_inflight_invoke_snapshots(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if not snapshots:
            return session_common.PreemptedInvokeReport(attempted=False, status="none")

        preempted = False
        pending_requested = False
        target_task_ids: list[str] = []
        completed_task_ids: list[str] = []
        failed_error_codes: list[str] = []
        pending_tokens: list[str] = []
        normalized_pending_event = self._build_pending_preempt_event(pending_event)
        for snapshot in snapshots:
            if snapshot.task_id is None:
                marked = await self._mark_inflight_cancel_requested(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    token=snapshot.token,
                    reason=reason,
                    pending_preempt_event=normalized_pending_event,
                )
                if marked is not None:
                    preempted = True
                    pending_requested = True
                    pending_tokens.append(marked.token)
                continue

            if snapshot.task_id not in target_task_ids:
                target_task_ids.append(snapshot.task_id)
            success, error_code = await self._cancel_inflight_task(
                user_id=user_id,
                conversation_id=conversation_id,
                snapshot=snapshot,
                reason=reason,
            )
            if not success:
                failed_error_codes.append(error_code or "upstream_error")
                continue
            preempted = True
            if snapshot.task_id not in completed_task_ids:
                completed_task_ids.append(snapshot.task_id)
        if preempted:
            if failed_error_codes:
                logger.warning(
                    "Partial inflight preemption failure",
                    extra={
                        "user_id": str(user_id),
                        "conversation_id": str(conversation_id),
                        "failed_error_codes": failed_error_codes,
                    },
                )
            status: Literal["accepted", "completed"] = (
                "completed" if completed_task_ids else "accepted"
            )
            return session_common.PreemptedInvokeReport(
                attempted=True,
                status=status,
                pending_requested=pending_requested,
                target_task_ids=target_task_ids,
                failed_error_codes=failed_error_codes,
                pending_tokens=pending_tokens,
            )
        if failed_error_codes:
            return session_common.PreemptedInvokeReport(
                attempted=True,
                status="failed",
                pending_requested=False,
                target_task_ids=target_task_ids,
                failed_error_codes=failed_error_codes,
                pending_tokens=[],
            )
        return session_common.PreemptedInvokeReport(attempted=False, status="none")

    async def cancel_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
    ) -> tuple[dict[str, Any], bool]:
        resolved_conversation_id = session_common.parse_conversation_id(conversation_id)
        target = await self._support.resolve_conversation_target(
            db,
            user_id=user_id,
            conversation_id=resolved_conversation_id,
        )
        if target is None:
            return (
                {
                    "conversationId": str(resolved_conversation_id),
                    "taskId": None,
                    "cancelled": False,
                    "status": "no_inflight",
                },
                False,
            )

        snapshots = await self._list_inflight_invoke_snapshots(
            user_id=user_id,
            conversation_id=resolved_conversation_id,
        )
        if not snapshots:
            return (
                {
                    "conversationId": str(resolved_conversation_id),
                    "taskId": None,
                    "cancelled": False,
                    "status": "no_inflight",
                },
                False,
            )

        accepted_task_id: str | None = None
        pending_requested = False
        terminal_task_id: str | None = None
        failed_error_codes: list[str] = []
        for snapshot in snapshots:
            if snapshot.task_id is None:
                marked = await self._mark_inflight_cancel_requested(
                    user_id=user_id,
                    conversation_id=resolved_conversation_id,
                    token=snapshot.token,
                    reason="hub_user_cancel",
                )
                if marked is not None:
                    pending_requested = True
                continue

            success, error_code = await self._cancel_inflight_task(
                user_id=user_id,
                conversation_id=resolved_conversation_id,
                snapshot=snapshot,
                reason="hub_user_cancel",
            )
            if (
                success
                and error_code
                not in session_common.INFLIGHT_CANCEL_TERMINAL_ERROR_CODES
            ):
                if accepted_task_id is None:
                    accepted_task_id = snapshot.task_id
                continue
            if (
                success
                and error_code in session_common.INFLIGHT_CANCEL_TERMINAL_ERROR_CODES
            ):
                if terminal_task_id is None:
                    terminal_task_id = snapshot.task_id
                continue

            failed_error_codes.append(error_code or "upstream_error")

        if accepted_task_id is not None:
            if failed_error_codes:
                logger.warning(
                    "Session cancel partially failed after accepted cancellation",
                    extra={
                        "user_id": str(user_id),
                        "conversation_id": str(resolved_conversation_id),
                        "failed_error_codes": failed_error_codes,
                    },
                )
            return (
                {
                    "conversationId": str(resolved_conversation_id),
                    "taskId": accepted_task_id,
                    "cancelled": True,
                    "status": "accepted",
                },
                False,
            )

        if pending_requested:
            if failed_error_codes:
                logger.warning(
                    "Session cancel partially failed while pending cancellation remains",
                    extra={
                        "user_id": str(user_id),
                        "conversation_id": str(resolved_conversation_id),
                        "failed_error_codes": failed_error_codes,
                    },
                )
            return (
                {
                    "conversationId": str(resolved_conversation_id),
                    "taskId": None,
                    "cancelled": True,
                    "status": "pending",
                },
                False,
            )

        if terminal_task_id is not None:
            if failed_error_codes:
                logger.warning(
                    "Session cancel partially failed with terminal tasks present",
                    extra={
                        "user_id": str(user_id),
                        "conversation_id": str(resolved_conversation_id),
                        "failed_error_codes": failed_error_codes,
                    },
                )
            return (
                {
                    "conversationId": str(resolved_conversation_id),
                    "taskId": terminal_task_id,
                    "cancelled": False,
                    "status": "already_terminal",
                },
                False,
            )

        if failed_error_codes:
            raise ValueError(
                self._resolve_status_error_from_cancel_errors(failed_error_codes)
            )

        return (
            {
                "conversationId": str(resolved_conversation_id),
                "taskId": None,
                "cancelled": False,
                "status": "no_inflight",
            },
            False,
        )
