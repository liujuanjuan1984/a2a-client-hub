from __future__ import annotations

import pytest

from app.features.schedules.schemas import A2AScheduleTaskUpdate
from app.features.schedules.self_management_jobs_service import (
    self_management_jobs_service,
)
from app.features.self_management_shared.actor_context import (
    SelfManagementActorType,
    build_self_management_actor_context,
)
from app.features.self_management_shared.tool_gateway import SelfManagementToolGateway
from tests.support.utils import create_a2a_agent, create_schedule_task, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _build_gateway(user):
    actor = build_self_management_actor_context(
        user=user,
        actor_type=SelfManagementActorType.HUMAN_API,
    )
    return SelfManagementToolGateway(actor)


async def test_self_management_jobs_service_supports_first_wave_patch_shapes() -> None:
    prompt_payload = A2AScheduleTaskUpdate(prompt="new prompt")
    schedule_payload = A2AScheduleTaskUpdate(time_point={"time": "10:00"})
    mixed_payload = A2AScheduleTaskUpdate(
        prompt="new prompt",
        time_point={"time": "10:00"},
    )

    assert self_management_jobs_service.supports_prompt_update(prompt_payload) is True
    assert (
        self_management_jobs_service.supports_schedule_update(prompt_payload) is False
    )
    assert (
        self_management_jobs_service.supports_schedule_update(schedule_payload) is True
    )
    assert (
        self_management_jobs_service.supports_prompt_update(schedule_payload) is False
    )
    assert self_management_jobs_service.supports_prompt_update(mixed_payload) is False
    assert self_management_jobs_service.supports_schedule_update(mixed_payload) is False


async def test_self_management_jobs_service_list_and_get_jobs(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session, user_id=user.id, suffix="jobs-list"
    )
    task = await create_schedule_task(
        async_db_session, user_id=user.id, agent_id=agent.id
    )
    gateway = _build_gateway(user)

    items, total = await self_management_jobs_service.list_jobs(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        page=1,
        size=20,
    )
    fetched = await self_management_jobs_service.get_job(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        task_id=task.id,
    )

    assert total >= 1
    assert any(item.id == task.id for item in items)
    assert fetched.id == task.id


async def test_self_management_jobs_service_pause_and_resume_job(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session, user_id=user.id, suffix="jobs-toggle"
    )
    task = await create_schedule_task(
        async_db_session, user_id=user.id, agent_id=agent.id
    )
    gateway = _build_gateway(user)
    timezone_str = user.timezone or "UTC"

    paused = await self_management_jobs_service.pause_job(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        task_id=task.id,
        timezone_str=timezone_str,
    )
    assert paused.enabled is False

    resumed = await self_management_jobs_service.resume_job(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        task_id=task.id,
        timezone_str=timezone_str,
    )

    assert resumed.enabled is True


async def test_self_management_jobs_service_updates_prompt_and_schedule(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session, user_id=user.id, suffix="jobs-update"
    )
    task = await create_schedule_task(
        async_db_session, user_id=user.id, agent_id=agent.id
    )
    gateway = _build_gateway(user)
    timezone_str = user.timezone or "UTC"

    updated_prompt = await self_management_jobs_service.update_prompt(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        task_id=task.id,
        prompt="new prompt",
        timezone_str=timezone_str,
    )
    updated_schedule = await self_management_jobs_service.update_schedule(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        task_id=task.id,
        cycle_type="daily",
        time_point={"time": "10:30"},
        timezone_str=timezone_str,
    )

    assert updated_prompt.prompt == "new prompt"
    assert updated_schedule.time_point["time"] == "10:30"
