"""FastAPI entry point for a2a-client-hub."""

import importlib
import inspect
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Awaitable, Callable, Dict, cast

import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.api.error_handlers import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.api.routers import ROUTER_MODULES
from app.core.config import settings
from app.core.http_client import close_global_http_client, init_global_http_client
from app.core.logging import get_logger, setup_logging
from app.db.session import AsyncSessionLocal
from app.db.transaction import run_with_new_session
from app.features.auth.cleanup_service import ensure_auth_cleanup_job
from app.features.schedules.job import ensure_a2a_schedule_job
from app.features.schedules.service import (
    ensure_a2a_schedule_execution_cleanup_job,
)
from app.features.self_management_agent.follow_up_job import (
    ensure_self_management_follow_up_job,
)
from app.features.self_management_shared.self_management_mcp import (
    SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH,
    SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS,
    SELF_MANAGEMENT_MCP_WRITE_MOUNT_PATH,
    SELF_MANAGEMENT_MCP_WRITE_OPERATION_IDS,
    build_self_management_mcp_http_app,
)
from app.integrations.a2a_client import get_a2a_service, shutdown_a2a_service
from app.integrations.a2a_extensions import (
    get_a2a_extensions_service,
    shutdown_a2a_extensions_service,
)
from app.middleware.debug_logging import DebugLoggingMiddleware
from app.runtime.a2a_proxy_service import a2a_proxy_service
from app.runtime.health import run_health_checks
from app.runtime.scheduler import shutdown_scheduler, start_scheduler
from app.runtime.ws_ticket import ensure_ws_ticket_cleanup_job
from app.utils.timezone_util import utc_now_iso

# Set up logging first
setup_logging()

logger = get_logger(__name__)


def combine_lifespans(
    *lifespans: Callable[[FastAPI], AbstractAsyncContextManager[None]],
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Combine multiple ASGI lifespan context managers into one."""

    @asynccontextmanager
    async def _combined(app: FastAPI) -> AsyncIterator[None]:
        async with lifespans[0](app):
            if len(lifespans) == 1:
                yield
                return
            async with combine_lifespans(*lifespans[1:])(app):
                yield

    return _combined


# Lifecycle management for the FastAPI application.
async def _run_startup_step(
    *,
    name: str,
    step: Callable[[], Any | Awaitable[Any]],
) -> None:
    try:
        result = step()
        if inspect.isawaitable(result):
            await result
        logger.info("Startup step completed: %s", name)
    except Exception:
        logger.exception("Startup step failed: %s", name)
        raise


async def _shutdown_runtime_components() -> None:
    await shutdown_a2a_extensions_service()
    await shutdown_a2a_service()
    shutdown_scheduler()
    await close_global_http_client()


@asynccontextmanager
async def app_lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        init_global_http_client()
        start_scheduler()
        ensure_a2a_schedule_job()
        ensure_auth_cleanup_job()
        ensure_a2a_schedule_execution_cleanup_job()
        ensure_self_management_follow_up_job()
        ensure_ws_ticket_cleanup_job()

        async def _init_a2a_service() -> None:
            service = cast(Any, get_a2a_service())
            await service.gateway.start_maintenance()

        await _run_startup_step(
            name="a2a_service_init",
            step=_init_a2a_service,
        )

        await _run_startup_step(
            name="a2a_extensions_service_init",
            step=get_a2a_extensions_service,
        )

        async def _refresh_proxy_cache() -> None:
            # Initialise A2A proxy allowlist cache.
            await run_with_new_session(
                a2a_proxy_service.prime_cache,
                session_factory=AsyncSessionLocal,
            )

        await _run_startup_step(
            name="a2a_proxy_allowlist_cache_init",
            step=_refresh_proxy_cache,
        )

        yield
    except Exception:
        await _shutdown_runtime_components()
        raise
    else:
        await _shutdown_runtime_components()


# Create FastAPI application instance
mcp_readonly_app = build_self_management_mcp_http_app(
    operation_ids=SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS
)
mcp_write_app = build_self_management_mcp_http_app(
    operation_ids=SELF_MANAGEMENT_MCP_WRITE_OPERATION_IDS
)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Backend API for a2a-client-hub",
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    docs_url=f"{settings.api_v1_prefix}/docs",
    redoc_url=f"{settings.api_v1_prefix}/redoc",
    lifespan=combine_lifespans(
        app_lifespan,
        mcp_readonly_app.lifespan,
        mcp_write_app.lifespan,
    ),
)

# Set up CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register global error handlers.
app.add_exception_handler(HTTPException, cast(Any, http_exception_handler))
app.add_exception_handler(
    RequestValidationError,
    cast(Any, validation_exception_handler),
)
app.add_exception_handler(Exception, unhandled_exception_handler)

# Compress JSON payloads to reduce response time on low-bandwidth clients
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Add request context/logging middleware
app.add_middleware(DebugLoggingMiddleware)


def include_all_routers() -> None:
    for module_name in ROUTER_MODULES:
        module = importlib.import_module(module_name)
        router = getattr(module, "router", None)
        if router is None:
            raise RuntimeError(
                f"Router module '{module_name}' does not export 'router'.",
            )
        app.include_router(router, prefix=settings.api_v1_prefix)
        logger.info("Successfully included router from: %s", module_name)


include_all_routers()
app.mount(SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH, mcp_readonly_app)
app.mount(SELF_MANAGEMENT_MCP_WRITE_MOUNT_PATH, mcp_write_app)


@app.get("/")
def read_root() -> Dict[str, Any]:
    """
    Root endpoint providing basic API information

    Returns:
        Basic API information and status
    """
    return {
        "message": "Welcome to A2A Client Backend API",
        "version": settings.app_version,
        "docs_url": f"{settings.api_v1_prefix}/docs",
        "status": "running",
    }


@app.get("/health")
async def health_check() -> JSONResponse:
    """
    Health check endpoint

    Returns:
        API health status
    """
    overall_status, checks = await run_health_checks()
    response_status = (
        status.HTTP_200_OK
        if overall_status != "unhealthy"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    payload: Dict[str, Any] = {
        "status": overall_status,
        "version": settings.app_version,
        "timestamp": utc_now_iso(),
        "checks": checks,
    }
    return JSONResponse(status_code=response_status, content=payload)


if __name__ == "__main__":
    workers = settings.uvicorn_workers if not settings.debug else 1
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        workers=max(1, workers),
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        log_config=None,  # Disable uvicorn default logging config to avoid duplicates
        access_log=False,  # Disable uvicorn access logs; use app logging config
    )
