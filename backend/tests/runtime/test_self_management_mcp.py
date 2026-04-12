from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.core.security import create_self_management_access_token
from app.features.self_management_shared.self_management_mcp import (
    _MCP_ALLOWED_OPERATION_IDS_STATE_KEY,
    _MCP_USER_ID_STATE_KEY,
    SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH,
    SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS,
    SelfManagementMcpAuthMiddleware,
    build_self_management_mcp_http_app,
    execute_self_management_mcp_operation,
    self_management_mcp_server,
    self_management_write_mcp_server,
)
from app.main import combine_lifespans
from tests.support.utils import (
    create_a2a_agent,
    create_conversation_thread,
    create_schedule_task,
    create_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    yield


async def test_self_management_mcp_server_lists_first_wave_tools() -> None:
    tools = await self_management_mcp_server.list_tools()
    tool_names = {tool.name for tool in tools}

    assert "self.agents.list" in tool_names
    assert "self.agents.get" in tool_names
    assert "self.jobs.list" in tool_names
    assert "self.jobs.get" in tool_names
    assert "self.sessions.list" in tool_names
    assert "self.sessions.get" in tool_names


async def test_self_management_write_mcp_server_lists_write_tools() -> None:
    tools = await self_management_write_mcp_server.list_tools()
    tool_names = {tool.name for tool in tools}

    assert "self.agents.update_config" in tool_names
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


async def test_execute_self_management_mcp_operation_supports_sessions(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="MCP Session",
    )

    list_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.sessions.list",
        arguments={"page": 1, "size": 20},
        db=async_db_session,
    )
    get_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.sessions.get",
        arguments={"conversation_id": str(thread.id)},
        db=async_db_session,
    )

    assert list_result["ok"] is True
    assert any(
        item["conversation_id"] == str(thread.id)
        for item in list_result["result"]["items"]
    )
    assert get_result["ok"] is True
    assert get_result["result"]["session"]["conversation_id"] == str(thread.id)
    assert get_result["result"]["session"]["title"] == "MCP Session"


async def test_execute_self_management_mcp_operation_supports_agents(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="mcp-agent",
        tags=["before"],
    )

    list_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.agents.list",
        arguments={"page": 1, "size": 20, "health_bucket": "all"},
        db=async_db_session,
    )
    get_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.agents.get",
        arguments={"agent_id": str(agent.id)},
        db=async_db_session,
    )
    update_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.agents.update_config",
        arguments={
            "agent_id": str(agent.id),
            "name": "MCP Updated Agent",
            "enabled": False,
            "tags": ["after"],
            "extra_headers": {"X-Test": "1"},
            "invoke_metadata_defaults": {"mode": "safe"},
        },
        db=async_db_session,
    )

    assert list_result["ok"] is True
    assert any(item["id"] == str(agent.id) for item in list_result["result"]["items"])
    assert get_result["ok"] is True
    assert get_result["result"]["agent"]["id"] == str(agent.id)
    assert update_result["ok"] is True
    assert update_result["result"]["agent"]["id"] == str(agent.id)
    assert update_result["result"]["agent"]["name"] == "MCP Updated Agent"
    assert update_result["result"]["agent"]["enabled"] is False
    assert update_result["result"]["agent"]["tags"] == ["after"]


async def test_self_management_mcp_http_app_requires_bearer_auth(
    async_db_session,
) -> None:
    await create_user(async_db_session)
    mcp_app = build_self_management_mcp_http_app(
        operation_ids=SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS
    )
    app = FastAPI(lifespan=combine_lifespans(_app_lifespan, mcp_app.lifespan))
    app.mount(SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH, mcp_app)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        missing = await client.get(f"{SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH}/")
        invalid = await client.get(
            f"{SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH}/",
            headers={"Authorization": "Bearer invalid-token"},
        )

    assert missing.status_code == 401
    assert missing.json()["detail"] == "Missing or invalid Authorization header"
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "Invalid or expired token"


async def test_self_management_mcp_auth_middleware_accepts_valid_bearer_auth(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    token = create_self_management_access_token(
        user.id,
        allowed_operations=sorted(SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS),
        delegated_by="test",
    )
    app = FastAPI()
    app.add_middleware(
        SelfManagementMcpAuthMiddleware,
        default_allowed_operation_ids=SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS,
        require_delegated_claims=True,
    )

    @app.get("/")
    async def read_root(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "user_id": str(
                    getattr(request.state, _MCP_USER_ID_STATE_KEY, ""),
                ),
                "allowed_operation_ids": sorted(
                    getattr(
                        request.state, _MCP_ALLOWED_OPERATION_IDS_STATE_KEY, frozenset()
                    )
                ),
            }
        )

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["user_id"] == str(user.id)
    assert response.json()["allowed_operation_ids"] == sorted(
        SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS
    )


async def test_execute_self_management_mcp_operation_rejects_unapproved_operation(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="mcp-agent-denied",
    )

    result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.agents.update_config",
        arguments={"agent_id": str(agent.id), "name": "Denied"},
        allowed_operation_ids=SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS,
        db=async_db_session,
    )

    assert result == {
        "ok": False,
        "error": (
            "Operation `self.agents.update_config` is not authorized for this MCP session."
        ),
    }
