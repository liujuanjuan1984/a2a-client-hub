from __future__ import annotations

import asyncio
import inspect
import types
import typing
from dataclasses import dataclass
from typing import Any, Callable, Optional
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api.routers import actual_event_templates as actual_event_templates_router
from app.api.routers import actual_events as actual_events_router
from app.api.routers import export as export_router
from app.api.routers import finance_accounts as finance_accounts_router
from app.api.routers import food_entries as food_entries_router
from app.api.routers import habits as habits_router
from app.api.routers import notes as notes_router
from app.api.routers import planned_events as planned_events_router
from app.api.routers import tags as tags_router
from app.api.routers import tasks as tasks_router
from app.core.config import settings
from app.main import app
from backend.tests.api_utils import create_test_client
from backend.tests.conftest import _truncate_all_tables
from backend.tests.utils import create_user


def _is_uuid_type(annotation: Any) -> bool:
    if annotation is inspect._empty:
        return False
    if annotation is UUID:
        return True
    origin = typing.get_origin(annotation)
    if origin is None:
        return annotation is UUID
    if origin is typing.Annotated:
        args = typing.get_args(annotation)
        return bool(args) and _is_uuid_type(args[0])
    if origin in (typing.Union, types.UnionType):
        return any(
            _is_uuid_type(arg)
            for arg in typing.get_args(annotation)
            if arg is not type(None)  # noqa: E721
        )
    return False


@pytest.mark.unit
def test_uuid_paths_use_uuid_converter():
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue

        endpoint = route.dependant.call or route.endpoint
        signature = inspect.signature(endpoint)

        for param in route.dependant.path_params:
            parameter = signature.parameters.get(param.name)
            if parameter is None:
                continue
            if _is_uuid_type(parameter.annotation):
                expected = f"{{{param.name}:uuid}}"
                assert (
                    expected in route.path
                ), f"Route '{route.path}' should declare '{expected}' to avoid path conflicts."


def _collect_export_routes() -> set[tuple[str, tuple[str, ...]]]:
    """Mount the export router on a fresh app and collect route+methods."""

    test_app = FastAPI()
    test_app.include_router(export_router.router, prefix=settings.api_v1_prefix)
    routes: set[tuple[str, tuple[str, ...]]] = set()
    for route in test_app.routes:
        if not isinstance(route, APIRoute):
            continue
        routes.add((route.path, tuple(sorted(route.methods or []))))
    return routes


def _find_route(
    routes: set[tuple[str, tuple[str, ...]]], path: str, method: str
) -> bool:
    method = method.upper()
    return any(rp == path and method in methods for rp, methods in routes)


def test_export_routes_registered():
    """Ensure critical export endpoints are defined in the export router."""

    routes = _collect_export_routes()

    base = settings.api_v1_prefix.rstrip("/")
    expected = {
        f"{base}/export/estimate": ["POST"],
        f"{base}/export/timelog": ["POST"],
        f"{base}/export/notes": ["POST"],
        f"{base}/export/planning": ["POST"],
        f"{base}/export/visions/{{vision_id}}": ["GET"],
        f"{base}/export/finance/trading": ["POST"],
        f"{base}/export/finance/accounts": ["POST"],
        f"{base}/export/finance/cashflow": ["POST"],
        f"{base}/export/full": ["POST"],
    }

    missing = []
    for path, methods in expected.items():
        for method in methods:
            if not _find_route(routes, path, method):
                missing.append(f"{method} {path}")

    assert not missing, f"Export routes not registered: {', '.join(missing)}"


@pytest.fixture(scope="module")
def router_test_user(async_session_maker, async_engine):
    """Provision a shared user to avoid recreating onboarding data per test."""

    async def _setup():
        async with async_session_maker() as session:
            user = await create_user(session, skip_onboarding_defaults=True)
            await session.commit()
            await session.refresh(user)
            session.expunge(user)
            return user

    user = asyncio.run(_setup())

    try:
        yield user
    finally:
        asyncio.run(_truncate_all_tables(async_engine))


@dataclass(frozen=True)
class StaticPathCase:
    name: str
    router: Any
    method: str
    path: str
    expected_status: int
    json_factory: Optional[Callable[[], dict]] = None
    params: Optional[dict] = None
    assert_json: Optional[Callable[[dict], None]] = None


def _payload_reorder_tasks() -> dict:
    return {"task_orders": [{"id": str(uuid4()), "display_order": 0}]}


STATIC_PATH_CASES = [
    StaticPathCase(
        name="actual_events_raw",
        router=actual_events_router.router,
        method="GET",
        path="/actual-events/raw",
        expected_status=200,
        assert_json=lambda body: body["items"] == [],
    ),
    StaticPathCase(
        name="tasks_reorder",
        router=tasks_router.router,
        method="POST",
        path="/tasks/reorder",
        expected_status=404,
        json_factory=_payload_reorder_tasks,
    ),
    StaticPathCase(
        name="notes_advanced_search",
        router=notes_router.router,
        method="POST",
        path="/notes/advanced-search",
        expected_status=200,
        json_factory=lambda: {},
        assert_json=lambda body: body["items"] == [],
    ),
    StaticPathCase(
        name="habits_task_associations",
        router=habits_router.router,
        method="GET",
        path="/habits/habit-task-associations/",
        expected_status=200,
        assert_json=lambda body: body.get("associations", {}) == {},
    ),
    StaticPathCase(
        name="planned_events_raw",
        router=planned_events_router.router,
        method="GET",
        path="/planned-events/raw",
        expected_status=200,
        params={"skip": 0, "limit": 10},
        assert_json=lambda body: body["items"] == [],
    ),
    StaticPathCase(
        name="tags_entity_types",
        router=tags_router.router,
        method="GET",
        path="/tags/entity-types/",
        expected_status=200,
        assert_json=lambda body: "person" in body,
    ),
    StaticPathCase(
        name="food_entries_daily_summary",
        router=food_entries_router.router,
        method="GET",
        path="/food-entries/daily-summary/2025-01-01",
        expected_status=200,
        assert_json=lambda body: body["date"] == "2025-01-01"
        and body["entry_count"] == 0,
    ),
    StaticPathCase(
        name="finance_accounts_tree",
        router=finance_accounts_router.router,
        method="GET",
        path="/finance/accounts/tree",
        expected_status=200,
        assert_json=lambda body: "accounts" in body,
    ),
    StaticPathCase(
        name="actual_event_templates_reorder",
        router=actual_event_templates_router.router,
        method="PATCH",
        path="/actual-events/templates/reorder",
        expected_status=204,
        json_factory=lambda: {"items": []},
    ),
]


async def _request_with_case(client, case: StaticPathCase):
    method = case.method.upper()
    payload = case.json_factory() if case.json_factory else None

    if method == "GET":
        return await client.get(case.path, params=case.params)
    if method == "POST":
        return await client.post(case.path, json=payload, params=case.params)
    if method == "PATCH":
        return await client.patch(case.path, json=payload, params=case.params)

    raise ValueError(f"Unsupported method: {case.method}")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("case", STATIC_PATH_CASES, ids=lambda case: case.name)
async def test_static_paths_resolve(router_test_user, async_session_maker, case):
    user = router_test_user

    async with create_test_client(
        case.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await _request_with_case(client, case)

    assert response.status_code == case.expected_status
    if case.assert_json is not None:
        assert case.assert_json(response.json())
