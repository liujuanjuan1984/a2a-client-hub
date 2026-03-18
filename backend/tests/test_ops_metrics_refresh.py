from app.services.ops_metrics import ops_metrics
from app.services.ops_metrics_refresh import refresh_db_pool_checked_out


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
