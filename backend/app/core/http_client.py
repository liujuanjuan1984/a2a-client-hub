"""Global HTTP client for the A2A client hub."""

from typing import cast

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.utils.async_cleanup import await_cancel_safe

logger = get_logger(__name__)

_global_http_client: httpx.AsyncClient | None = None


def resolve_http_client_timeout(
    timeout: httpx.Timeout | None = None,
) -> httpx.Timeout:
    """Resolve an explicit or default timeout for hub-managed HTTP clients."""

    return timeout or httpx.Timeout(
        max(settings.a2a_default_timeout, 1.0),
        connect=10.0,
    )


def create_http_client(*, timeout: httpx.Timeout | None = None) -> httpx.AsyncClient:
    """Build a hub-configured async HTTP client."""

    max_conn = max(settings.a2a_max_connections, 1)
    limits = httpx.Limits(
        max_connections=max_conn,
        max_keepalive_connections=max(1, max_conn // 2),
    )
    resolved_timeout = resolve_http_client_timeout(timeout)
    return httpx.AsyncClient(
        limits=limits,
        timeout=resolved_timeout,
    )


def init_global_http_client() -> None:
    """Initialize the global httpx client with connection pooling."""
    global _global_http_client
    if _global_http_client is None or _global_http_client.is_closed:
        _global_http_client = create_http_client()
        logger.info(
            "Global HTTP client initialized",
            extra={
                "max_connections": max(settings.a2a_max_connections, 1),
                "timeout": settings.a2a_default_timeout,
            },
        )


def get_global_http_client() -> httpx.AsyncClient:
    """Get the initialized global httpx client."""
    global _global_http_client
    if _global_http_client is None or _global_http_client.is_closed:
        if _global_http_client is not None and _global_http_client.is_closed:
            logger.warning(
                "Global HTTP client was closed unexpectedly; recreating client",
                extra={"http_client_recreated": True},
            )
        init_global_http_client()
    return cast(httpx.AsyncClient, _global_http_client)


async def close_global_http_client() -> None:
    """Close the global httpx client and release resources."""
    global _global_http_client
    if _global_http_client is not None and not _global_http_client.is_closed:
        await await_cancel_safe(_global_http_client.aclose())
        logger.info("Global HTTP client closed")
    _global_http_client = None
