from __future__ import annotations

import pytest

from app.features.hub_assistant_shared.actor_context import (
    HubAssistantActorType,
    build_hub_assistant_actor_context,
)
from app.features.hub_assistant_shared.tool_gateway import HubAssistantToolGateway
from app.features.schedules.hub_assistant_jobs_service import (
    hub_assistant_jobs_service,
)
from app.features.schedules.schemas import A2AScheduleTaskUpdate
from tests.support.utils import create_a2a_agent, create_schedule_task, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _build_gateway(user):
    actor = build_hub_assistant_actor_context(
        user=user,
        actor_type=HubAssistantActorType.HUMAN_API,
    )
    return HubAssistantToolGateway(actor)


async def test_hub_assistant_jobs_service_supports_first_wave_patch_shapes() -> None:
    prompt_payload = A2AScheduleTaskUpdate(prompt="new prompt")
    schedule_payload = A2AScheduleTaskUpdate(time_point={"time": "10:00"})
    mixed_payload = A2AScheduleTaskUpdate(
        prompt="new prompt",
        time_point={"time": "10:00"},
    )

    assert hub_assistant_jobs_service.supports_prompt_update(prompt_payload) is True
    assert hub_assistant_jobs_service.supports_schedule_update(prompt_payload) is False
    assert hub_assistant_jobs_service.supports_schedule_update(schedule_payload) is True
    assert hub_assistant_jobs_service.supports_prompt_update(schedule_payload) is False
    assert hub_assistant_jobs_service.supports_prompt_update(mixed_payload) is False
    assert hub_assistant_jobs_service.supports_schedule_update(mixed_payload) is False


async def test_hub_assistant_jobs_service_list_and_get_jobs(
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

    items, total = await hub_assistant_jobs_service.list_jobs(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        page=1,
        size=20,
    )
    fetched = await hub_assistant_jobs_service.get_job(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        task_id=task.id,
    )

    assert total >= 1
    assert any(item.id == task.id for item in items)
    assert fetched.id == task.id


async def test_hub_assistant_jobs_service_pause_and_resume_job(
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

    paused = await hub_assistant_jobs_service.pause_job(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        task_id=task.id,
        timezone_str=timezone_str,
    )
    assert paused.enabled is False

    resumed = await hub_assistant_jobs_service.resume_job(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        task_id=task.id,
        timezone_str=timezone_str,
    )

    assert resumed.enabled is True


async def test_hub_assistant_jobs_service_updates_prompt_and_schedule(
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

    updated_prompt = await hub_assistant_jobs_service.update_prompt(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        task_id=task.id,
        prompt="new prompt",
        timezone_str=timezone_str,
    )
    updated_schedule = await hub_assistant_jobs_service.update_schedule(
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


async def test_hub_assistant_jobs_service_create_update_and_delete_job(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    first_agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="jobs-create-a",
    )
    second_agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="jobs-create-b",
    )
    gateway = _build_gateway(user)
    timezone_str = user.timezone or "UTC"

    created = await hub_assistant_jobs_service.create_job(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        name="Created job",
        agent_id=first_agent.id,
        prompt="Run this",
        cycle_type="daily",
        time_point={"time": "09:45"},
        enabled=True,
        conversation_policy="reuse_single",
        timezone_str=timezone_str,
    )

    assert created.name == "Created job"
    assert created.conversation_policy == "reuse_single"

    updated = await hub_assistant_jobs_service.update_job(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        task_id=created.id,
        timezone_str=timezone_str,
        name="Updated job",
        agent_id=second_agent.id,
        enabled=False,
        conversation_policy="new_each_run",
    )

    assert updated.name == "Updated job"
    assert updated.agent_id == second_agent.id
    assert updated.enabled is False
    assert updated.conversation_policy == "new_each_run"

    await hub_assistant_jobs_service.delete_job(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        task_id=created.id,
    )

    items, _total = await hub_assistant_jobs_service.list_jobs(
        db=async_db_session,
        gateway=gateway,
        current_user=user,
        page=1,
        size=20,
    )
    assert all(item.id != created.id for item in items)
