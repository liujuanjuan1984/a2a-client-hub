import importlib

import pytest
from fastapi import FastAPI

from app.api.routers import ROUTER_MODULES
from app.main import _run_startup_step


def test_router_registry_modules_export_router() -> None:
    for module_name in ROUTER_MODULES:
        module = importlib.import_module(module_name)
        assert hasattr(module, "router"), module_name


@pytest.mark.asyncio
async def test_run_startup_step_marks_degraded_for_non_critical_failure() -> None:
    app = FastAPI()

    async def failing_step() -> None:
        raise RuntimeError("boom")

    await _run_startup_step(
        app,
        name="non_critical_step",
        step=failing_step,
        critical=False,
    )

    assert app.state.startup_degraded is True
    assert app.state.startup_failures == ["non_critical_step"]


@pytest.mark.asyncio
async def test_run_startup_step_raises_for_critical_failure() -> None:
    app = FastAPI()

    def failing_step() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await _run_startup_step(
            app,
            name="critical_step",
            step=failing_step,
            critical=True,
        )
