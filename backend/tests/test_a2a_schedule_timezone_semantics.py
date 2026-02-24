from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services.a2a_schedule_service import a2a_schedule_service


@pytest.mark.parametrize(
    ("after_utc", "expected_utc"),
    [
        (
            datetime(2026, 3, 7, 12, 30, tzinfo=timezone.utc),
            datetime(2026, 3, 7, 13, 0, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 3, 8, 12, 30, tzinfo=timezone.utc),
            datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 10, 31, 11, 30, tzinfo=timezone.utc),
            datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 11, 1, 12, 30, tzinfo=timezone.utc),
            datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc),
        ),
    ],
)
def test_daily_schedule_preserves_eight_am_across_dst(
    after_utc: datetime,
    expected_utc: datetime,
) -> None:
    next_run_at = a2a_schedule_service.compute_next_run_at(
        cycle_type="daily",
        time_point={"time": "08:00"},
        timezone_str="America/New_York",
        after_utc=after_utc,
    )

    assert next_run_at == expected_utc

    local = next_run_at.astimezone(ZoneInfo("America/New_York"))
    assert (local.hour, local.minute) == (8, 0)
