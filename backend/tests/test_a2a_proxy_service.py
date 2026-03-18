from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.api import deps
from app.api.routers import admin_proxy_allowlist as admin_proxy_allowlist_router
from app.core.config import settings
from app.services.a2a_proxy_service import A2AProxyService, a2a_proxy_service
from tests.api_utils import create_test_client
from tests.utils import create_user


class _ScalarResult:
    def __init__(self, values: list[str]) -> None:
        self._values = values

    def scalars(self) -> "_ScalarResult":
        return self

    def all(self) -> list[str]:
        return list(self._values)


@pytest.fixture(autouse=True)
def reset_proxy_service_state() -> None:
    A2AProxyService._cached_allowed_hosts = []
    A2AProxyService._last_refresh = 0
    A2AProxyService._ttl = 60
    A2AProxyService._is_initialized = False
    A2AProxyService._refresh_lock = None
    A2AProxyService._refresh_lock_loop = None


@pytest.mark.asyncio
async def test_get_effective_allowed_hosts_singleflights_expired_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["settings.example.com"])

    execute_calls = 0
    release_execute = asyncio.Event()
    first_call_started = asyncio.Event()

    async def execute(_stmt):
        nonlocal execute_calls
        execute_calls += 1
        first_call_started.set()
        await release_execute.wait()
        return _ScalarResult(["db.example.com", "settings.example.com"])

    db = SimpleNamespace(execute=execute)

    async def read_allowed_hosts() -> list[str]:
        return await a2a_proxy_service.get_effective_allowed_hosts(db)

    tasks = [asyncio.create_task(read_allowed_hosts()) for _ in range(10)]
    await first_call_started.wait()
    await asyncio.sleep(0)
    assert execute_calls == 1

    release_execute.set()
    results = await asyncio.gather(*tasks)

    assert execute_calls == 1
    assert results == [
        ["settings.example.com", "db.example.com"] for _ in range(len(tasks))
    ]


@pytest.mark.asyncio
async def test_prime_cache_falls_back_to_settings_snapshot_on_db_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "a2a_proxy_allowed_hosts",
        ["settings.example.com", "settings.example.com"],
    )

    async def execute(_stmt):
        raise RuntimeError("db unavailable")

    db = SimpleNamespace(execute=execute)

    cached_hosts = await a2a_proxy_service.prime_cache(db)

    assert cached_hosts == ["settings.example.com"]
    assert a2a_proxy_service.get_effective_allowed_hosts_sync() == [
        "settings.example.com"
    ]
    assert a2a_proxy_service._is_initialized is True
    assert a2a_proxy_service._last_refresh > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_allowlist_write_refreshes_current_process_cache(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["settings.example.com"])

    admin = await create_user(
        async_db_session,
        email="admin_proxy_allowlist@example.com",
        is_superuser=True,
    )

    async with create_test_client(
        admin_proxy_allowlist_router.router,
        async_session_maker=async_session_maker,
        overrides={deps.get_current_admin_user: lambda: admin},
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/admin/proxy/allowlist",
            json={
                "host_pattern": "db.example.com",
                "is_enabled": True,
                "remark": "added during test",
            },
        )

    assert response.status_code == 201
    assert a2a_proxy_service.get_effective_allowed_hosts_sync() == [
        "settings.example.com",
        "db.example.com",
    ]


@pytest.mark.asyncio
async def test_failed_refresh_keeps_existing_snapshot_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["settings.example.com"])
    A2AProxyService._cached_allowed_hosts = ["cached.example.com"]
    A2AProxyService._last_refresh = 0
    A2AProxyService._is_initialized = True

    async def execute(_stmt):
        raise RuntimeError("db unavailable")

    db = SimpleNamespace(execute=execute)

    cached_hosts = await a2a_proxy_service.get_effective_allowed_hosts(db)

    assert cached_hosts == ["cached.example.com"]
    assert A2AProxyService._last_refresh == 0
