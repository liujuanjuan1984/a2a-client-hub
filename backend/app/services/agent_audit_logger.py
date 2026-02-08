"""Service helpers for persisting agent audit log entries."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.agent_audit_log import AgentAuditLog
from app.utils.json_encoder import json_dumps

logger = get_logger(__name__)

MAX_SNAPSHOT_BYTES = 64 * 1024  # 64 KiB safety guard


def _normalise_json(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if payload is None:
        return None
    if not payload:
        return None

    try:
        encoded = json_dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        logger.debug(
            "agent_audit_logger: payload not JSON serializable; storing raw repr"
        )
        return {"__non_serializable__": str(payload)}

    size = len(encoded.encode("utf-8"))
    if size <= MAX_SNAPSHOT_BYTES:
        return payload

    logger.warning(
        "agent_audit_logger: payload truncated to protect storage",
        extra={"payload_size": size},
    )
    return {
        "__truncated__": True,
        "original_size": size,
    }


class AgentAuditLogger:
    """Lightweight helper to record agent tool executions."""

    def _build_entry(
        self,
        *,
        trigger_user_id: UUID,
        agent_name: str,
        tool_name: str,
        tool_call_id: Optional[str],
        session_id: Optional[UUID],
        message_id: Optional[UUID],
        status: str,
        duration_ms: Optional[int],
        operation: Optional[str] = None,
        target_entities: Optional[Dict[str, Any]] = None,
        before_snapshot: Optional[Dict[str, Any]] = None,
        after_snapshot: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
        run_id: Optional[UUID] = None,
    ) -> AgentAuditLog:
        return AgentAuditLog(
            run_id=run_id or uuid4(),
            trigger_user_id=trigger_user_id,
            session_id=session_id,
            message_id=message_id,
            agent_name=agent_name,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            operation=operation or tool_name,
            status=status,
            duration_ms=duration_ms,
            error=error,
            target_entities=_normalise_json(target_entities),
            before_snapshot=_normalise_json(before_snapshot),
            after_snapshot=_normalise_json(after_snapshot),
            extra=_normalise_json(extra),
        )

    async def bulk_log_tool_runs(
        self,
        db: AsyncSession,
        entries: Iterable[Dict[str, Any]],
    ) -> List[AgentAuditLog]:
        batch = [self._build_entry(**payload) for payload in entries]
        if not batch:
            return []
        for entry in batch:
            db.add(entry)
        await db.flush()
        return batch


agent_audit_logger = AgentAuditLogger()

__all__ = ["AgentAuditLogger", "agent_audit_logger"]
