from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.features.agents_shared.self_management_mcp import (
    SELF_MANAGEMENT_MCP_MOUNT_PATH,
    build_self_management_mcp_http_app,
    execute_self_management_mcp_operation,
    self_management_mcp_server,
)
from app.main import combine_lifespans
from tests.support.utils import create_a2a_agent, create_schedule_task, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    yield


async def test_self_management_mcp_server_lists_first_wave_job_tools() -> None:
    tools = await self_management_mcp_server.get_tools()
    tool_names = {tool.name for tool in tools.values()}

    assert "self.jobs.list" in tool_names
    assert "self.jobs.get" in tool_names
    assert "self.jobs.pause" in tool_names


async def test_execute_self_management_mcp_operation_returns_swival_envelope(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="mcp-jobs",
    )
    task = await create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        prompt="mcp prompt",
    )

    list_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.jobs.list",
        arguments={"page": 1, "size": 20},
        db=async_db_session,
    )
    get_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.jobs.get",
        arguments={"task_id": str(task.id)},
        db=async_db_session,
    )

    assert list_result["ok"] is True
    assert any(item["id"] == str(task.id) for item in list_result["result"]["items"])
    assert get_result["ok"] is True
    assert get_result["result"]["job"]["prompt"] == "mcp prompt"


async def test_self_management_mcp_http_app_requires_bearer_auth(
    async_db_session,
) -> None:
    await create_user(async_db_session)
    mcp_app = build_self_management_mcp_http_app()
    app = FastAPI(lifespan=combine_lifespans(_app_lifespan, mcp_app.lifespan))
    app.mount(SELF_MANAGEMENT_MCP_MOUNT_PATH, mcp_app)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        missing = await client.get(f"{SELF_MANAGEMENT_MCP_MOUNT_PATH}/")
        invalid = await client.get(
            f"{SELF_MANAGEMENT_MCP_MOUNT_PATH}/",
            headers={"Authorization": "Bearer invalid-token"},
        )

    assert missing.status_code == 401
    assert missing.json()["detail"] == "Missing or invalid Authorization header"
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "Invalid or expired token"
