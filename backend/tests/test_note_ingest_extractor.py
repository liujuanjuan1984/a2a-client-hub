from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from litellm import exceptions as litellm_exceptions

from app.agents.llm import llm_client
from app.db.models.note import Note
from app.services.note_ingest_extractor import (
    NoteIngestExtractionError,
    note_ingest_extractor,
)
from backend.tests.utils import create_user

pytestmark = pytest.mark.asyncio


def _mock_response(content: str) -> SimpleNamespace:
    choice = SimpleNamespace(message={"content": content})
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return SimpleNamespace(choices=[choice], usage=usage)


async def _create_note(session, user, *, content: str) -> Note:
    note = Note(user_id=user.id, content=content)
    session.add(note)
    await session.flush()
    return note


async def test_extractor_retries_until_tags_present(async_db_session, monkeypatch):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    note = await _create_note(async_db_session, user, content="测试标签逻辑")
    await async_db_session.commit()

    responses = [
        _mock_response(
            json.dumps(
                {
                    "note": {
                        "content": note.content,
                        "person_refs": [],
                        "tags": [],
                    },
                    "persons": [],
                    "tags": [],
                    "visions": [],
                    "tasks": [],
                    "habits": [],
                    "confidence": 0.5,
                    "uncertainties": [],
                }
            )
        ),
        _mock_response(
            json.dumps(
                {
                    "note": {
                        "content": note.content,
                        "person_refs": [],
                        "tags": ["测试"],
                    },
                    "persons": [],
                    "tags": [],
                    "visions": [],
                    "tasks": [],
                    "habits": [],
                    "confidence": 0.8,
                    "uncertainties": [],
                }
            )
        ),
    ]

    calls: list[list[dict]] = []

    async def fake_completion(*, messages, **kwargs):
        calls.append(messages)
        return responses[len(calls) - 1]

    monkeypatch.setattr(llm_client, "completion", fake_completion)

    result = await note_ingest_extractor.extract(
        async_db_session,
        user_id=user.id,
        note_id=note.id,
    )

    assert result.extraction.note.tags == ["测试"]
    assert len(calls) == 2
    assert "修正反馈" in calls[1][-1]["content"]


async def test_extractor_raises_after_exhausting_retries(async_db_session, monkeypatch):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    note = await _create_note(async_db_session, user, content="始终缺少标签")
    await async_db_session.commit()

    payload = json.dumps(
        {
            "note": {"content": note.content, "person_refs": [], "tags": []},
            "persons": [],
            "tags": [],
            "visions": [],
            "tasks": [],
            "habits": [],
            "confidence": 0.3,
            "uncertainties": [],
        }
    )

    response = _mock_response(payload)

    async def fake_completion(*args, **kwargs):
        return response

    monkeypatch.setattr(llm_client, "completion", fake_completion)

    with pytest.raises(NoteIngestExtractionError):
        await note_ingest_extractor.extract(
            async_db_session,
            user_id=user.id,
            note_id=note.id,
        )


async def test_extractor_handles_structured_payload_without_content(
    async_db_session, monkeypatch
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    note = await _create_note(async_db_session, user, content="解析 structured payload")
    await async_db_session.commit()

    payload = {
        "note": {
            "content": note.content,
            "person_refs": [],
            "tags": ["结构化"],
        },
        "persons": [],
        "tags": [],
        "visions": [],
        "tasks": [],
        "habits": [],
        "confidence": 0.9,
        "uncertainties": [],
    }

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=None, parsed=payload))
        ],
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    )

    async def fake_completion(*args, **kwargs):
        return response

    monkeypatch.setattr(llm_client, "completion", fake_completion)

    result = await note_ingest_extractor.extract(
        async_db_session,
        user_id=user.id,
        note_id=note.id,
    )

    assert result.extraction.note.tags == ["结构化"]


async def test_extractor_retries_transport_timeout_then_succeeds(
    async_db_session, monkeypatch
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    note = await _create_note(async_db_session, user, content="触发网络超时后重试")
    await async_db_session.commit()

    successful_response = _mock_response(
        json.dumps(
            {
                "note": {"content": note.content, "person_refs": [], "tags": ["网络"]},
                "persons": [],
                "tags": [],
                "visions": [],
                "tasks": [],
                "habits": [],
                "confidence": 0.7,
                "uncertainties": [],
            }
        )
    )

    attempts = {"count": 0}

    async def flaky_completion(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise litellm_exceptions.Timeout(
                "LLM request timed out", model="gpt-4o", llm_provider="openai"
            )
        return successful_response

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(llm_client, "completion", flaky_completion)
    monkeypatch.setattr("app.services.note_ingest_extractor.asyncio.sleep", fake_sleep)

    result = await note_ingest_extractor.extract(
        async_db_session,
        user_id=user.id,
        note_id=note.id,
    )

    assert result.extraction.note.tags == ["网络"]
    assert attempts["count"] == 2
    assert sleep_calls == [
        pytest.approx(note_ingest_extractor._NETWORK_RETRY_BASE_DELAY_SECONDS)
    ]


async def test_extractor_raises_after_transport_retries_exhausted(
    async_db_session, monkeypatch
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    note = await _create_note(async_db_session, user, content="持续网络超时")
    await async_db_session.commit()

    attempts = {"count": 0}

    async def always_timeout(*args, **kwargs):
        attempts["count"] += 1
        raise asyncio.TimeoutError("upstream timeout")

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(llm_client, "completion", always_timeout)
    monkeypatch.setattr("app.services.note_ingest_extractor.asyncio.sleep", fake_sleep)

    with pytest.raises(NoteIngestExtractionError) as excinfo:
        await note_ingest_extractor.extract(
            async_db_session,
            user_id=user.id,
            note_id=note.id,
        )

    assert attempts["count"] == note_ingest_extractor._NETWORK_RETRY_ATTEMPTS + 1
    expected_delays = [
        note_ingest_extractor._NETWORK_RETRY_BASE_DELAY_SECONDS,
        min(
            note_ingest_extractor._NETWORK_RETRY_BASE_DELAY_SECONDS * 2,
            note_ingest_extractor._NETWORK_RETRY_BASE_DELAY_SECONDS
            * note_ingest_extractor._NETWORK_RETRY_ATTEMPTS,
        ),
    ]
    assert len(sleep_calls) == len(expected_delays)
    for recorded, expected in zip(sleep_calls, expected_delays):
        assert recorded == pytest.approx(expected)
    assert "transport" in str(excinfo.value)
