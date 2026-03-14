"""Shared HTTP client providers for A2A transport adapters."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

import httpx

from app.core.http_client import create_http_client, resolve_http_client_timeout
from app.core.logging import get_logger
from app.utils.async_cleanup import await_cancel_safe

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SharedSDKTransportLease:
    """Borrowed view of one shared SDK transport client bucket."""

    timeout_key: tuple[float | None, ...]
    generation: int
    client: httpx.AsyncClient


@dataclass(slots=True)
class _SharedSDKTransportEntry:
    generation: int
    client: httpx.AsyncClient


_sdk_transport_clients: dict[tuple[float | None, ...], _SharedSDKTransportEntry] = {}
_sdk_transport_generations: dict[tuple[float | None, ...], int] = {}
_sdk_transport_clients_lock = Lock()


def borrow_shared_sdk_transport_http_client(
    *,
    timeout: httpx.Timeout | None = None,
) -> SharedSDKTransportLease:
    """Borrow a shared SDK transport client keyed by timeout policy."""

    timeout_key = _build_timeout_key(timeout)
    with _sdk_transport_clients_lock:
        entry = _sdk_transport_clients.get(timeout_key)
        if entry is None or entry.client.is_closed:
            generation = _sdk_transport_generations.get(timeout_key, 0) + 1
            entry = _SharedSDKTransportEntry(
                generation=generation,
                client=create_http_client(timeout=resolve_http_client_timeout(timeout)),
            )
            _sdk_transport_clients[timeout_key] = entry
            _sdk_transport_generations[timeout_key] = generation
            logger.info(
                "Initialized shared SDK transport HTTP client",
                extra={
                    "timeout_key": timeout_key,
                    "generation": generation,
                },
            )
        return SharedSDKTransportLease(
            timeout_key=timeout_key,
            generation=entry.generation,
            client=entry.client,
        )


async def invalidate_shared_sdk_transport_http_client(
    lease: SharedSDKTransportLease,
) -> bool:
    """Invalidate one shared SDK transport client generation if still active."""

    with _sdk_transport_clients_lock:
        entry = _sdk_transport_clients.get(lease.timeout_key)
        if entry is None or entry.generation != lease.generation:
            return False
        stale_client = entry.client
        _sdk_transport_clients.pop(lease.timeout_key, None)

    if not stale_client.is_closed:
        await await_cancel_safe(stale_client.aclose())
    logger.info(
        "Invalidated shared SDK transport HTTP client",
        extra={
            "timeout_key": lease.timeout_key,
            "generation": lease.generation,
        },
    )
    return True


async def close_shared_sdk_transport_http_clients() -> None:
    """Close all shared SDK transport clients."""

    with _sdk_transport_clients_lock:
        clients = [entry.client for entry in _sdk_transport_clients.values()]
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
    "SharedSDKTransportLease",
    "borrow_shared_sdk_transport_http_client",
    "close_shared_sdk_transport_http_clients",
    "invalidate_shared_sdk_transport_http_client",
]
