"""Global HTTP client for the A2A client hub."""

from typing import Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_global_http_client: Optional[httpx.AsyncClient] = None


def init_global_http_client() -> None:
    """Initialize the global httpx client with connection pooling."""
    global _global_http_client
    if _global_http_client is None:
        # Reasonably large limits for global reuse
        max_conn = max(settings.a2a_max_connections, 100)
        limits = httpx.Limits(
            max_connections=max_conn,
            max_keepalive_connections=max(max_conn // 2, 20),
        )
        timeout = httpx.Timeout(
            max(settings.a2a_default_timeout, 1.0), 
            connect=10.0
        )

        _global_http_client = httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
        )
        logger.info(
            "Global HTTP client initialized",
            extra={
                "max_connections": max_conn,
                "timeout": settings.a2a_default_timeout,
            },
        )


def get_global_http_client() -> httpx.AsyncClient:
    """Get the initialized global httpx client."""
    global _global_http_client
    if _global_http_client is None:
        init_global_http_client()
    return _global_http_client


async def close_global_http_client() -> None:
    """Close the global httpx client and release resources."""
    global _global_http_client
    if _global_http_client is not None and not _global_http_client.is_closed:
        await _global_http_client.aclose()
        logger.info("Global HTTP client closed")
    _global_http_client = None
