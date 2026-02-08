"""
Recurring Events Utility Module

This module provides functionality for handling recurring events using RRULE strings
according to RFC 5545 (iCalendar specification).

It uses python-dateutil library for parsing and computing recurring event instances.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import NAMESPACE_URL, UUID, uuid5

from dateutil.rrule import rrulestr
from pydantic import BaseModel

from app.core.logging import get_logger
from app.schemas.planned_event import PlannedEventResponse

logger = get_logger(__name__)


def compute_instance_id(master_event_id: UUID, occurrence_start: datetime) -> UUID:
    """Return the deterministic UUID for a recurring occurrence."""

    return uuid5(NAMESPACE_URL, f"{master_event_id}:{occurrence_start.isoformat()}")


@dataclass
class RecurringEventExceptionBundle:
    """Container for recurrence exceptions such as skips or truncations."""

    skip_instance_ids: Set[UUID] = field(default_factory=set)
    skip_instance_starts: Set[datetime] = field(default_factory=set)
    truncate_after: Optional[datetime] = None
    override_payloads_by_instance_id: Dict[UUID, Dict[str, Any]] = field(
        default_factory=dict
    )
    override_payloads_by_instance_start: Dict[datetime, Dict[str, Any]] = field(
        default_factory=dict
    )


def _parse_datetime_payload(value: Any) -> Any:
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return value
    return value


def _apply_override_payload(
    event_dict: Dict[str, Any], payload: Dict[str, Any]
) -> None:
    for key, value in payload.items():
        if key in {"start_time", "end_time"} and value is not None:
            event_dict[key] = _parse_datetime_payload(value)
        else:
            event_dict[key] = value


RecurringExceptionMap = Dict[UUID, RecurringEventExceptionBundle]


class RecurringEventInstance(BaseModel):
    """
    Represents a single instance of a recurring event

    This is a computed instance with specific start/end times derived from
    the master event and its recurrence rule.
    """

    # Inherit all fields from the master event
    id: UUID
    title: str
    start_time: datetime
    end_time: Optional[datetime] = None
    priority: int = 0
    is_all_day: bool = False
    is_recurring: bool = True  # Always True for instances
    recurrence_pattern: Optional[dict] = None
    rrule_string: Optional[str] = None
    status: str = "planned"
    tags: Optional[List[str]] = None
    extra_data: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    # Additional fields for instance metadata
    is_instance: bool = True  # Flag to identify this as a computed instance
    master_event_id: UUID  # Reference to the original master event
    instance_id: UUID  # Stable identifier for this specific occurrence


def generate_recurring_instances(
    master_event: PlannedEventResponse, start_range: datetime, end_range: datetime
) -> List[RecurringEventInstance]:
    """
    Generate recurring event instances for a master event within a time range

    This function takes a master event with an RRULE string and generates all
    occurrences that fall within the specified time range.

    Args:
        master_event: The master planned event with recurrence rules
        start_range: Start of the time range to generate instances for
        end_range: End of the time range to generate instances for

    Returns:
        List of recurring event instances within the specified range

    Raises:
        ValueError: If the RRULE string is invalid or malformed
    """
    if not master_event.rrule_string:
        return []

    try:
        # Parse the RRULE string using dateutil
        # The dtstart parameter sets the start date for the recurrence rule
        rule = rrulestr(master_event.rrule_string, dtstart=master_event.start_time)

        # Calculate the duration of the master event; keep zero-length events
        duration: Optional[timedelta] = None
        if master_event.end_time is not None:
            candidate_duration = master_event.end_time - master_event.start_time
            if candidate_duration.total_seconds() >= 0:
                duration = candidate_duration

        # Generate occurrences within the specified range
        # Use between() method to get occurrences in the time range
        occurrences = rule.between(start_range, end_range, inc=True)

        instances = []
        for occurrence_start in occurrences:
            # Calculate the end time for this instance
            occurrence_end = (
                occurrence_start + duration if duration is not None else None
            )

            # Create a new instance based on the master event
            instance_uuid = compute_instance_id(master_event.id, occurrence_start)

            instance = RecurringEventInstance(
                id=master_event.id,  # Keep same ID for now (may need different strategy)
                title=master_event.title,
                start_time=occurrence_start,
                end_time=occurrence_end,
                priority=master_event.priority,
                is_all_day=master_event.is_all_day,
                is_recurring=True,
                recurrence_pattern=master_event.recurrence_pattern,
                rrule_string=master_event.rrule_string,
                status=master_event.status,
                tags=master_event.tags,
                extra_data=master_event.extra_data,
                created_at=master_event.created_at,
                updated_at=master_event.updated_at,
                is_instance=True,
                master_event_id=master_event.id,
                instance_id=instance_uuid,
            )
            instances.append(instance)

        return instances

    except Exception as e:
        logger.error("Error generating recurring instances: %s", e)
        return []


PADDING_DAYS_FOR_RECURRING = 1


def expand_planned_events_with_recurrence(
    events: List[PlannedEventResponse],
    start_range: datetime,
    end_range: datetime,
    exceptions: Optional[RecurringExceptionMap] = None,
) -> List[dict]:
    """
    Expand a list of planned events to include recurring instances

    This function processes a list of planned events and:
    1. Returns non-recurring events as-is (if they fall in the time range)
    2. Generates and returns recurring instances for recurring events

    Args:
        events: List of planned events from the database
        start_range: Start of the time range to expand events for
        end_range: End of the time range to expand events for

    Returns:
        List of events (mix of original events and computed instances) as dictionaries
    """
    expanded_events = []
    exception_map = exceptions or {}

    for event in events:
        if event.rrule_string:
            bundle = exception_map.get(event.id)
            padding = timedelta(days=PADDING_DAYS_FOR_RECURRING)
            generation_start = start_range - padding
            generation_end = end_range + padding
            if bundle and bundle.truncate_after is not None:
                generation_end = min(generation_end, bundle.truncate_after)

            # This is a recurring event - generate instances
            instances = generate_recurring_instances(
                event, generation_start, generation_end
            )
            # Convert instances to dictionaries for API response
            for instance in instances:
                instance_end = instance.end_time or instance.start_time
                if not (instance.start_time < end_range and instance_end > start_range):
                    continue
                if bundle:
                    if (
                        bundle.skip_instance_ids
                        and instance.instance_id in bundle.skip_instance_ids
                    ):
                        continue
                    if (
                        bundle.skip_instance_starts
                        and instance.start_time in bundle.skip_instance_starts
                    ):
                        continue
                    if (
                        bundle.truncate_after
                        and instance.start_time >= bundle.truncate_after
                    ):
                        continue
                instance_dict = instance.model_dump()
                if bundle:
                    override_payload = bundle.override_payloads_by_instance_id.get(
                        instance.instance_id
                    ) or bundle.override_payloads_by_instance_start.get(
                        instance.start_time
                    )
                    if override_payload:
                        _apply_override_payload(instance_dict, override_payload)
                expanded_events.append(instance_dict)
        else:
            # Non-recurring event - include if it falls within the range
            event_start = event.start_time
            event_end = event.end_time or event_start

            # Check if the event overlaps with the requested range
            if event_start <= end_range and event_end >= start_range:
                # Convert to dict and add instance metadata
                event_dict = event.model_dump()
                event_dict["is_instance"] = False
                event_dict["master_event_id"] = event.id
                expanded_events.append(event_dict)

    return expanded_events


def infer_rrule_series_end(
    start_time: datetime, rrule_string: Optional[str]
) -> Optional[datetime]:
    """
    Infer the upper bound of a recurrence series based on its RRULE.

    Returns UTC-aware datetime of the last possible occurrence if the series
    is finite (via UNTIL or COUNT). Otherwise returns None.
    """

    if not rrule_string:
        return None

    try:
        rule = rrulestr(rrule_string, dtstart=start_time)
    except Exception:
        return None

    until = getattr(rule, "_until", None)
    if until is not None:
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return until

    count = getattr(rule, "_count", None)
    if count:
        try:
            last = rule[count - 1]
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            return last
        except Exception:
            return None

    return None
