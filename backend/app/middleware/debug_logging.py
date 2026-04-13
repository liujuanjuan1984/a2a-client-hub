"""
Debug logging middleware for development and troubleshooting.

This middleware provides detailed logging of API requests and responses,
particularly useful for debugging agent chat interactions.
"""

import time
import uuid
from typing import Callable, cast

from fastapi import Request, Response
from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.logging import (
    clear_actor_context,
    clear_user_context,
    get_logger,
    reset_actor_context,
    reset_request_id,
    reset_user_context,
    set_actor_context,
    set_request_id,
    set_user_context,
)
from app.core.security import ACCESS_TOKEN_TYPE, verify_jwt_token
from app.utils.logging_redaction import (
    redact_headers_for_logging,
    redact_query_params_for_logging,
)

logger = get_logger(__name__)


class DebugLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log detailed request/response information for debugging."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Record request start time
        start_time = time.perf_counter()
        request_id = uuid.uuid4().hex[:8]
        token = set_request_id(request_id)
        user_token = clear_user_context()
        actor_token = clear_actor_context()
        auth_header = request.headers.get("authorization")
        if auth_header:
            scheme, _, credentials = auth_header.partition(" ")
            if scheme.lower() == "bearer" and credentials:
                user_id = verify_jwt_token(
                    credentials,
                    expected_type=ACCESS_TOKEN_TYPE,
                )
                if user_id:
                    set_user_context(user_id)
                    set_actor_context(
                        principal_user_id=str(user_id),
                        actor_type="human_api",
                        admin_mode=False,
                    )
                    request.state.user_id = user_id
        request.state.request_id = request_id

        if settings.debug:
            logger.info(
                "Request started",
                extra={
                    "event": "request_started",
                    "method": request.method,
                    "path": request.url.path,
                },
            )

        # Log specific agent chat requests with more detail
        if request.url.path == "/api/v1/agent/chat":
            client_ip = request.client.host if request.client else "unknown"
            logger.debug(f"Agent chat request from {client_ip}")
            logger.debug(
                "Request headers: %s",
                redact_headers_for_logging(dict(request.headers)),
            )
            logger.debug(
                "Query params: %s",
                redact_query_params_for_logging(dict(request.query_params)),
            )

        cleanup_scheduled = False

        def _cleanup_context() -> None:
            nonlocal cleanup_scheduled
            if cleanup_scheduled:
                return
            cleanup_scheduled = True
            reset_request_id(token)
            reset_user_context(user_token)
            reset_actor_context(actor_token)

        # Process the request
        try:
            response = await call_next(request)
            process_time = time.perf_counter() - start_time

            if settings.debug:
                logger.info(
                    "Request completed",
                    extra={
                        "event": "request_completed",
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "duration": round(process_time, 6),
                    },
                )

            response.headers.setdefault("X-Request-ID", request_id)

            if hasattr(response, "call_on_close") and callable(response.call_on_close):
                response.call_on_close(_cleanup_context)
            else:
                background = response.background

                async def _run_background_and_cleanup() -> None:
                    if background is not None:
                        await background()
                    _cleanup_context()

                response.background = BackgroundTask(_run_background_and_cleanup)

            # Log streaming response start details
            if request.url.path == "/api/v1/agent/chat" and response.status_code == 200:
                logger.debug("Streaming response initiated for session")

            return cast(Response, response)

        except Exception as exc:
            process_time = time.perf_counter() - start_time
            if settings.debug:
                logger.error(
                    "Request failed",
                    extra={
                        "event": "request_failed",
                        "method": request.method,
                        "path": request.url.path,
                        "duration": round(process_time, 6),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
            _cleanup_context()
            raise
