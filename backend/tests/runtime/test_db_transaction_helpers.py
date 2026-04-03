from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from app.db import transaction as transaction_module


class _FakeSession:
    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0
        self.in_transaction_value = True
        self.new: list[object] = []
        self.dirty: list[object] = []
        self.deleted: list[object] = []

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1

    def in_transaction(self) -> bool:
        return self.in_transaction_value


@asynccontextmanager
async def _session_factory(session: _FakeSession) -> AsyncIterator[_FakeSession]:
    yield session


@pytest.mark.asyncio
async def test_load_for_external_call_runs_loader_and_closes_read_only_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    session = _FakeSession()

    async def fake_prepare_for_external_call(db) -> None:
        assert db is session
        calls.append("prepare")

    async def loader(db):
        assert db is session
        calls.append("load")
        return {"ok": True}

    monkeypatch.setattr(
        transaction_module,
        "prepare_for_external_call",
        fake_prepare_for_external_call,
    )

    result = await transaction_module.load_for_external_call(session, loader)

    assert result == {"ok": True}
    assert calls == ["load", "prepare"]


@pytest.mark.asyncio
async def test_run_in_write_session_commits_on_success() -> None:
    session = _FakeSession()

    async def operation(db: _FakeSession) -> str:
        assert db is session
        return "done"

    result = await transaction_module.run_in_write_session(
        operation,
        session_factory=lambda: _session_factory(session),
    )

    assert result == "done"
    assert session.committed == 1
    assert session.rolled_back == 0


@pytest.mark.asyncio
async def test_run_in_write_session_rolls_back_on_failure() -> None:
    session = _FakeSession()

    async def operation(db: _FakeSession) -> None:
        assert db is session
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await transaction_module.run_in_write_session(
            operation,
            session_factory=lambda: _session_factory(session),
        )

    assert session.committed == 0
    assert session.rolled_back == 1
