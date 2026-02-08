from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_audit_log import AgentAuditLog
from app.db.models.user import User
from app.services.agent_audit_logger import MAX_SNAPSHOT_BYTES, agent_audit_logger

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


async def _create_user(db: AsyncSession) -> User:
    user = User(email="agent-audit@example.com", name="Agent Audit", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def test_agent_audit_logger_persists_entry(async_db_session) -> None:
    user = await _create_user(async_db_session)

    await agent_audit_logger.bulk_log_tool_runs(
        async_db_session,
        [
            {
                "trigger_user_id": user.id,
                "agent_name": "test-agent",
                "tool_name": "tasks_update",
                "tool_call_id": "call_123",
                "session_id": None,
                "message_id": uuid4(),
                "status": "finished",
                "duration_ms": 1200,
                "operation": "tasks.update",
                "target_entities": {"type": "task", "ids": ["t1", "t2"]},
                "before_snapshot": {"t1": {"status": "todo"}},
                "after_snapshot": {"t1": {"status": "done"}},
                "error": None,
                "extra": {"arguments": {"task_id": "t1"}},
                "run_id": uuid4(),
            }
        ],
    )

    stored = (
        await async_db_session.execute(
            select(AgentAuditLog).where(AgentAuditLog.tool_call_id == "call_123")
        )
    ).scalar_one()
    assert stored.tool_name == "tasks_update"
    assert stored.operation == "tasks.update"
    assert stored.target_entities["ids"] == ["t1", "t2"]
    assert stored.before_snapshot["t1"]["status"] == "todo"
    assert stored.after_snapshot["t1"]["status"] == "done"


async def test_agent_audit_logger_truncates_large_payload(async_db_session) -> None:
    user = await _create_user(async_db_session)
    large_blob = {"data": "x" * (MAX_SNAPSHOT_BYTES + 10)}

    await agent_audit_logger.bulk_log_tool_runs(
        async_db_session,
        [
            {
                "trigger_user_id": user.id,
                "agent_name": "test-agent",
                "tool_name": "notes_write",
                "tool_call_id": "truncate_case",
                "session_id": None,
                "message_id": None,
                "status": "failed",
                "duration_ms": None,
                "operation": None,
                "target_entities": None,
                "before_snapshot": large_blob,
                "after_snapshot": None,
                "error": "boom",
                "extra": None,
                "run_id": uuid4(),
            }
        ],
    )

    stored = (
        await async_db_session.execute(
            select(AgentAuditLog).where(AgentAuditLog.tool_call_id == "truncate_case")
        )
    ).scalar_one()
    assert stored.before_snapshot["__truncated__"] is True
    assert stored.before_snapshot["original_size"] > MAX_SNAPSHOT_BYTES


async def test_agent_audit_logger_bulk_insert(async_db_session) -> None:
    user = await _create_user(async_db_session)
    payloads = [
        {
            "trigger_user_id": user.id,
            "agent_name": "bulk-agent",
            "tool_name": "notes_write",
            "tool_call_id": "bulk-1",
            "session_id": None,
            "message_id": None,
            "status": "finished",
            "duration_ms": 100,
            "operation": "notes.create",
            "target_entities": {"type": "note", "ids": ["n1"]},
            "before_snapshot": None,
            "after_snapshot": {"note": {"id": "n1"}},
            "error": None,
            "extra": {"arguments": {"title": "demo"}},
            "run_id": uuid4(),
        },
        {
            "trigger_user_id": user.id,
            "agent_name": "bulk-agent",
            "tool_name": "notes_write",
            "tool_call_id": "bulk-2",
            "session_id": None,
            "message_id": None,
            "status": "failed",
            "duration_ms": None,
            "operation": "notes.update",
            "target_entities": {"type": "note", "ids": ["n2"]},
            "before_snapshot": {"note": {"id": "n2"}},
            "after_snapshot": None,
            "error": "boom",
            "extra": {"arguments": {"note_id": "n2"}},
            "run_id": uuid4(),
        },
    ]

    await agent_audit_logger.bulk_log_tool_runs(async_db_session, payloads)

    total = (
        await async_db_session.execute(select(func.count()).select_from(AgentAuditLog))
    ).scalar_one()
    assert total == 2
