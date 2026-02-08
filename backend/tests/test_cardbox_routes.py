from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.routers import cardbox as cardbox_router
from app.cardbox import context_service as context_service_module
from app.cardbox import service as cardbox_service_module
from app.db.models.agent_session import AgentSession
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _make_session(db, user):
    session = AgentSession(
        id=uuid4(),
        user_id=user.id,
        name="Test Session",
        description="",
        module_key=None,
        cardbox_name="session-box",
    )
    db.add(session)
    await db.flush()
    await db.commit()
    return session


async def test_list_session_messages_returns_items(
    async_db_session, async_session_maker, monkeypatch
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    session = await _make_session(async_db_session, user)

    def fake_list_session_messages(**kwargs):
        return [{"content": "hi", "metadata": {}}]

    monkeypatch.setattr(
        cardbox_service_module.cardbox_service,
        "list_session_messages",
        fake_list_session_messages,
    )

    async with create_test_client(
        cardbox_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        db_session=async_db_session,
    ) as client:
        response = await client.get(f"/cardbox/session/{session.id}/messages")

    assert response.status_code == 200
    assert response.json()["items"][0]["content"] == "hi"


async def test_list_session_messages_missing_session_returns_404(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    async with create_test_client(
        cardbox_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        db_session=async_db_session,
    ) as client:
        response = await client.get(f"/cardbox/session/{uuid4()}/messages")
    assert response.status_code == 404


async def test_list_context_boxes(monkeypatch, async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    record = SimpleNamespace(
        box_id=1,
        name="context/box",
        module="notes",
        display_name="Notes",
        card_count=3,
        updated_at="2025-01-01T00:00:00Z",
        manifest_metadata={"foo": "bar"},
    )

    def fake_list_context_boxes(user_id):
        return [record]

    monkeypatch.setattr(
        context_service_module.context_box_manager,
        "list_context_boxes",
        fake_list_context_boxes,
    )

    async with create_test_client(
        cardbox_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        db_session=async_db_session,
    ) as client:
        response = await client.get("/cardbox/context/list")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["name"] == "context/box"
    assert payload["pagination"]["total"] == 1


async def test_create_context_box_validation_error(
    monkeypatch, async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async def fake_create_context_box(*args, **kwargs):
        raise ValueError("bad module")

    monkeypatch.setattr(
        context_service_module.context_box_manager,
        "create_context_box",
        fake_create_context_box,
    )

    async with create_test_client(
        cardbox_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        db_session=async_db_session,
    ) as client:
        response = await client.post(
            "/cardbox/context/create",
            json={"module": "invalid", "filters": {}, "name": "box", "overwrite": True},
        )

    assert response.status_code == 400


async def test_preview_context_box_returns_items(
    monkeypatch, async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    record = SimpleNamespace(
        box_id=2,
        name="context/test",
        module="notes",
        display_name="Test",
        card_count=1,
        updated_at="2025-02-01T00:00:00Z",
        manifest_metadata={},
    )

    card = SimpleNamespace(
        card_id="card-1",
        content=SimpleNamespace(text="content"),
        metadata={"stage": "summary"},
        text=lambda: "content",
    )

    def fake_get_record(user_id, box_id):
        return record

    def fake_load_box_cards(**kwargs):
        return [card]

    monkeypatch.setattr(
        context_service_module.context_box_manager,
        "get_record_by_id",
        fake_get_record,
    )
    monkeypatch.setattr(
        context_service_module.context_box_manager,
        "load_box_cards",
        fake_load_box_cards,
    )

    async with create_test_client(
        cardbox_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        db_session=async_db_session,
    ) as client:
        response = await client.get("/cardbox/context/2/items")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["content"] == "content"


async def test_delete_context_box_not_found(
    monkeypatch, async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    def fake_delete_box(user_id, box_id):
        return False

    monkeypatch.setattr(
        context_service_module.context_box_manager,
        "delete_box_by_id",
        fake_delete_box,
    )

    async with create_test_client(
        cardbox_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        db_session=async_db_session,
    ) as client:
        response = await client.delete("/cardbox/context/999")

    assert response.status_code == 404


async def test_create_context_box_success(
    monkeypatch, async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    record = SimpleNamespace(
        box_id=3,
        name="context/success",
        module="notes",
        display_name="Success",
        card_count=0,
        updated_at="2025-05-01T00:00:00Z",
        manifest_metadata={},
    )

    async def fake_create_context_box(*args, **kwargs):
        return record

    monkeypatch.setattr(
        context_service_module.context_box_manager,
        "create_context_box",
        fake_create_context_box,
    )

    async with create_test_client(
        cardbox_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        db_session=async_db_session,
    ) as client:
        response = await client.post(
            "/cardbox/context/create",
            json={
                "module": "notes",
                "filters": {},
                "name": "Success",
                "overwrite": True,
            },
        )

    assert response.status_code == 201
    assert response.json()["box"]["name"] == "context/success"
