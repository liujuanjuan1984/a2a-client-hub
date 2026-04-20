import importlib

import pytest
from fastapi import FastAPI

from app import main as main_module
from app.api.routers import ROUTER_MODULES
from app.main import _run_startup_step


def test_router_registry_modules_export_router() -> None:
    for module_name in ROUTER_MODULES:
        module = importlib.import_module(module_name)
        assert hasattr(module, "router"), module_name


@pytest.mark.asyncio
async def test_run_startup_step_raises_for_async_failure() -> None:
    async def failing_step() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await _run_startup_step(
            name="async_step",
            step=failing_step,
        )


@pytest.mark.asyncio
async def test_run_startup_step_raises_for_sync_failure() -> None:
    def failing_step() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await _run_startup_step(
            name="sync_step",
            step=failing_step,
        )


@pytest.mark.asyncio
async def test_app_lifespan_cleans_up_when_startup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    monkeypatch.setattr(main_module, "init_global_http_client", lambda: None)
    monkeypatch.setattr(main_module, "start_scheduler", lambda: called.append("start"))
    monkeypatch.setattr(
        main_module,
        "ensure_a2a_schedule_job",
        lambda: called.append("schedule_job"),
    )
    monkeypatch.setattr(
        main_module,
        "ensure_auth_cleanup_job",
        lambda: called.append("auth_cleanup_job"),
    )
    monkeypatch.setattr(
        main_module,
        "ensure_a2a_schedule_execution_cleanup_job",
        lambda: called.append("schedule_cleanup_job"),
    )
    monkeypatch.setattr(
        main_module,
        "ensure_self_management_follow_up_job",
        lambda: called.append("self_management_follow_up_job"),
    )
    monkeypatch.setattr(
        main_module,
        "ensure_self_management_dispatch_job",
        lambda: called.append("self_management_dispatch_job"),
    )
    monkeypatch.setattr(
        main_module,
        "ensure_ws_ticket_cleanup_job",
        lambda: called.append("ws_cleanup_job"),
    )

    def _raise_startup_failure() -> None:
        raise RuntimeError("startup failure")

    monkeypatch.setattr(main_module, "get_a2a_service", _raise_startup_failure)

    async def _noop_shutdown(*_: object, **__: object) -> None:
        return None

    async def _shutdown_a2a() -> None:
        called.append("shutdown_a2a")

    async def _shutdown_extensions() -> None:
        called.append("shutdown_extensions")

    async def _close_http() -> None:
        called.append("close_http")

    def _shutdown_scheduler() -> None:
        called.append("shutdown_scheduler")

    monkeypatch.setattr(main_module, "get_a2a_extensions_service", lambda: None)
    monkeypatch.setattr(main_module.a2a_proxy_service, "refresh_cache", _noop_shutdown)
    monkeypatch.setattr(main_module, "shutdown_a2a_service", _shutdown_a2a)
    monkeypatch.setattr(
        main_module,
        "shutdown_a2a_extensions_service",
        _shutdown_extensions,
    )
    monkeypatch.setattr(main_module, "close_global_http_client", _close_http)
    monkeypatch.setattr(main_module, "shutdown_scheduler", _shutdown_scheduler)

    with pytest.raises(RuntimeError, match="startup failure"):
        async with main_module.app_lifespan(FastAPI()):
            pass

    assert "auth_cleanup_job" in called
    assert "schedule_cleanup_job" in called
    assert "self_management_follow_up_job" in called
    assert "self_management_dispatch_job" in called
    assert "shutdown_scheduler" in called
    assert "close_http" in called
