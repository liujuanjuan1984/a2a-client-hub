"""FastMCP adapter for self-management operations."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any
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
from app.features.agents_shared.actor_context import SelfManagementAuthorizationError
from app.features.agents_shared.capability_catalog import (
    SELF_AGENTS_GET,
    SELF_AGENTS_LIST,
    SELF_AGENTS_UPDATE_CONFIG,
    SELF_JOBS_GET,
    SELF_JOBS_LIST,
    SELF_JOBS_PAUSE,
    SELF_SESSIONS_GET,
    SELF_SESSIONS_LIST,
)
from app.features.agents_shared.self_management_tool_contract import (
    SelfManagementToolDefinition,
    list_self_management_tool_definitions,
)
from app.features.agents_shared.self_management_toolkit import (
    SelfManagementToolInputError,
)
from app.features.agents_shared.self_management_web_agent import (
    build_self_management_web_agent_runtime,
)
from app.features.agents_shared.tool_gateway import SelfManagementSurface
from app.features.auth.service import UserNotFoundError, get_active_user

logger = get_logger(__name__)

SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH = "/mcp"
SELF_MANAGEMENT_MCP_WRITE_MOUNT_PATH = "/mcp-write"
_MCP_USER_ID_STATE_KEY = "self_management_mcp_user_id"
_MCP_ALLOWED_OPERATION_IDS_STATE_KEY = "self_management_mcp_allowed_operation_ids"
SELF_MANAGEMENT_MCP_OPERATION_IDS = (
    SELF_AGENTS_LIST.operation_id,
    SELF_AGENTS_GET.operation_id,
    SELF_AGENTS_UPDATE_CONFIG.operation_id,
    SELF_JOBS_LIST.operation_id,
    SELF_JOBS_GET.operation_id,
    SELF_JOBS_PAUSE.operation_id,
    SELF_SESSIONS_LIST.operation_id,
    SELF_SESSIONS_GET.operation_id,
)
SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS = frozenset(
    {
        SELF_AGENTS_LIST.operation_id,
        SELF_AGENTS_GET.operation_id,
        SELF_JOBS_LIST.operation_id,
        SELF_JOBS_GET.operation_id,
        SELF_SESSIONS_LIST.operation_id,
        SELF_SESSIONS_GET.operation_id,
    }
)
SELF_MANAGEMENT_MCP_WRITE_OPERATION_IDS = frozenset(SELF_MANAGEMENT_MCP_OPERATION_IDS)


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

    if _exposed(SELF_AGENTS_UPDATE_CONFIG.operation_id):

        @mcp.tool(
            name=SELF_AGENTS_UPDATE_CONFIG.tool_name,
            description=SELF_AGENTS_UPDATE_CONFIG.description,
        )
        async def self_agents_update_config(
            agent_id: str,
            name: str | None = None,
            enabled: bool | None = None,
            tags: list[str] | None = None,
            extra_headers: dict[str, str] | None = None,
            invoke_metadata_defaults: dict[str, str] | None = None,
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
                    "enabled": enabled,
                    "tags": tags,
                    "extra_headers": extra_headers,
                    "invoke_metadata_defaults": invoke_metadata_defaults,
                },
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

    if _exposed(SELF_SESSIONS_LIST.operation_id):

        @mcp.tool(
            name=SELF_SESSIONS_LIST.tool_name,
            description=SELF_SESSIONS_LIST.description,
        )
        async def self_sessions_list(
            page: int = 1,
            size: int = 20,
            source: str | None = None,
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
