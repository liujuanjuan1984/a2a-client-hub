"""
Common Compass Backend Main Application

This is the FastAPI application entry point for the Common Compass backend.
"""

import importlib
import pkgutil
from contextlib import asynccontextmanager
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.api import routers
from app.api.error_handlers import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.cardbox.config import setup_cardbox
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.integrations.a2a_client import get_a2a_service, shutdown_a2a_service
from app.middleware.debug_logging import DebugLoggingMiddleware
from app.services.a2a_schedule_job import ensure_a2a_schedule_job
from app.services.habit_expiration_job import ensure_habit_expiration_job
from app.services.health import run_health_checks
from app.services.scheduler import shutdown_scheduler, start_scheduler
from app.services.system_health_monitor import ensure_health_check_job
from app.utils.async_debug import enable_unawaited_coroutine_logging
from app.utils.timezone_util import utc_now_iso

# Set up logging first
setup_logging()

logger = get_logger(__name__)

# Configure Cardbox before building the FastAPI application. This guarantees
# any later Cardbox imports see the configured storage/settings.
setup_cardbox(settings)


# Lifecycle management for the FastAPI application.
@asynccontextmanager
async def app_lifespan(_: FastAPI):
    start_scheduler()
    ensure_health_check_job()
    ensure_habit_expiration_job()
    ensure_a2a_schedule_job()
    if settings.a2a_enabled:
        try:
            get_a2a_service()
            logger.info("A2A service initialised during startup")
        except Exception as exc:  # pragma: no cover - defensive startup logging
            logger.error("Failed to initialise A2A service: %s", exc, exc_info=exc)
    try:
        yield
    finally:
        await shutdown_a2a_service()
        shutdown_scheduler()


# Create FastAPI application instance
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Backend API for Common Compass - Your Personal Navigation Tool",
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
if settings.debug:
    enable_unawaited_coroutine_logging()


def include_all_routers() -> None:
    for module_loader, module_name, _ in pkgutil.iter_modules(
        routers.__path__, routers.__name__ + "."
    ):
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "router"):
                app.include_router(module.router, prefix=settings.api_v1_prefix)
                logger.info("Successfully included router from: %s", module_name)

        except Exception as e:
            logger.error("Failed to include router from %s: %s", module_name, e)


include_all_routers()


@app.get("/")
def read_root() -> Dict[str, Any]:
    """
    Root endpoint providing basic API information

    Returns:
        Basic API information and status
    """
    return {
        "message": "Welcome to Common Compass API",
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
