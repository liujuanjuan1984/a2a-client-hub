"""FastMCP adapter for self-management operations."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any, Literal
from uuid import UUID

from fastmcp import Context, FastMCP
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    get_self_management_allowed_operations,
    verify_jwt_token_claims,
)
from app.db.session import AsyncSessionLocal
from app.features.auth.service import UserNotFoundError, get_active_user
from app.features.personal_agents.service import A2AAgentError
from app.features.schedules.common import A2AScheduleError
from app.features.self_management_shared.actor_context import (
    SelfManagementAction,
    SelfManagementAuthorizationError,
)
from app.features.self_management_shared.capability_catalog import (
    SELF_AGENTS_CHECK_HEALTH,
    SELF_AGENTS_CHECK_HEALTH_ALL,
    SELF_AGENTS_CREATE,
    SELF_AGENTS_DELETE,
    SELF_AGENTS_GET,
    SELF_AGENTS_LIST,
    SELF_AGENTS_START_SESSIONS,
    SELF_AGENTS_UPDATE_CONFIG,
    SELF_JOBS_CREATE,
    SELF_JOBS_DELETE,
    SELF_JOBS_GET,
    SELF_JOBS_LIST,
    SELF_JOBS_PAUSE,
    SELF_JOBS_RESUME,
    SELF_JOBS_UPDATE,
    SELF_JOBS_UPDATE_PROMPT,
    SELF_JOBS_UPDATE_SCHEDULE,
    SELF_SESSIONS_ARCHIVE,
    SELF_SESSIONS_GET,
    SELF_SESSIONS_LIST,
    SELF_SESSIONS_SEND_MESSAGE,
    SELF_SESSIONS_UNARCHIVE,
    SELF_SESSIONS_UPDATE,
    list_self_management_operation_ids,
)
from app.features.self_management_shared.self_management_tool_contract import (
    SelfManagementToolDefinition,
    list_self_management_tool_definitions,
)
from app.features.self_management_shared.self_management_toolkit import (
    SelfManagementToolInputError,
)
from app.features.self_management_shared.self_management_web_agent import (
    build_self_management_web_agent_runtime,
)
from app.features.self_management_shared.tool_gateway import SelfManagementSurface

logger = get_logger(__name__)

SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH = "/mcp"
SELF_MANAGEMENT_MCP_WRITE_MOUNT_PATH = "/mcp-write"
_MCP_USER_ID_STATE_KEY = "self_management_mcp_user_id"
_MCP_ALLOWED_OPERATION_IDS_STATE_KEY = "self_management_mcp_allowed_operation_ids"
SELF_MANAGEMENT_MCP_OPERATION_IDS = list_self_management_operation_ids(
    surface=SelfManagementSurface.WEB_AGENT,
    require_tool_name=True,
)
SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS = frozenset(
    list_self_management_operation_ids(
        surface=SelfManagementSurface.WEB_AGENT,
        action=SelfManagementAction.READ,
        require_tool_name=True,
    )
)
SELF_MANAGEMENT_MCP_WRITE_OPERATION_IDS = frozenset(
    list_self_management_operation_ids(
        surface=SelfManagementSurface.WEB_AGENT,
        require_tool_name=True,
    )
)


class SelfManagementMcpAuthMiddleware:
    """Require a valid hub bearer token for every MCP HTTP request."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        default_allowed_operation_ids: frozenset[str],
        require_delegated_claims: bool,
    ) -> None:
        self.app = app
        self.default_allowed_operation_ids = default_allowed_operation_ids
        self.require_delegated_claims = require_delegated_claims

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        auth_header = Headers(scope=scope).get("authorization", "")
        if not auth_header.startswith("Bearer "):
            response = JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
            )
            await response(scope, receive, send)
            return

        token = auth_header[7:].strip()
        claims = verify_jwt_token_claims(token, expected_type="access")
        if claims is None:
            response = JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )
            await response(scope, receive, send)
            return

        allowed_operation_ids = get_self_management_allowed_operations(claims)
        if self.require_delegated_claims and not allowed_operation_ids:
            response = JSONResponse(
                status_code=403,
                content={
                    "detail": "Delegated self-management operation claims are required"
                },
            )
            await response(scope, receive, send)
            return

        if allowed_operation_ids:
            allowed_operation_ids = frozenset(
                operation_id
                for operation_id in allowed_operation_ids
                if operation_id in self.default_allowed_operation_ids
            )
        else:
            allowed_operation_ids = self.default_allowed_operation_ids

        scope.setdefault("state", {})[_MCP_USER_ID_STATE_KEY] = claims.subject
        scope.setdefault("state", {})[
            _MCP_ALLOWED_OPERATION_IDS_STATE_KEY
        ] = allowed_operation_ids
        await self.app(scope, receive, send)


def _require_request_user_id(ctx: Context) -> UUID:
    request_context = ctx.request_context
    if request_context is None or request_context.request is None:
        raise RuntimeError("HTTP request context is required for MCP tools.")

    raw_user_id = getattr(
        request_context.request.state,
        _MCP_USER_ID_STATE_KEY,
        None,
    )
    if raw_user_id is None:
        raise RuntimeError("Authenticated MCP user context is missing.")

    return UUID(str(raw_user_id))


def _require_request_allowed_operation_ids(ctx: Context) -> frozenset[str]:
    request_context = ctx.request_context
    if request_context is None or request_context.request is None:
        raise RuntimeError("HTTP request context is required for MCP tools.")

    allowed_operation_ids = getattr(
        request_context.request.state,
        _MCP_ALLOWED_OPERATION_IDS_STATE_KEY,
        None,
    )
    if not isinstance(allowed_operation_ids, frozenset):
        raise RuntimeError("Authorized MCP operation context is missing.")
    return allowed_operation_ids


async def execute_self_management_mcp_operation(
    *,
    user_id: UUID,
    operation_id: str,
    arguments: Mapping[str, Any] | None = None,
    allowed_operation_ids: frozenset[str] | None = None,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    """Execute one self-management operation and return a swival-friendly envelope."""

    @asynccontextmanager
    async def _db_context() -> AsyncIterator[AsyncSession]:
        if db is not None:
            yield db
            return
        async with AsyncSessionLocal() as session:
            yield session

    async with _db_context() as session:
        try:
            if (
                allowed_operation_ids is not None
                and operation_id not in allowed_operation_ids
            ):
                raise SelfManagementAuthorizationError(
                    f"Operation `{operation_id}` is not authorized for this MCP session."
                )
            current_user = await get_active_user(session, user_id=user_id)
            runtime = build_self_management_web_agent_runtime(
                db=session,
                current_user=current_user,
            )
            result = await runtime.toolkit.execute(
                operation_id=operation_id,
                arguments=arguments,
            )
        except (
            A2AAgentError,
            A2AScheduleError,
            SelfManagementAuthorizationError,
            SelfManagementToolInputError,
            UserNotFoundError,
            ValueError,
        ) as exc:
            await session.rollback()
            return {"ok": False, "error": str(exc)}
        except Exception:
            await session.rollback()
            logger.exception(
                "Self-management MCP operation failed",
                extra={"operation_id": operation_id, "user_id": str(user_id)},
            )
            return {"ok": False, "error": "Internal server error"}

        return {"ok": True, "result": result.payload}


def build_self_management_mcp_server(
    *,
    operation_ids: frozenset[str],
    server_name: str,
) -> FastMCP:
    """Build the FastMCP server exposing first-wave self-management tools."""

    mcp = FastMCP(
        server_name,
        version=settings.app_version,
        instructions=(
            "Use these tools to manage the authenticated user's exposed "
            "self-management resources inside a2a-client-hub. All operations "
            "are scoped to the current user."
        ),
    )

    def _exposed(operation_id: str) -> bool:
        return operation_id in operation_ids

    if _exposed(SELF_AGENTS_LIST.operation_id):

        @mcp.tool(
            name=SELF_AGENTS_LIST.tool_name,
            description=SELF_AGENTS_LIST.description,
        )
        async def self_agents_list(
            page: int = 1,
            size: int = 20,
            health_bucket: str = "all",
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_AGENTS_LIST.operation_id,
                arguments={
                    "page": page,
                    "size": size,
                    "health_bucket": health_bucket,
                },
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_AGENTS_GET.operation_id):

        @mcp.tool(
            name=SELF_AGENTS_GET.tool_name,
            description=SELF_AGENTS_GET.description,
        )
        async def self_agents_get(
            agent_id: str,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_AGENTS_GET.operation_id,
                arguments={"agent_id": agent_id},
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_AGENTS_CHECK_HEALTH.operation_id):

        @mcp.tool(
            name=SELF_AGENTS_CHECK_HEALTH.tool_name,
            description=SELF_AGENTS_CHECK_HEALTH.description,
        )
        async def self_agents_check_health(
            agent_id: str,
            force: bool = True,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_AGENTS_CHECK_HEALTH.operation_id,
                arguments={"agent_id": agent_id, "force": force},
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_AGENTS_CHECK_HEALTH_ALL.operation_id):

        @mcp.tool(
            name=SELF_AGENTS_CHECK_HEALTH_ALL.tool_name,
            description=SELF_AGENTS_CHECK_HEALTH_ALL.description,
        )
        async def self_agents_check_health_all(
            force: bool = False,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_AGENTS_CHECK_HEALTH_ALL.operation_id,
                arguments={"force": force},
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_AGENTS_CREATE.operation_id):

        @mcp.tool(
            name=SELF_AGENTS_CREATE.tool_name,
            description=SELF_AGENTS_CREATE.description,
        )
        async def self_agents_create(
            name: str,
            card_url: str,
            auth_type: str,
            auth_header: str | None = None,
            auth_scheme: str | None = None,
            enabled: bool = True,
            tags: list[str] | None = None,
            extra_headers: dict[str, str] | None = None,
            invoke_metadata_defaults: dict[str, str] | None = None,
            token: str | None = None,
            basic_username: str | None = None,
            basic_password: str | None = None,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_AGENTS_CREATE.operation_id,
                arguments={
                    "name": name,
                    "card_url": card_url,
                    "auth_type": auth_type,
                    "auth_header": auth_header,
                    "auth_scheme": auth_scheme,
                    "enabled": enabled,
                    "tags": tags,
                    "extra_headers": extra_headers,
                    "invoke_metadata_defaults": invoke_metadata_defaults,
                    "token": token,
                    "basic_username": basic_username,
                    "basic_password": basic_password,
                },
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_AGENTS_UPDATE_CONFIG.operation_id):

        @mcp.tool(
            name=SELF_AGENTS_UPDATE_CONFIG.tool_name,
            description=SELF_AGENTS_UPDATE_CONFIG.description,
        )
        async def self_agents_update_config(
            agent_id: str,
            name: str | None = None,
            card_url: str | None = None,
            auth_type: str | None = None,
            auth_header: str | None = None,
            auth_scheme: str | None = None,
            enabled: bool | None = None,
            tags: list[str] | None = None,
            extra_headers: dict[str, str] | None = None,
            invoke_metadata_defaults: dict[str, str] | None = None,
            token: str | None = None,
            basic_username: str | None = None,
            basic_password: str | None = None,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_AGENTS_UPDATE_CONFIG.operation_id,
                arguments={
                    "agent_id": agent_id,
                    "name": name,
                    "card_url": card_url,
                    "auth_type": auth_type,
                    "auth_header": auth_header,
                    "auth_scheme": auth_scheme,
                    "enabled": enabled,
                    "tags": tags,
                    "extra_headers": extra_headers,
                    "invoke_metadata_defaults": invoke_metadata_defaults,
                    "token": token,
                    "basic_username": basic_username,
                    "basic_password": basic_password,
                },
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_AGENTS_DELETE.operation_id):

        @mcp.tool(
            name=SELF_AGENTS_DELETE.tool_name,
            description=SELF_AGENTS_DELETE.description,
        )
        async def self_agents_delete(
            agent_id: str,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_AGENTS_DELETE.operation_id,
                arguments={"agent_id": agent_id},
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_AGENTS_START_SESSIONS.operation_id):

        @mcp.tool(
            name=SELF_AGENTS_START_SESSIONS.tool_name,
            description=SELF_AGENTS_START_SESSIONS.description,
        )
        async def self_agents_start_sessions(
            agent_ids: list[str],
            message: str,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_AGENTS_START_SESSIONS.operation_id,
                arguments={"agent_ids": agent_ids, "message": message},
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_JOBS_LIST.operation_id):

        @mcp.tool(
            name=SELF_JOBS_LIST.tool_name,
            description=SELF_JOBS_LIST.description,
        )
        async def self_jobs_list(
            page: int = 1,
            size: int = 20,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_JOBS_LIST.operation_id,
                arguments={"page": page, "size": size},
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_JOBS_CREATE.operation_id):

        @mcp.tool(
            name=SELF_JOBS_CREATE.tool_name,
            description=SELF_JOBS_CREATE.description,
        )
        async def self_jobs_create(
            name: str,
            agent_id: str,
            prompt: str,
            cycle_type: str,
            time_point: dict[str, object],
            enabled: bool = True,
            conversation_policy: Literal["new_each_run", "reuse_single"] = (
                "new_each_run"
            ),
            schedule_timezone: str | None = None,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_JOBS_CREATE.operation_id,
                arguments={
                    "name": name,
                    "agent_id": agent_id,
                    "prompt": prompt,
                    "cycle_type": cycle_type,
                    "time_point": time_point,
                    "enabled": enabled,
                    "conversation_policy": conversation_policy,
                    "schedule_timezone": schedule_timezone,
                },
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_JOBS_GET.operation_id):

        @mcp.tool(
            name=SELF_JOBS_GET.tool_name,
            description=SELF_JOBS_GET.description,
        )
        async def self_jobs_get(
            task_id: str,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_JOBS_GET.operation_id,
                arguments={"task_id": task_id},
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_JOBS_PAUSE.operation_id):

        @mcp.tool(
            name=SELF_JOBS_PAUSE.tool_name,
            description=SELF_JOBS_PAUSE.description,
        )
        async def self_jobs_pause(
            task_id: str,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_JOBS_PAUSE.operation_id,
                arguments={"task_id": task_id},
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_JOBS_RESUME.operation_id):

        @mcp.tool(
            name=SELF_JOBS_RESUME.tool_name,
            description=SELF_JOBS_RESUME.description,
        )
        async def self_jobs_resume(
            task_id: str,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_JOBS_RESUME.operation_id,
                arguments={"task_id": task_id},
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_JOBS_UPDATE.operation_id):

        @mcp.tool(
            name=SELF_JOBS_UPDATE.tool_name,
            description=SELF_JOBS_UPDATE.description,
        )
        async def self_jobs_update(
            task_id: str,
            name: str | None = None,
            agent_id: str | None = None,
            prompt: str | None = None,
            cycle_type: str | None = None,
            time_point: dict[str, object] | None = None,
            enabled: bool | None = None,
            conversation_policy: Literal["new_each_run", "reuse_single"] | None = None,
            schedule_timezone: str | None = None,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_JOBS_UPDATE.operation_id,
                arguments={
                    "task_id": task_id,
                    "name": name,
                    "agent_id": agent_id,
                    "prompt": prompt,
                    "cycle_type": cycle_type,
                    "time_point": time_point,
                    "enabled": enabled,
                    "conversation_policy": conversation_policy,
                    "schedule_timezone": schedule_timezone,
                },
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_JOBS_UPDATE_PROMPT.operation_id):

        @mcp.tool(
            name=SELF_JOBS_UPDATE_PROMPT.tool_name,
            description=SELF_JOBS_UPDATE_PROMPT.description,
        )
        async def self_jobs_update_prompt(
            task_id: str,
            prompt: str,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_JOBS_UPDATE_PROMPT.operation_id,
                arguments={"task_id": task_id, "prompt": prompt},
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_JOBS_UPDATE_SCHEDULE.operation_id):

        @mcp.tool(
            name=SELF_JOBS_UPDATE_SCHEDULE.tool_name,
            description=SELF_JOBS_UPDATE_SCHEDULE.description,
        )
        async def self_jobs_update_schedule(
            task_id: str,
            cycle_type: str | None = None,
            time_point: dict[str, object] | None = None,
            schedule_timezone: str | None = None,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_JOBS_UPDATE_SCHEDULE.operation_id,
                arguments={
                    "task_id": task_id,
                    "cycle_type": cycle_type,
                    "time_point": time_point,
                    "schedule_timezone": schedule_timezone,
                },
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_JOBS_DELETE.operation_id):

        @mcp.tool(
            name=SELF_JOBS_DELETE.tool_name,
            description=SELF_JOBS_DELETE.description,
        )
        async def self_jobs_delete(
            task_id: str,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_JOBS_DELETE.operation_id,
                arguments={"task_id": task_id},
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_SESSIONS_LIST.operation_id):

        @mcp.tool(
            name=SELF_SESSIONS_LIST.tool_name,
            description=SELF_SESSIONS_LIST.description,
        )
        async def self_sessions_list(
            page: int = 1,
            size: int = 20,
            source: str | None = None,
            status: str = "active",
            agent_id: str | None = None,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_SESSIONS_LIST.operation_id,
                arguments={
                    "page": page,
                    "size": size,
                    "source": source,
                    "status": status,
                    "agent_id": agent_id,
                },
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_SESSIONS_GET.operation_id):

        @mcp.tool(
            name=SELF_SESSIONS_GET.tool_name,
            description=SELF_SESSIONS_GET.description,
        )
        async def self_sessions_get(
            conversation_id: str,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_SESSIONS_GET.operation_id,
                arguments={"conversation_id": conversation_id},
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_SESSIONS_UPDATE.operation_id):

        @mcp.tool(
            name=SELF_SESSIONS_UPDATE.tool_name,
            description=SELF_SESSIONS_UPDATE.description,
        )
        async def self_sessions_update(
            conversation_id: str,
            title: str,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_SESSIONS_UPDATE.operation_id,
                arguments={"conversation_id": conversation_id, "title": title},
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_SESSIONS_ARCHIVE.operation_id):

        @mcp.tool(
            name=SELF_SESSIONS_ARCHIVE.tool_name,
            description=SELF_SESSIONS_ARCHIVE.description,
        )
        async def self_sessions_archive(
            conversation_id: str,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_SESSIONS_ARCHIVE.operation_id,
                arguments={"conversation_id": conversation_id},
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_SESSIONS_UNARCHIVE.operation_id):

        @mcp.tool(
            name=SELF_SESSIONS_UNARCHIVE.tool_name,
            description=SELF_SESSIONS_UNARCHIVE.description,
        )
        async def self_sessions_unarchive(
            conversation_id: str,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_SESSIONS_UNARCHIVE.operation_id,
                arguments={"conversation_id": conversation_id},
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    if _exposed(SELF_SESSIONS_SEND_MESSAGE.operation_id):

        @mcp.tool(
            name=SELF_SESSIONS_SEND_MESSAGE.tool_name,
            description=SELF_SESSIONS_SEND_MESSAGE.description,
        )
        async def self_sessions_send_message(
            conversation_ids: list[str],
            message: str,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            if ctx is None:
                raise RuntimeError("FastMCP context is required.")
            return await execute_self_management_mcp_operation(
                user_id=_require_request_user_id(ctx),
                operation_id=SELF_SESSIONS_SEND_MESSAGE.operation_id,
                arguments={
                    "conversation_ids": conversation_ids,
                    "message": message,
                },
                allowed_operation_ids=_require_request_allowed_operation_ids(ctx),
            )

    return mcp


self_management_mcp_server = build_self_management_mcp_server(
    operation_ids=SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS,
    server_name="a2a-client-hub self-management read-only",
)
self_management_write_mcp_server = build_self_management_mcp_server(
    operation_ids=SELF_MANAGEMENT_MCP_WRITE_OPERATION_IDS,
    server_name="a2a-client-hub self-management write-enabled",
)


def build_self_management_mcp_http_app(
    *,
    operation_ids: frozenset[str],
) -> Any:
    """Build the mounted FastMCP HTTP app for swival consumption."""
    server = (
        self_management_write_mcp_server
        if operation_ids == SELF_MANAGEMENT_MCP_WRITE_OPERATION_IDS
        else self_management_mcp_server
    )
    return server.http_app(
        path="/",
        transport="sse",
        middleware=[
            Middleware(
                SelfManagementMcpAuthMiddleware,
                default_allowed_operation_ids=operation_ids,
                require_delegated_claims=True,
            )
        ],
    )


def list_self_management_mcp_tool_definitions() -> (
    tuple[SelfManagementToolDefinition, ...]
):
    """List tool definitions currently exposed by the FastMCP adapter."""

    return tuple(
        definition
        for definition in list_self_management_tool_definitions(
            surface=SelfManagementSurface.WEB_AGENT,
        )
        if definition.operation_id in SELF_MANAGEMENT_MCP_WRITE_OPERATION_IDS
    )


__all__ = [
    "SELF_MANAGEMENT_MCP_OPERATION_IDS",
    "SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH",
    "SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS",
    "SELF_MANAGEMENT_MCP_WRITE_MOUNT_PATH",
    "SELF_MANAGEMENT_MCP_WRITE_OPERATION_IDS",
    "SelfManagementMcpAuthMiddleware",
    "build_self_management_mcp_http_app",
    "build_self_management_mcp_server",
    "execute_self_management_mcp_operation",
    "list_self_management_mcp_tool_definitions",
    "self_management_mcp_server",
]
