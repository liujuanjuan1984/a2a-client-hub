from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

import pytest

from app.db.models.self_management_agent_task import SelfManagementAgentTask
from app.features.self_management_shared import task_job as task_job_module
from app.features.self_management_shared.task_service import (
    DelegatedInvokeTaskRequest,
    PermissionReplyContinuationTaskRequest,
    self_management_agent_task_service,
)
from tests.support.utils import create_conversation_thread, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_self_management_agent_task_job_runs_permission_reply_continuation(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    user_id = cast(UUID, user.id)
    built_in_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Built-in Conversation",
    )
    request = PermissionReplyContinuationTaskRequest(
        current_user_id=user_id,
        built_in_conversation_id=str(built_in_thread.id),
        message="Resume the approved change",
        request_id="permission-request-1",
        agent_message_id=uuid4(),
        approved_operation_ids=frozenset({"self.jobs.pause"}),
    )
    task_id = (
        await self_management_agent_task_service.enqueue_permission_reply_continuation(
            db=async_db_session,
            request=request,
        )
    )
    await async_db_session.commit()

    recorded_requests: list[PermissionReplyContinuationTaskRequest] = []

    async def _fake_run_permission_reply_continuation(**kwargs) -> None:
        recorded_requests.append(kwargs["request"])

    monkeypatch.setattr(
        task_job_module.self_management_built_in_agent_service,
        "run_permission_reply_continuation",
        _fake_run_permission_reply_continuation,
    )

    await task_job_module.dispatch_due_self_management_agent_tasks(batch_size=10)

    assert recorded_requests == [request]
    async_db_session.expire_all()
    task = await async_db_session.get(SelfManagementAgentTask, task_id)
    assert task is not None
    assert task.status == SelfManagementAgentTask.STATUS_COMPLETED
    assert task.last_run_error is None


async def test_self_management_agent_task_job_runs_delegated_invoke(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    user_id = cast(UUID, user.id)
    built_in_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Built-in Conversation",
    )
    request = DelegatedInvokeTaskRequest(
        current_user_id=user_id,
        built_in_conversation_id=str(built_in_thread.id),
        agent_id=uuid4(),
        agent_source="personal",
        message="Ping the delegated conversation",
        conversation_id=str(uuid4()),
        target_kind="session",
        target_id=str(uuid4()),
    )
    task_id = await self_management_agent_task_service.enqueue_delegated_invoke(
        db=async_db_session,
        request=request,
    )
    await async_db_session.commit()

    recorded_requests: list[DelegatedInvokeTaskRequest] = []

    async def _fake_run_delegated_dispatch_request(**kwargs) -> None:
        recorded_requests.append(kwargs["request"])

    monkeypatch.setattr(
        task_job_module.delegated_conversation_service.self_management_delegated_conversation_service,
        "run_delegated_dispatch_request",
        _fake_run_delegated_dispatch_request,
    )

    await task_job_module.dispatch_due_self_management_agent_tasks(batch_size=10)

    assert recorded_requests == [request]
    async_db_session.expire_all()
    task = await async_db_session.get(SelfManagementAgentTask, task_id)
    assert task is not None
    assert task.status == SelfManagementAgentTask.STATUS_COMPLETED
    assert task.last_run_error is None
