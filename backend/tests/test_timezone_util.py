from datetime import datetime, timezone

from app.utils import timezone_util as tz_util


def test_utc_now_and_today_are_utc():
    now = tz_util.utc_now()
    assert now.tzinfo == timezone.utc
    today = tz_util.utc_today()
    assert today == now.date()


def test_ensure_utc_handles_naive_and_aware():
    naive = datetime(2025, 1, 1, 12, 0, 0)
    aware = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    assert tz_util.ensure_utc(naive).tzinfo == timezone.utc
    assert tz_util.ensure_utc(aware) == aware


def test_resolve_timezone_falls_back_to_default():
    tz = tz_util.resolve_timezone("Asia/Shanghai")
    assert tz.key == "Asia/Shanghai"

    fallback = tz_util.resolve_timezone("Not/AZone", default="UTC")
    assert fallback.key == "UTC"
