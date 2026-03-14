"""Shared HTTP client providers for A2A transport adapters."""

from __future__ import annotations

from threading import Lock

import httpx

from app.core.http_client import create_http_client, resolve_http_client_timeout
from app.core.logging import get_logger
from app.utils.async_cleanup import await_cancel_safe

logger = get_logger(__name__)

_sdk_transport_clients: dict[tuple[float | None, ...], httpx.AsyncClient] = {}
_sdk_transport_clients_lock = Lock()


def get_shared_sdk_transport_http_client(
    *,
    timeout: httpx.Timeout | None = None,
) -> httpx.AsyncClient:
    """Return a shared SDK transport client keyed by timeout policy."""

    timeout_key = _build_timeout_key(timeout)
    with _sdk_transport_clients_lock:
        client = _sdk_transport_clients.get(timeout_key)
        if client is None or client.is_closed:
            client = create_http_client(timeout=resolve_http_client_timeout(timeout))
            _sdk_transport_clients[timeout_key] = client
            logger.info(
                "Initialized shared SDK transport HTTP client",
                extra={"timeout_key": timeout_key},
            )
        return client


async def close_shared_sdk_transport_http_clients() -> None:
    """Close all shared SDK transport clients."""

    with _sdk_transport_clients_lock:
        clients = list(_sdk_transport_clients.values())
        _sdk_transport_clients.clear()
    for client in clients:
        if client.is_closed:
            continue
        await await_cancel_safe(client.aclose())
    if clients:
        logger.info("Closed shared SDK transport HTTP clients")


def _build_timeout_key(timeout: httpx.Timeout | None) -> tuple[float | None, ...]:
    resolved = resolve_http_client_timeout(timeout)
    return (
        _normalize_timeout_value(resolved.connect),
        _normalize_timeout_value(resolved.read),
        _normalize_timeout_value(resolved.write),
        _normalize_timeout_value(resolved.pool),
    )


def _normalize_timeout_value(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


__all__ = [
    "close_shared_sdk_transport_http_clients",
    "get_shared_sdk_transport_http_client",
]
