import sqlite3

import pytest
from sqlalchemy import event
from sqlalchemy.pool import QueuePool

from app.core.config import settings
from app.runtime.ops_metrics import ops_metrics
from app.runtime.ops_metrics_refresh import refresh_db_pool_checked_out


def test_refresh_db_pool_checked_out_sets_live_value() -> None:
    class _FakePool:
        def checkedout(self) -> int:
            return 3

    ops_metrics.set_db_pool_checked_out(0)

    refreshed = refresh_db_pool_checked_out(_FakePool())

    assert refreshed == 3
    assert ops_metrics.snapshot()["db_pool_checked_out"] == 3


def test_refresh_db_pool_checked_out_skips_pools_without_checkedout() -> None:
    class _PoolWithoutCheckedOut:
        pass

    ops_metrics.set_db_pool_checked_out(4)

    refreshed = refresh_db_pool_checked_out(_PoolWithoutCheckedOut())

    assert refreshed is None
    assert ops_metrics.snapshot()["db_pool_checked_out"] == 4


def test_db_pool_metric_handlers_track_checkout_and_checkin_only() -> None:
    from app.db import session as session_module

    ops_metrics.set_db_pool_checked_out(0)

    session_module._pool_checkout()
    session_module._pool_checkin()

    assert ops_metrics.snapshot()["db_pool_checked_out"] == 0
    assert not hasattr(session_module, "_pool_close")
    assert not hasattr(session_module, "_pool_invalidate")


def test_db_pool_metric_handlers_do_not_double_decrement_after_invalidate() -> None:
    from app.db import session as session_module

    pool = QueuePool(lambda: sqlite3.connect(":memory:"))
    event.listen(pool, "checkout", session_module._pool_checkout)
    event.listen(pool, "checkin", session_module._pool_checkin)

    ops_metrics.set_db_pool_checked_out(0)

    try:
        connection = pool.connect()
        assert ops_metrics.snapshot()["db_pool_checked_out"] == 1

        connection.invalidate()
        connection.close()

        assert ops_metrics.snapshot()["db_pool_checked_out"] == 0
    finally:
        event.remove(pool, "checkout", session_module._pool_checkout)
        event.remove(pool, "checkin", session_module._pool_checkin)
        pool.dispose()


def test_db_pool_metric_handlers_record_long_hold_source_and_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db import session as session_module

    class _FakeConnectionRecord:
        def __init__(self) -> None:
            self.info: dict[str, object] = {}

    record = _FakeConnectionRecord()
    counters = iter([10.0, 10.9])

    ops_metrics.set_db_pool_checked_out(0)
    ops_metrics.reset_db_connection_hold_metrics()
    monkeypatch.setattr(settings, "async_db_connection_hold_warn_ms", 500.0)
    monkeypatch.setattr(
        session_module,
        "_capture_db_checkout_source",
        lambda: "app/features/example.py:12:load_runtime",
    )
    monkeypatch.setattr(session_module.time, "perf_counter", lambda: next(counters))

    session_module._pool_checkout(None, record)
    session_module._pool_checkin(None, record)

    snapshot = ops_metrics.snapshot()["db_connection_hold"]
    assert ops_metrics.snapshot()["db_pool_checked_out"] == 0
    assert snapshot["count"] == 1
    assert snapshot["last_ms"] == 900.0
    assert snapshot["long_hold_count"] == 1
    assert (
        snapshot["last_long_hold_source"] == "app/features/example.py:12:load_runtime"
    )
    assert snapshot["longest_hold_source"] == "app/features/example.py:12:load_runtime"
