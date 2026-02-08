from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.schemas.planned_event import PlannedEventResponse
from app.utils.recurring_events import (
    RecurringEventExceptionBundle,
    compute_instance_id,
    expand_planned_events_with_recurrence,
    generate_recurring_instances,
    infer_rrule_series_end,
)


def _build_master_event(**overrides) -> PlannedEventResponse:
    start_time = overrides.get(
        "start_time", datetime(2025, 12, 29, 12, 30, tzinfo=timezone.utc)
    )
    base = {
        "id": uuid4(),
        "title": overrides.get("title", "Recurring Test"),
        "start_time": start_time,
        "end_time": overrides.get("end_time", start_time + timedelta(minutes=30)),
        "priority": 0,
        "dimension_id": None,
        "task_id": None,
        "is_all_day": False,
        "is_recurring": True,
        "recurrence_pattern": None,
        "rrule_string": overrides.get("rrule_string", "FREQ=DAILY"),
        "status": "planned",
        "tags": [],
        "extra_data": None,
        "created_at": overrides.get("created_at", start_time),
        "updated_at": overrides.get("updated_at", start_time),
        "persons": [],
    }
    base.update(overrides)
    return PlannedEventResponse(**base)


def test_generate_recurring_instances_keeps_zero_duration_end_time():
    start_time = datetime(2025, 12, 29, 12, 30, tzinfo=timezone.utc)
    master = _build_master_event(start_time=start_time, end_time=start_time)

    start_range = start_time - timedelta(hours=1)
    end_range = start_time + timedelta(days=1)

    instances = generate_recurring_instances(master, start_range, end_range)

    assert instances, "Expected at least one recurring instance"
    first = instances[0]
    assert first.start_time == start_time
    assert first.end_time == start_time, "Zero-duration events must retain end_time"


def test_generate_recurring_instances_preserves_positive_duration():
    start_time = datetime(2025, 12, 29, 12, 30, tzinfo=timezone.utc)
    end_time = start_time + timedelta(minutes=30)
    master = _build_master_event(start_time=start_time, end_time=end_time)

    start_range = start_time - timedelta(hours=1)
    end_range = start_time + timedelta(days=1, hours=1)

    instances = generate_recurring_instances(master, start_range, end_range)

    assert instances, "Expected recurring instances for positive duration"
    first = instances[0]
    assert first.start_time == start_time
    assert first.end_time == end_time


def test_expand_events_respects_skip_exception():
    start_time = datetime(2025, 12, 25, 8, 0, tzinfo=timezone.utc)
    master = _build_master_event(
        start_time=start_time,
        end_time=start_time + timedelta(minutes=30),
        rrule_string="FREQ=DAILY",
    )
    start_range = start_time - timedelta(hours=1)
    end_range = start_time + timedelta(days=2)
    skip_bundle = RecurringEventExceptionBundle()
    skip_bundle.skip_instance_ids.add(compute_instance_id(master.id, start_time))
    exceptions = {master.id: skip_bundle}

    expanded = expand_planned_events_with_recurrence(
        [master], start_range, end_range, exceptions=exceptions
    )

    assert expanded, "Expected expanded instances even with skip"
    assert all(item["start_time"] != start_time for item in expanded)


def test_expand_events_respects_truncate_exception():
    start_time = datetime(2025, 12, 1, 6, 0, tzinfo=timezone.utc)
    master = _build_master_event(
        start_time=start_time,
        end_time=start_time + timedelta(minutes=45),
        rrule_string="FREQ=DAILY",
    )
    start_range = start_time
    end_range = start_time + timedelta(days=5)
    truncate_after = start_time + timedelta(days=2)
    bundle = RecurringEventExceptionBundle(truncate_after=truncate_after)

    expanded = expand_planned_events_with_recurrence(
        [master], start_range, end_range, exceptions={master.id: bundle}
    )

    assert expanded, "Expected expanded events before truncate boundary"
    assert all(item["start_time"] < truncate_after for item in expanded)


def test_expand_events_includes_cross_day_overlap():
    start_time = datetime(2025, 12, 30, 22, 0, tzinfo=timezone.utc)
    end_time = datetime(2025, 12, 31, 6, 0, tzinfo=timezone.utc)
    master = _build_master_event(
        start_time=start_time,
        end_time=end_time,
        rrule_string="FREQ=DAILY",
    )

    start_range = datetime(2025, 12, 31, 0, 0, tzinfo=timezone.utc)
    end_range = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

    expanded = expand_planned_events_with_recurrence([master], start_range, end_range)

    assert expanded, "Cross-day instance should be returned for overlapping day"
    assert any(item["start_time"] == start_time for item in expanded)


def test_infer_rrule_series_end_uses_until():
    start_time = datetime(2025, 12, 1, 8, 0, tzinfo=timezone.utc)
    until_str = "20251205T080000Z"
    rrule = f"FREQ=DAILY;UNTIL={until_str}"

    inferred = infer_rrule_series_end(start_time, rrule)

    assert inferred == datetime(2025, 12, 5, 8, 0, tzinfo=timezone.utc)


def test_infer_rrule_series_end_uses_count():
    start_time = datetime(2025, 12, 1, 8, 0, tzinfo=timezone.utc)
    rrule = "FREQ=DAILY;COUNT=3"

    inferred = infer_rrule_series_end(start_time, rrule)

    assert inferred == datetime(2025, 12, 3, 8, 0, tzinfo=timezone.utc)
