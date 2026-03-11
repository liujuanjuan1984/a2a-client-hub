import importlib

import pytest

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
