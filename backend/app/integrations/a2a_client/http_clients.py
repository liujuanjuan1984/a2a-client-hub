"""Shared HTTP client providers for A2A transport adapters."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from threading import Lock
from typing import AsyncIterator

import httpx

from app.core.http_client import create_http_client, resolve_http_client_timeout
from app.core.logging import get_logger
from app.integrations.a2a_client.lifecycle import SharedSDKTransportBucketSnapshot
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
    active_users: int = 0
    invalidated: bool = False


class SharedSDKTransportInvalidatedError(RuntimeError):
    """Raised when a borrowed shared SDK transport lease is no longer current."""


_sdk_transport_clients: dict[tuple[float | None, ...], _SharedSDKTransportEntry] = {}
_sdk_transport_entries: dict[
    tuple[tuple[float | None, ...], int], _SharedSDKTransportEntry
] = {}
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
            _sdk_transport_entries[(timeout_key, generation)] = entry
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


def is_shared_sdk_transport_http_client_stale(lease: SharedSDKTransportLease) -> bool:
    """Check whether a borrowed shared transport lease is no longer usable."""

    with _sdk_transport_clients_lock:
        entry = _sdk_transport_entries.get((lease.timeout_key, lease.generation))
        return entry is None or entry.invalidated or entry.client.is_closed


def acquire_shared_sdk_transport_http_client_usage(
    lease: SharedSDKTransportLease,
) -> bool:
    """Mark one in-flight use of a shared transport generation."""

    with _sdk_transport_clients_lock:
        entry = _sdk_transport_entries.get((lease.timeout_key, lease.generation))
        if entry is None or entry.invalidated or entry.client.is_closed:
            return False
        entry.active_users += 1
        return True


async def release_shared_sdk_transport_http_client_usage(
    lease: SharedSDKTransportLease,
) -> None:
    """Release one in-flight use and close drained invalid generations."""

    stale_client: httpx.AsyncClient | None = None
    with _sdk_transport_clients_lock:
        entry = _sdk_transport_entries.get((lease.timeout_key, lease.generation))
        if entry is None:
            return
        if entry.active_users > 0:
            entry.active_users -= 1
        if entry.active_users == 0 and (entry.invalidated or entry.client.is_closed):
            _sdk_transport_entries.pop((lease.timeout_key, lease.generation), None)
            if _sdk_transport_clients.get(lease.timeout_key) is entry:
                _sdk_transport_clients.pop(lease.timeout_key, None)
            stale_client = entry.client
    if stale_client is not None and not stale_client.is_closed:
        await await_cancel_safe(stale_client.aclose())


@asynccontextmanager
async def use_shared_sdk_transport_http_client(
    lease: SharedSDKTransportLease | None,
) -> AsyncIterator[None]:
    """Guard one SDK transport operation against concurrent generation invalidation."""

    if lease is None:
        yield
        return
    if not acquire_shared_sdk_transport_http_client_usage(lease):
        raise SharedSDKTransportInvalidatedError(
            "Shared SDK transport lease is stale or invalidated."
        )
    try:
        yield
    finally:
        await release_shared_sdk_transport_http_client_usage(lease)


async def invalidate_shared_sdk_transport_http_client(
    lease: SharedSDKTransportLease,
) -> bool:
    """Invalidate one shared SDK transport client generation if still active."""

    stale_client: httpx.AsyncClient | None = None
    with _sdk_transport_clients_lock:
        entry = _sdk_transport_entries.get((lease.timeout_key, lease.generation))
        if entry is None or entry.invalidated:
            return False
        entry.invalidated = True
        if _sdk_transport_clients.get(lease.timeout_key) is entry:
            _sdk_transport_clients.pop(lease.timeout_key, None)
        if entry.active_users == 0:
            _sdk_transport_entries.pop((lease.timeout_key, lease.generation), None)
            stale_client = entry.client

    if stale_client is not None and not stale_client.is_closed:
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
        clients = [entry.client for entry in _sdk_transport_entries.values()]
        _sdk_transport_clients.clear()
        _sdk_transport_entries.clear()
    for client in clients:
        if client.is_closed:
            continue
        await await_cancel_safe(client.aclose())
    if clients:
        logger.info("Closed shared SDK transport HTTP clients")


def get_shared_sdk_transport_bucket_snapshot(
    *,
    timeout: httpx.Timeout | None = None,
) -> SharedSDKTransportBucketSnapshot | None:
    """Return observable state for one shared SDK transport timeout bucket."""

    timeout_key = _build_timeout_key(timeout)
    with _sdk_transport_clients_lock:
        entries = [
            entry
            for (
                entry_timeout_key,
                _generation,
            ), entry in _sdk_transport_entries.items()
            if entry_timeout_key == timeout_key
        ]
        if not entries and timeout_key not in _sdk_transport_clients:
            return None
        current_entry = _sdk_transport_clients.get(timeout_key)
        invalidated_generations = sum(1 for entry in entries if entry.invalidated)
        draining_generations = sum(
            1 for entry in entries if entry.invalidated and entry.active_users > 0
        )
        active_users = sum(entry.active_users for entry in entries)
        return SharedSDKTransportBucketSnapshot(
            timeout_key=timeout_key,
            current_generation=(
                current_entry.generation if current_entry is not None else None
            ),
            tracked_generations=len(entries),
            invalidated_generations=invalidated_generations,
            draining_generations=draining_generations,
            active_users=active_users,
        )


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
    "SharedSDKTransportInvalidatedError",
    "acquire_shared_sdk_transport_http_client_usage",
    "borrow_shared_sdk_transport_http_client",
    "close_shared_sdk_transport_http_clients",
    "get_shared_sdk_transport_bucket_snapshot",
    "invalidate_shared_sdk_transport_http_client",
    "is_shared_sdk_transport_http_client_stale",
    "release_shared_sdk_transport_http_client_usage",
    "use_shared_sdk_transport_http_client",
]
