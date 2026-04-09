"""FastMCP adapter for self-management operations."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastmcp import Context, FastMCP
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import verify_access_token
from app.db.session import AsyncSessionLocal
from app.features.agents_shared.actor_context import SelfManagementAuthorizationError
from app.features.agents_shared.capability_catalog import (
    SELF_JOBS_GET,
    SELF_JOBS_LIST,
    SELF_JOBS_PAUSE,
)
from app.features.agents_shared.self_management_toolkit import (
    SelfManagementToolInputError,
)
from app.features.agents_shared.self_management_web_agent import (
    build_self_management_web_agent_runtime,
)
from app.features.auth.service import UserNotFoundError, get_active_user

logger = get_logger(__name__)

SELF_MANAGEMENT_MCP_MOUNT_PATH = "/mcp"
_MCP_USER_ID_STATE_KEY = "self_management_mcp_user_id"


class SelfManagementMcpAuthMiddleware(BaseHTTPMiddleware):
    """Require a valid hub bearer token for every MCP HTTP request."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
            )

        token = auth_header[7:].strip()
        raw_user_id = verify_access_token(token)
        if raw_user_id is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        setattr(request.state, _MCP_USER_ID_STATE_KEY, raw_user_id)
        return await call_next(request)


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


async def execute_self_management_mcp_operation(
    *,
    user_id: UUID,
    operation_id: str,
    arguments: Mapping[str, Any] | None = None,
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


def build_self_management_mcp_server() -> FastMCP:
    """Build the FastMCP server exposing first-wave self-management tools."""

    mcp = FastMCP(
        "a2a-client-hub self-management",
        version=settings.app_version,
        instructions=(
            "Use these tools to manage the authenticated user's jobs inside "
            "a2a-client-hub. All operations are scoped to the current user."
        ),
    )

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
        )

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
        )

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
        )

    return mcp


self_management_mcp_server = build_self_management_mcp_server()


def build_self_management_mcp_http_app() -> Any:
    """Build the mounted FastMCP HTTP app for swival consumption."""

    return self_management_mcp_server.http_app(
        path="/",
        transport="sse",
        middleware=[Middleware(SelfManagementMcpAuthMiddleware)],
    )


__all__ = [
    "SELF_MANAGEMENT_MCP_MOUNT_PATH",
    "SelfManagementMcpAuthMiddleware",
    "build_self_management_mcp_http_app",
    "build_self_management_mcp_server",
    "execute_self_management_mcp_operation",
    "self_management_mcp_server",
]
