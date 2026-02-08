from __future__ import annotations

import pytest

from app.db.transaction import commit_safely, rollback_safely

pytestmark = pytest.mark.unit


class DummyAsyncSession:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True
        if self.should_fail:
            raise ValueError("commit failed")

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.mark.asyncio
async def test_commit_safely_success() -> None:
    session = DummyAsyncSession()
    await commit_safely(session)
    assert session.committed is True
    assert session.rolled_back is False


@pytest.mark.asyncio
async def test_commit_safely_rolls_back_on_error() -> None:
    session = DummyAsyncSession(should_fail=True)
    with pytest.raises(ValueError):
        await commit_safely(session)

    assert session.committed is True
    assert session.rolled_back is True


@pytest.mark.asyncio
async def test_rollback_safely_swallows_errors() -> None:
    class FailingAsyncRollbackSession(DummyAsyncSession):
        async def rollback(self) -> None:  # type: ignore[override]
            await super().rollback()
            raise RuntimeError("rollback failed")

    session = FailingAsyncRollbackSession(should_fail=True)
    with pytest.raises(ValueError):
        await commit_safely(session)

    # Explicit rollback helper should swallow secondary errors
    await rollback_safely(session)
