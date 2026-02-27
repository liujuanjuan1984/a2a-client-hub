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


def test_daily_schedule_resolves_nonexistent_local_time_in_dst_gap() -> None:
    next_run_at = a2a_schedule_service.compute_next_run_at(
        cycle_type="daily",
        time_point={"time": "02:30"},
        timezone_str="America/New_York",
        after_utc=datetime(2026, 3, 8, 5, 0, tzinfo=timezone.utc),
    )

    assert next_run_at == datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc)
    local = next_run_at.astimezone(ZoneInfo("America/New_York"))
    assert (local.hour, local.minute) == (3, 30)


def test_daily_schedule_picks_first_occurrence_for_ambiguous_local_time() -> None:
    next_run_at = a2a_schedule_service.compute_next_run_at(
        cycle_type="daily",
        time_point={"time": "01:30"},
        timezone_str="America/New_York",
        after_utc=datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc),
    )

    assert next_run_at == datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
    local = next_run_at.astimezone(ZoneInfo("America/New_York"))
    assert (local.hour, local.minute) == (1, 30)
    assert local.fold == 0


def test_daily_schedule_respects_not_before_during_fall_back_overlap() -> None:
    next_run_at = a2a_schedule_service.compute_next_run_at(
        cycle_type="daily",
        time_point={"time": "01:30"},
        timezone_str="America/New_York",
        after_utc=datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc),
        not_before_utc=datetime(2026, 11, 1, 6, 10, tzinfo=timezone.utc),
    )

    # 2026-11-01 01:30 occurs twice in NY. With fold=0 policy, the first
    # occurrence (05:30 UTC) is considered passed once not_before is 06:10 UTC.
    # The next valid trigger is the next day at 01:30 local (EST, 06:30 UTC).
    assert next_run_at == datetime(2026, 11, 2, 6, 30, tzinfo=timezone.utc)
