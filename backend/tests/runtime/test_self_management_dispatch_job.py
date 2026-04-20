from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

import pytest

from app.db.models.self_management_dispatch_task import SelfManagementDispatchTask
from app.features.self_management_shared import dispatch_job as dispatch_job_module
from app.features.self_management_shared.dispatch_service import (
    DelegatedInvokeDispatchRequest,
    PermissionReplyContinuationDispatchRequest,
    self_management_dispatch_service,
)
from tests.support.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_dispatch_due_self_management_tasks_runs_permission_reply_continuation(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    user_id = cast(UUID, user.id)
    request = PermissionReplyContinuationDispatchRequest(
        current_user_id=user_id,
        conversation_id=str(uuid4()),
        message="Resume the approved change",
        request_id="permission-request-1",
        agent_message_id=uuid4(),
        approved_operation_ids=frozenset({"self.jobs.pause"}),
    )
    task_id = (
        await self_management_dispatch_service.enqueue_permission_reply_continuation(
            db=async_db_session,
            request=request,
        )
    )
    await async_db_session.commit()

    recorded_requests: list[PermissionReplyContinuationDispatchRequest] = []

    async def _fake_run_permission_reply_continuation(**kwargs) -> None:
        recorded_requests.append(kwargs["request"])

    monkeypatch.setattr(
        dispatch_job_module.self_management_built_in_agent_service,
        "run_permission_reply_continuation",
        _fake_run_permission_reply_continuation,
    )

    await dispatch_job_module.dispatch_due_self_management_tasks(batch_size=10)

    assert recorded_requests == [request]
    async_db_session.expire_all()
    task = await async_db_session.get(SelfManagementDispatchTask, task_id)
    assert task is not None
    assert task.status == SelfManagementDispatchTask.STATUS_COMPLETED
    assert task.last_run_error is None


async def test_dispatch_due_self_management_tasks_runs_delegated_invoke(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    user_id = cast(UUID, user.id)
    request = DelegatedInvokeDispatchRequest(
        current_user_id=user_id,
        agent_id=uuid4(),
        agent_source="personal",
        message="Ping the delegated conversation",
        conversation_id=str(uuid4()),
        target_kind="session",
        target_id=str(uuid4()),
    )
    task_id = await self_management_dispatch_service.enqueue_delegated_invoke(
        db=async_db_session,
        request=request,
    )
    await async_db_session.commit()

    recorded_requests: list[DelegatedInvokeDispatchRequest] = []

    async def _fake_run_delegated_dispatch_request(**kwargs) -> None:
        recorded_requests.append(kwargs["request"])

    monkeypatch.setattr(
        dispatch_job_module.delegated_conversation_service.self_management_delegated_conversation_service,
        "run_delegated_dispatch_request",
        _fake_run_delegated_dispatch_request,
    )

    await dispatch_job_module.dispatch_due_self_management_tasks(batch_size=10)

    assert recorded_requests == [request]
    async_db_session.expire_all()
    task = await async_db_session.get(SelfManagementDispatchTask, task_id)
    assert task is not None
    assert task.status == SelfManagementDispatchTask.STATUS_COMPLETED
    assert task.last_run_error is None
