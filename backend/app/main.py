"""FastAPI entry point for a2a-client-hub."""

import importlib
from contextlib import asynccontextmanager
from typing import Any, Dict

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
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.integrations.a2a_client import get_a2a_service, shutdown_a2a_service
from app.integrations.a2a_extensions import (
    get_a2a_extensions_service,
    shutdown_a2a_extensions_service,
)
from app.middleware.debug_logging import DebugLoggingMiddleware
from app.services.a2a_schedule_job import ensure_a2a_schedule_job
from app.services.health import run_health_checks
from app.services.scheduler import shutdown_scheduler, start_scheduler
from app.utils.timezone_util import utc_now_iso

# Set up logging first
setup_logging()

logger = get_logger(__name__)


# Lifecycle management for the FastAPI application.
@asynccontextmanager
async def app_lifespan(_: FastAPI):
    start_scheduler()
    ensure_a2a_schedule_job()
    try:
        get_a2a_service()
        logger.info("A2A service initialised during startup")
    except Exception as exc:  # pragma: no cover - defensive startup logging
        logger.error("Failed to initialise A2A service: %s", exc, exc_info=exc)
    try:
        get_a2a_extensions_service()
        logger.info("A2A extensions service initialised during startup")
    except Exception as exc:  # pragma: no cover - defensive startup logging
        logger.error(
            "Failed to initialise A2A extensions service: %s", exc, exc_info=exc
        )
    try:
        yield
    finally:
        await shutdown_a2a_extensions_service()
        await shutdown_a2a_service()
        shutdown_scheduler()


# Create FastAPI application instance
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Backend API for a2a-client-hub",
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    docs_url=f"{settings.api_v1_prefix}/docs",
    redoc_url=f"{settings.api_v1_prefix}/redoc",
    lifespan=app_lifespan,
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
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# Compress JSON payloads to reduce response time on low-bandwidth clients
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Add request context/logging middleware
app.add_middleware(DebugLoggingMiddleware)


def include_all_routers() -> None:
    router_modules = (
        "app.api.routers.auth",
        "app.api.routers.a2a_agents",
        "app.api.routers.hub_a2a_agents",
        "app.api.routers.admin_a2a_agents",
        "app.api.routers.a2a_extensions_opencode",
        "app.api.routers.hub_a2a_extensions_opencode",
        "app.api.routers.opencode_session_directory",
        "app.api.routers.a2a_schedules",
        "app.api.routers.me_sessions",
        "app.api.routers.invitations",
    )
    for module_name in router_modules:
        module = importlib.import_module(module_name)
        app.include_router(module.router, prefix=settings.api_v1_prefix)
        logger.info("Successfully included router from: %s", module_name)


include_all_routers()


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
def health_check() -> JSONResponse:
    """
    Health check endpoint

    Returns:
        API health status
    """
    overall_status, checks = run_health_checks()
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
