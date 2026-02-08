from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID, uuid4

import pytest

from app.agents.context_builder import ContextBuildResult
from app.agents.conversation_history import ConversationMessage
from app.agents.services import context_pipeline as pipeline_module
from app.agents.services.context_pipeline import (
    MAX_CONTEXT_CARDS_PER_BOX,
    ContextPipeline,
)


class StubConversationHistoryService:
    def __init__(
        self,
        *,
        result: Tuple[List[ConversationMessage], str] | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._result = result or ([], "database")
        self._exc = exc
        self.calls: List[Tuple[Any, UUID, Optional[UUID], int]] = []

    async def get_recent_history(
        self,
        db,
        *,
        user_id: UUID,
        session_id: Optional[UUID],
        limit: int,
    ) -> Tuple[List[ConversationMessage], str]:
        self.calls.append((db, user_id, session_id, limit))
        if self._exc:
            raise self._exc
        return self._result


class StubContextSource:
    def __init__(self, selection: Iterable[Dict[str, Any]] | None = None) -> None:
        self._selection = list(selection or [])
        self.calls: List[Tuple[UUID, Optional[UUID]]] = []

    async def load_selection(
        self,
        db,
        *,
        user_id: UUID,
        session_id: Optional[UUID],
    ) -> List[Dict[str, Any]]:
        self.calls.append((user_id, session_id))
        return list(self._selection)


class StubBoxRecord:
    def __init__(self, *, box_id: int, name: str, module: str) -> None:
        self.box_id = box_id
        self.name = name
        self.module = module


class StubBoxManager:
    def __init__(
        self,
        *,
        records: Dict[Tuple[UUID, int], StubBoxRecord] | None = None,
        cards: Dict[Tuple[UUID, str], List[Any]] | None = None,
    ) -> None:
        self._records = records or {}
        self._cards = cards or {}
        self.load_requests: List[Tuple[UUID, str, bool, int]] = []

    def get_record_by_id(
        self, *, user_id: UUID, box_id: int
    ) -> Optional[StubBoxRecord]:
        return self._records.get((user_id, box_id))

    def get_record_by_name(self, *, user_id: UUID, box_name: str):
        # Interface completeness for ContextPipeline callers, unused in tests.
        return self._records.get((user_id, box_name))  # pragma: no cover

    def load_box_cards(
        self,
        *,
        user_id: UUID,
        box_name: str,
        skip_manifest: bool,
        limit: int,
    ) -> List[Any]:
        self.load_requests.append((user_id, box_name, skip_manifest, limit))
        return list(self._cards.get((user_id, box_name), []))[:limit]


class DummyCard:
    def __init__(
        self, *, card_id: str, text_value: str, metadata: Dict[str, Any]
    ) -> None:
        self.card_id = card_id
        self._text = text_value
        self.metadata = metadata

    def text(self) -> str:
        return self._text


def _build_pipeline(
    *,
    history_service: StubConversationHistoryService | None = None,
    context_source: StubContextSource | None = None,
    box_manager: StubBoxManager | None = None,
) -> ContextPipeline:
    return ContextPipeline(
        history_service=history_service or StubConversationHistoryService(),
        context_source=context_source or StubContextSource(),
        box_manager=box_manager or StubBoxManager(),
    )


@pytest.mark.asyncio
async def test_get_conversation_history_delegates_to_service() -> None:
    user_id = uuid4()
    session_id = uuid4()
    history = [
        ConversationMessage(
            role="assistant",
            content="hello",
            created_at=datetime.now(timezone.utc),
            source="db",
        )
    ]
    history_service = StubConversationHistoryService(result=(history, "database"))
    pipeline = _build_pipeline(history_service=history_service)

    result, source = await pipeline.get_conversation_history(
        db=None,
        user_id=user_id,
        session_id=session_id,
        limit=5,
    )

    assert result == history
    assert source == "database"
    assert history_service.calls == [(None, user_id, session_id, 5)]


@pytest.mark.asyncio
async def test_get_conversation_history_handles_errors() -> None:
    user_id = uuid4()
    session_id = uuid4()
    history_service = StubConversationHistoryService(exc=RuntimeError("boom"))
    pipeline = _build_pipeline(history_service=history_service)

    result, source = await pipeline.get_conversation_history(
        db=None,
        user_id=user_id,
        session_id=session_id,
        limit=1,
    )

    assert result == []
    assert source == "error"


@pytest.mark.asyncio
async def test_load_session_context_messages_orders_records() -> None:
    user_id = uuid4()
    session_id = uuid4()
    selection = [{"box_id": 2, "order": 2}, {"box_id": 1, "order": 1}]
    context_source = StubContextSource(selection)

    record_alpha = StubBoxRecord(box_id=1, name="alpha", module="unknown")
    record_beta = StubBoxRecord(box_id=2, name="beta", module="visions")
    cards = {
        (user_id, "alpha"): [
            DummyCard(
                card_id="1",
                text_value="alpha-first",
                metadata={
                    "role": "system",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            ),
        ],
        (user_id, "beta"): [
            DummyCard(
                card_id="2",
                text_value="beta-first",
                metadata={
                    "role": "assistant",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            ),
        ],
    }
    records = {
        (user_id, 1): record_alpha,
        (user_id, 2): record_beta,
    }
    box_manager = StubBoxManager(records=records, cards=cards)
    pipeline = _build_pipeline(context_source=context_source, box_manager=box_manager)

    messages, summaries = await pipeline.load_session_context_messages(
        db=None,
        user_id=user_id,
        session_id=session_id,
    )

    assert [message.content for message in messages] == ["alpha-first", "beta-first"]
    assert [summary["box_id"] for summary in summaries] == [1, 2]
    assert [request[3] for request in box_manager.load_requests] == [
        MAX_CONTEXT_CARDS_PER_BOX,
        MAX_CONTEXT_CARDS_PER_BOX,
    ]


@pytest.mark.asyncio
async def test_load_session_context_messages_skips_missing_records() -> None:
    user_id = uuid4()
    session_id = uuid4()
    context_source = StubContextSource(selection=[{"box_id": 42, "order": 1}])
    pipeline = _build_pipeline(context_source=context_source)

    messages, summaries = await pipeline.load_session_context_messages(
        db=None,
        user_id=user_id,
        session_id=session_id,
    )

    assert messages == []
    assert summaries == []


def test_append_context_usage_log_adds_card(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = _build_pipeline()
    captured: Dict[str, Any] = {}

    def fake_ensure_session_box(session):
        captured["session"] = session
        return "session-box"

    def fake_add_cards(tenant_id, box_name, cards):
        captured["tenant_id"] = tenant_id
        captured["box_name"] = box_name
        captured["cards"] = cards

    monkeypatch.setattr(
        pipeline_module,
        "cardbox_service",
        SimpleNamespace(
            ensure_session_box=fake_ensure_session_box,
            add_cards=fake_add_cards,
        ),
    )

    summaries = [{"box_id": 1, "name": "alpha", "module": "notes", "order": 0}]
    pipeline.append_context_usage_log(
        session="db-session",
        tenant_id="tenant",
        user_id=uuid4(),
        summaries=summaries,
    )

    assert captured["session"] == "db-session"
    assert captured["tenant_id"] == "tenant"
    assert captured["box_name"] == "session-box"
    assert len(captured["cards"]) == 1
    card = captured["cards"][0]
    assert card.metadata["type"] == "context_usage"
    assert card.metadata["boxes"] == summaries


def test_log_context_truncation_warns_when_cards_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pipeline = _build_pipeline()
    now = datetime.now(timezone.utc)
    dropped_messages = [
        ConversationMessage(
            role="assistant",
            content="trimmed",
            created_at=now,
            source="context_box",
            message_id="card-1",
            metadata={"card_id": "card-1"},
        ),
        ConversationMessage(
            role="assistant",
            content="kept",
            created_at=now,
            source="other",
        ),
    ]
    context_result = ContextBuildResult(
        messages=[],
        selected_history=[],
        dropped_history=dropped_messages,
        token_usage={"history_tokens": 10},
    )

    with caplog.at_level("WARNING"):
        pipeline.log_context_truncation(
            user_id=uuid4(),
            session_id=uuid4(),
            context_result=context_result,
        )

    assert "context trimming dropped" in caplog.text
