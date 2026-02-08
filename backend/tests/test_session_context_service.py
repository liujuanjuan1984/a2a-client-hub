from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.services.session_context_service import (
    PREFERENCE_MODULE,
    SessionContextService,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def service() -> SessionContextService:
    return SessionContextService()


@pytest.mark.asyncio
async def test_save_selection(monkeypatch, service):
    captured: dict[str, Any] = {}

    async def fake_set_preference(db, *, user_id, key, value, module):
        captured.update(
            {"db": db, "user_id": user_id, "key": key, "value": value, "module": module}
        )

    monkeypatch.setattr(
        "app.services.session_context_service.user_preferences_service.set_preference_value",
        fake_set_preference,
    )
    monkeypatch.setattr(
        "app.services.session_context_service.utc_now_iso",
        lambda: "2024-01-02T03:04:05Z",
    )

    user_id = uuid4()
    session_id = uuid4()
    payload = await service.save_selection(
        db="async-db",
        user_id=user_id,
        session_id=session_id,
        box_ids=[1, 2],
    )

    assert payload["boxes"] == [
        {"box_id": 1, "order": 0},
        {"box_id": 2, "order": 1},
    ]
    assert captured["module"] == PREFERENCE_MODULE
    assert captured["db"] == "async-db"


@pytest.mark.asyncio
async def test_load_selection(monkeypatch, service):
    class Pref:
        def __init__(self, value):
            self.value = value

    async def fake_get_preference(db, *, user_id, key):
        return Pref(
            {
                "boxes": [
                    {"box_id": 5, "order": 3},
                    {"box_id": 4, "order": 1},
                ]
            }
        )

    monkeypatch.setattr(
        "app.services.session_context_service.user_preferences_service.get_preference_by_key",
        fake_get_preference,
    )

    result = await service.load_selection(
        db="async-db",
        user_id=uuid4(),
        session_id=uuid4(),
    )

    assert result == [
        {"box_id": 4, "order": 1},
        {"box_id": 5, "order": 3},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pref_value",
    [
        None,
        {},
        {"boxes": "bad"},
        {"boxes": [1, 2, 3]},
    ],
)
async def test_load_selection_handles_invalid(monkeypatch, service, pref_value):
    class Pref:
        def __init__(self, value):
            self.value = value

    async def fake_get_preference(db, *, user_id, key):
        return Pref(pref_value)

    monkeypatch.setattr(
        "app.services.session_context_service.user_preferences_service.get_preference_by_key",
        fake_get_preference,
    )

    result = await service.load_selection(
        db="async-db",
        user_id=uuid4(),
        session_id=uuid4(),
    )

    assert result == []


@pytest.mark.asyncio
async def test_load_selection_returns_empty_when_missing(monkeypatch, service):
    async def fake_get_preference(db, *, user_id, key):
        return None

    monkeypatch.setattr(
        "app.services.session_context_service.user_preferences_service.get_preference_by_key",
        fake_get_preference,
    )

    result = await service.load_selection(
        db="async-db",
        user_id=uuid4(),
        session_id=uuid4(),
    )

    assert result == []
