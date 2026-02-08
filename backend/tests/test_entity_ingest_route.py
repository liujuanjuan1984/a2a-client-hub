from __future__ import annotations

import pytest
from sqlalchemy import select

from app.agents.service_types import AgentServiceResult
from app.agents.tools.note_tools import CreateNoteTool
from app.agents.tools.person_tools import CreatePersonTool
from app.agents.tools.tag_tools import CreateTagTool
from app.api.routers import entity_ingest as ingest_router
from app.db.models.note import Note
from app.db.models.person import Person
from app.db.models.tag import Tag
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _fake_agent_run(
    user_message: str, db, user_id, **_kwargs
) -> AgentServiceResult:
    """Simulate the agent by invoking real tools in a fixed order."""

    tag_tool = CreateTagTool(db, user_id)
    tag_result = await tag_tool.execute(name="前同事", entity_type="person")
    tag_id = tag_result.data["tag"]["id"]

    person_tool = CreatePersonTool(db, user_id)
    person_result = await person_tool.execute(name="吴昊", tag_ids=[tag_id])
    person_id = person_result.data["person"]["id"]

    note_tool = CreateNoteTool(db, user_id)
    await note_tool.execute(
        content=user_message,
        person_ids=[person_id],
        tag_ids=[tag_id],
        task_id=None,
    )

    return AgentServiceResult(
        content="done",
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        cost_usd=None,
        response_time_ms=0,
        model_name="fake-model",
        raw_response={},
        tool_runs=[],
    )


async def test_entity_ingest_creates_records(
    async_db_session, async_session_maker, monkeypatch
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    monkeypatch.setattr(
        ingest_router.agent_service,
        "generate_response_with_tools",
        _fake_agent_run,
    )

    async with create_test_client(
        ingest_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/entity/ingest",
            json={"text": "昨天和前同事吴昊语音，聊了些事。"},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["content"] == "done"

    persons = (await async_db_session.execute(select(Person))).scalars().all()
    tags = (await async_db_session.execute(select(Tag))).scalars().all()
    notes = (await async_db_session.execute(select(Note))).scalars().all()

    assert len(persons) == 1
    assert len(tags) == 1
    assert len(notes) == 1
    assert notes[0].content.startswith("昨天和前同事")


async def test_entity_ingest_validation_error(
    async_db_session, async_session_maker, monkeypatch
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    # Even if patched, request should fail before hitting the agent when payload is invalid
    monkeypatch.setattr(
        ingest_router.agent_service,
        "generate_response_with_tools",
        _fake_agent_run,
    )

    async with create_test_client(
        ingest_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post("/entity/ingest", json={"text": ""})

    assert resp.status_code == 422
