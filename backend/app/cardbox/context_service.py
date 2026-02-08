"""Helpers for generating user-defined context CardBoxes."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo

from card_box_core.structures import Card, TextContent
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cardbox.async_bridge import run_cardbox_io
from app.cardbox.service import cardbox_service
from app.cardbox.utils import tenant_for_user
from app.core.logging import get_logger
from app.db.models.task import Task
from app.db.models.vision import Vision
from app.handlers import notes as note_service
from app.handlers import user_preferences as user_preferences_service
from app.handlers.actual_events import (
    DEFAULT_MAX_SEARCH_DAYS,
    DEFAULT_MAX_SEARCH_RESULTS,
    search_actual_events,
)
from app.handlers.associations import LinkType, ModelName
from app.handlers.associations_async import attach_persons_for_sources
from app.handlers.dimensions import get_dimension
from app.handlers.tasks import list_tasks
from app.serialization.entities import build_task_summary
from app.utils.json_encoder import json_dumps
from app.utils.timezone_util import resolve_timezone, utc_now

logger = get_logger(__name__)

MODULE_ACTUAL_EVENT = "actual_event"
MODULE_NOTES = "notes"
MODULE_VISION_TASKS = "vision_tasks"  # legacy support
MODULE_PLANNING_TASKS = "planning_tasks"
MODULE_VISION_PROGRESS = "vision_progress"

LEGACY_MODULE_ALIASES = {
    "timelog": MODULE_ACTUAL_EVENT,
}

MODULE_LABELS = {
    MODULE_ACTUAL_EVENT: "Timelog",
    MODULE_NOTES: "Notes",
    MODULE_VISION_TASKS: "Vision & Tasks",
    MODULE_PLANNING_TASKS: "Planning Tasks",
    MODULE_VISION_PROGRESS: "Vision Progress",
}

DEFAULT_LIMITS = {
    MODULE_ACTUAL_EVENT: 500,
    MODULE_NOTES: 50,
    MODULE_VISION_TASKS: 10,
    MODULE_PLANNING_TASKS: 200,
    MODULE_VISION_PROGRESS: 20,
}

MANIFEST_TYPE = "context_manifest"
ENTRY_TYPE = "context_entry"
USAGE_TYPE = "context_usage"

ACTUAL_EVENT_CARD_ENTRY_LIMIT = 50
DEFAULT_TIMEZONE = "UTC"


async def _list_notes_for_context(
    db: AsyncSession,
    *,
    user_id: UUID,
    limit: int,
    offset: int = 0,
    tag_id: Optional[UUID] = None,
    person_id: Optional[UUID] = None,
    task_id: Optional[UUID] = None,
    keyword: Optional[str] = None,
    untagged: Optional[bool] = None,
) -> List[Any]:
    """Fetch notes via async handler and hydrate associations."""

    notes = await note_service.list_notes(
        db,
        user_id=user_id,
        limit=limit,
        offset=offset,
        tag_id=tag_id,
        person_id=person_id,
        task_id=task_id,
        keyword=keyword,
        untagged=untagged,
    )
    if not notes:
        return []
    associations = await note_service.get_notes_with_associations(
        db,
        user_id=user_id,
        notes=notes,
    )
    for note in notes:
        assoc = associations.get(note.id, {})
        persons = assoc.get("persons")
        if persons is not None:
            note.persons = persons  # type: ignore[attr-defined]
        task = assoc.get("task")
        if task is not None:
            note.task = task  # type: ignore[attr-defined]
        timelogs = assoc.get("timelogs")
        if timelogs is not None:
            note.timelogs = timelogs  # type: ignore[attr-defined]
    return notes


@dataclass
class ContextBoxRecord:
    box_id: int
    name: str
    module: str
    display_name: str
    card_count: int
    updated_at: datetime
    manifest_metadata: Dict[str, Any]


async def _list_visions_for_cardbox(
    db: AsyncSession,
    *,
    user_id: UUID,
    limit: int,
    status_filter: Optional[str] = None,
) -> List[Vision]:
    stmt = (
        select(Vision)
        .where(Vision.user_id == user_id, Vision.deleted_at.is_(None))
        .order_by(Vision.created_at.desc())
        .limit(max(limit, 1))
    )
    if status_filter:
        stmt = stmt.where(Vision.status == status_filter)
    visions = (await db.execute(stmt)).scalars().all()
    if not visions:
        return []

    vision_ids = [vision.id for vision in visions]
    totals_stmt = (
        select(Task.vision_id, func.sum(Task.actual_effort_total).label("total"))
        .where(
            Task.user_id == user_id,
            Task.deleted_at.is_(None),
            Task.parent_task_id.is_(None),
            Task.vision_id.in_(vision_ids),
        )
        .group_by(Task.vision_id)
    )
    totals = await db.execute(totals_stmt)
    total_map = {vision_id: int(total or 0) for vision_id, total in totals.all()}
    for vision in visions:
        setattr(vision, "total_actual_effort", total_map.get(vision.id, 0))

    await attach_persons_for_sources(
        db,
        source_model=ModelName.Vision,
        items=visions,
        link_type=LinkType.INVOLVES,
        user_id=user_id,
    )
    return visions


class ContextBoxManager:
    """Coordinate creation and management of context CardBoxes."""

    def __init__(self) -> None:
        self._cardbox_service = cardbox_service

    def _task_summary_payload(
        self,
        task: Any,
        *,
        include_parent: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Convert a Task instance into the shared TaskSummary payload.
        """
        summary_model = build_task_summary(
            task,
            include_parent_summary=include_parent,
        )
        if summary_model is None:
            return None
        return summary_model.model_dump(mode="json", exclude_none=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def create_context_box(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        module: str,
        filters: Dict[str, Any],
        display_name: Optional[str] = None,
        overwrite: bool = True,
    ) -> ContextBoxRecord:
        module_key = self._canonical_module_key(module)
        legacy_source = (module or "").lower() or None
        if legacy_source == module_key:
            legacy_source = None
        if module_key not in MODULE_LABELS:
            raise ValueError(f"Unsupported context module: {module}")

        timestamp = utc_now()
        tenant_id = tenant_for_user(user_id)
        normalized_filters = self._normalise_filters(filters)
        effective_display_name = display_name or self._build_default_display_name(
            module_key, normalized_filters, timestamp
        )
        box_name = self._build_box_name(
            user_id, module_key, effective_display_name, timestamp
        )

        cards: List[Card]
        builder_meta: Dict[str, Any]
        if module_key == MODULE_ACTUAL_EVENT:
            cards, builder_meta = await self._build_timelog_cards(
                db, user_id, normalized_filters
            )
        elif module_key == MODULE_NOTES:
            cards, builder_meta = await self._build_note_cards(
                db, user_id, normalized_filters
            )
        elif module_key == MODULE_PLANNING_TASKS:
            cards, builder_meta = await self._build_planning_task_cards(
                db, user_id, normalized_filters
            )
        elif module_key == MODULE_VISION_PROGRESS:
            cards, builder_meta = await self._build_vision_progress_cards(
                db, user_id, normalized_filters
            )
        else:
            cards, builder_meta = await self._build_vision_task_cards(
                db, user_id, normalized_filters
            )

        if not cards:
            logger.info(
                "create_context_box produced no cards",
                extra={
                    "module": module_key,
                    "filters": normalized_filters,
                    "legacy_module": legacy_source,
                },
            )

        manifest_card = self._build_manifest_card(
            module=module_key,
            box_name=box_name,
            display_name=effective_display_name,
            generated_at=timestamp,
            filters=normalized_filters,
            payload_meta=builder_meta,
            total_cards=len(cards),
            legacy_module=legacy_source,
        )
        ordered_cards = [manifest_card, *cards]

        await run_cardbox_io(
            self._cardbox_service.replace_box,
            tenant_id,
            box_name,
            ordered_cards,
            allow_overwrite=overwrite,
        )

        record = await run_cardbox_io(
            self._fetch_record_by_name,
            tenant_id,
            box_name,
        )
        if record is None:
            raise RuntimeError(f"Failed to persist context CardBox '{box_name}'")
        return record

    def list_context_boxes(self, *, user_id: UUID) -> List[ContextBoxRecord]:
        tenant_id = tenant_for_user(user_id)
        engine, storage, connection = self._get_engine_and_connection(tenant_id)

        rows = connection.execute(
            """
            SELECT box_id, name, card_ids, updated_at
            FROM card_boxes
            WHERE tenant_id = ? AND name LIKE 'context/%'
            ORDER BY updated_at DESC
            """,
            (tenant_id,),
        ).fetchall()

        records: List[ContextBoxRecord] = []
        for row in rows:
            record = self._build_record_from_row(engine, row)
            if record:
                records.append(record)
        return records

    def get_record_by_id(
        self, *, user_id: UUID, box_id: int
    ) -> Optional[ContextBoxRecord]:
        tenant_id = tenant_for_user(user_id)
        return self._fetch_record_by_id(tenant_id, box_id)

    def get_record_by_name(
        self, *, user_id: UUID, name: str
    ) -> Optional[ContextBoxRecord]:
        tenant_id = tenant_for_user(user_id)
        return self._fetch_record_by_name(tenant_id, name)

    def delete_box_by_id(self, *, user_id: UUID, box_id: int) -> bool:
        tenant_id = tenant_for_user(user_id)
        record = self._fetch_record_by_id(tenant_id, box_id)
        if record is None:
            return False
        return self._cardbox_service.delete_box(tenant_id, record.name)

    def load_box_cards(
        self,
        *,
        user_id: UUID,
        box_name: str,
        skip_manifest: bool = True,
        limit: Optional[int] = None,
    ) -> List[Card]:
        tenant_id = tenant_for_user(user_id)
        engine = self._cardbox_service._get_engine(tenant_id)
        box = engine.storage_adapter.load_card_box(box_name, tenant_id)
        if box is None:
            return []

        card_ids = list(box.card_ids or [])
        cards: List[Card] = []
        for idx, card_id in enumerate(card_ids):
            if skip_manifest and idx == 0:
                card = engine.card_store.get(card_id)
                if not card or card.metadata.get("type") != MANIFEST_TYPE:
                    # Manifest missing; treat as regular card
                    pass
                else:
                    continue
            card = engine.card_store.get(card_id)
            if card is None:
                continue
            cards.append(card)
            if limit is not None and len(cards) >= limit:
                break
        return cards

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------
    async def _build_timelog_cards(
        self,
        db: AsyncSession,
        user_id: UUID,
        filters: Dict[str, Any],
    ) -> Tuple[List[Card], Dict[str, Any]]:
        limit = int(filters.get("limit") or DEFAULT_LIMITS[MODULE_ACTUAL_EVENT])
        start_dt, end_dt = self._resolve_time_window(filters)
        keyword = filters.get("keyword") or filters.get("description_keyword")
        tracking_method = filters.get("tracking_method")
        dimension_name = filters.get("dimension_name")
        task_filter_raw = filters.get("task_id")
        task_filter: Optional[UUID] = None
        if task_filter_raw is not None:
            try:
                task_filter = UUID(task_filter_raw)
            except (TypeError, ValueError):
                task_filter = None

        timezone_name, timezone_info = await self._resolve_user_timezone_info(
            db, user_id
        )

        events = await search_actual_events(
            db,
            user_id=user_id,
            start_date=start_dt,
            end_date=end_dt,
            tracking_method=tracking_method,
            dimension_name=dimension_name,
            description_keyword=keyword,
            task_id=task_filter,
            max_results=DEFAULT_MAX_SEARCH_RESULTS,
            max_range_days=DEFAULT_MAX_SEARCH_DAYS,
        )

        dimension_name_cache: Dict[UUID, Optional[str]] = {}
        dimension_ids = {
            event.dimension_id
            for event, *_ in events
            if getattr(event, "dimension_id", None) is not None
        }
        for dim_id in dimension_ids:
            try:
                dimension = await get_dimension(
                    db, user_id=user_id, dimension_id=dim_id
                )
            except Exception:  # pragma: no cover - defensive
                dimension = None
            if dimension is not None:
                dimension_name_cache[dim_id] = dimension.name

        cards: List[Card] = []
        base_tags = {"context", MODULE_ACTUAL_EVENT}
        grouped_entries: Dict[str, Dict[str, Any]] = {}
        total_entries = 0

        for event, persons, task_summary in events[:limit]:
            lines: List[str] = []
            title = (event.title or "untitled Timelog").strip()
            lines.append(f"Timelog: {title}")
            time_range = self._format_time_range(event.start_time, event.end_time)
            if time_range:
                lines.append(f"TimeRange: {time_range}")

            dimension_label = None
            dimension_id_value = getattr(event, "dimension_id", None)
            if dimension_id_value:
                dimension_label = dimension_name_cache.get(event.dimension_id)
                if dimension_label:
                    lines.append(f"DimensionLabel: {dimension_label}")
                else:
                    lines.append(f"DimensionId{event.dimension_id}")

            task_info: Optional[Dict[str, Any]] = None
            if task_summary:
                task_content = self._resolve_attr(task_summary, "content") or ""
                task_status = self._resolve_attr(task_summary, "status") or ""
                lines.append(
                    "Task: {content}({status})".format(
                        content=task_content,
                        status=task_status,
                    )
                )
                task_id_value = self._resolve_attr(task_summary, "id")
                vision_id_value = self._resolve_attr(task_summary, "vision_id")
                task_info = {
                    "id": str(task_id_value) if task_id_value is not None else None,
                    "content": task_content or None,
                    "status": task_status or None,
                    "vision_id": (
                        str(vision_id_value) if vision_id_value is not None else None
                    ),
                }

            participant_display_names: List[str] = []
            participant_details: List[Dict[str, Optional[str]]] = []
            if persons:
                for person in persons:
                    display_name = (
                        self._resolve_attr(person, "display_name")
                        or self._resolve_attr(person, "name")
                        or ""
                    )
                    raw_name = self._resolve_attr(person, "name")
                    person_id_value = self._resolve_attr(person, "id")
                    if display_name:
                        participant_display_names.append(str(display_name))
                    participant_details.append(
                        {
                            "id": (
                                str(person_id_value)
                                if person_id_value is not None
                                else None
                            ),
                            "display_name": str(display_name) if display_name else None,
                            "name": str(raw_name) if raw_name else None,
                        }
                    )

            filtered = [name for name in participant_display_names if name]
            if filtered:
                lines.append("Related Persons: " + ", ".join(filtered))

            if event.tags:
                lines.append("Tags: " + ", ".join(event.tags))

            note_text = (event.notes or "").strip()
            if note_text:
                lines.append("Notes: " + note_text)

            tracking_method = getattr(event, "tracking_method", None)
            if tracking_method:
                lines.append(f"TrackingMethod: {tracking_method}")

            duration_minutes = self._calculate_duration_minutes(
                event.start_time, event.end_time
            )
            if duration_minutes is not None:
                lines.append(f"DurationMinutes: {duration_minutes}")

            local_day = self._resolve_event_local_day(event, timezone_info)
            day_key = local_day.isoformat()

            entry_data = {
                "lines": lines,
                "event_id": str(event.id),
                "start_time": event.start_time,
                "end_time": event.end_time,
                "tags": set(event.tags or []),
                "structured": {
                    "event_id": str(event.id),
                    "title": title,
                    "start_time": self._safe_iso(event.start_time),
                    "end_time": self._safe_iso(event.end_time),
                    "duration_minutes": duration_minutes,
                    "dimension": (
                        {
                            "id": (
                                str(dimension_id_value)
                                if dimension_id_value is not None
                                else None
                            ),
                            "name": dimension_label,
                        }
                        if dimension_id_value or dimension_label
                        else None
                    ),
                    "tracking_method": tracking_method,
                    "participants": [
                        participant
                        for participant in participant_details
                        if participant.get("id")
                        or participant.get("display_name")
                        or participant.get("name")
                    ],
                    "participant_names": filtered,
                    "task": task_info,
                    "notes": note_text or None,
                    "tags": list(event.tags or []),
                },
            }

            group = grouped_entries.get(day_key)
            if group is None:
                group = {"entries": [], "local_day": local_day}
                grouped_entries[day_key] = group
            group["entries"].append(entry_data)
            total_entries += 1

        grouping_meta: List[Dict[str, Any]] = []
        entry_limit = ACTUAL_EVENT_CARD_ENTRY_LIMIT

        for day_key, group in grouped_entries.items():
            entries = group["entries"]
            entry_count = len(entries)
            if entry_count == 0:
                continue
            total_chunks = math.ceil(entry_count / entry_limit)
            grouping_meta.append(
                {
                    "day": day_key,
                    "entry_count": entry_count,
                    "chunks": total_chunks,
                }
            )

            for chunk_index in range(total_chunks):
                start_idx = chunk_index * entry_limit
                chunk_entries = entries[start_idx : start_idx + entry_limit]
                if not chunk_entries:
                    continue

                card_lines: List[str] = []
                header = f"Date: {day_key} ({timezone_name})"
                if total_chunks > 1:
                    header = f"{header} [part {chunk_index + 1}/{total_chunks}]"
                card_lines.append(header)

                for offset, entry in enumerate(chunk_entries, start=start_idx + 1):
                    entry_lines = entry["lines"]
                    if not entry_lines:
                        continue
                    first_line = entry_lines[0]
                    card_lines.append(f"{offset}. {first_line}")
                    for extra_line in entry_lines[1:]:
                        card_lines.append(f"   {extra_line}")
                    card_lines.append("")

                if card_lines and card_lines[-1] == "":
                    card_lines.pop()

                chunk_tags = set(base_tags)
                event_ids: List[str] = []
                start_candidates: List[datetime] = []
                end_candidates: List[datetime] = []
                chunk_structured_entries: List[Dict[str, Any]] = []
                for rel_index, entry in enumerate(chunk_entries, start=start_idx + 1):
                    chunk_tags.update(entry.get("tags", set()))
                    event_ids.append(entry["event_id"])
                    if entry.get("start_time") is not None:
                        start_candidates.append(entry["start_time"])
                    if entry.get("end_time") is not None:
                        end_candidates.append(entry["end_time"])

                    structured_entry = entry.get("structured") or {}
                    if structured_entry:
                        enriched_entry = {
                            **structured_entry,
                            "index": rel_index,
                            "local_day": day_key,
                            "chunk_index": chunk_index + 1,
                            "chunks_total": total_chunks,
                        }
                        chunk_structured_entries.append(enriched_entry)

                latest_start_iso = (
                    self._safe_iso(max(start_candidates)) if start_candidates else None
                )
                earliest_end_iso = (
                    self._safe_iso(min(end_candidates)) if end_candidates else None
                )
                earliest_start_iso = (
                    self._safe_iso(min(start_candidates)) if start_candidates else None
                )
                latest_end_iso = (
                    self._safe_iso(max(end_candidates)) if end_candidates else None
                )

                metadata = {
                    "role": "system",
                    "type": ENTRY_TYPE,
                    "module": MODULE_ACTUAL_EVENT,
                    "indexable": True,
                    "tags": sorted(chunk_tags),
                    "day": day_key,
                    "timezone": timezone_name,
                    "entry_count": len(chunk_entries),
                    "event_ids": event_ids,
                    "chunk_index": chunk_index + 1,
                    "chunks_total": total_chunks,
                }
                if latest_start_iso:
                    metadata["latest_start_time"] = latest_start_iso
                if earliest_end_iso:
                    metadata["earliest_end_time"] = earliest_end_iso
                if earliest_start_iso:
                    metadata["earliest_start_time"] = earliest_start_iso
                if latest_end_iso:
                    metadata["latest_end_time"] = latest_end_iso
                if chunk_structured_entries:
                    metadata["entries"] = chunk_structured_entries

                content = TextContent(text="\n".join(card_lines))
                cards.append(Card(content=content, metadata=metadata))

        meta = {
            "filters": filters,
            "items": total_entries,
            "window": {
                "start": self._safe_iso(start_dt),
                "end": self._safe_iso(end_dt),
            },
            "grouping": {
                "mode": "per_day",
                "timezone": timezone_name,
                "max_entries_per_card": entry_limit,
                "days": grouping_meta,
            },
        }
        return cards, meta

    @staticmethod
    def _resolve_attr(obj: Any, key: str) -> Any:
        """Best-effort attribute/dict accessor."""
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    async def _build_note_cards(
        self,
        db: AsyncSession,
        user_id: UUID,
        filters: Dict[str, Any],
    ) -> Tuple[List[Card], Dict[str, Any]]:
        limit = int(filters.get("limit") or DEFAULT_LIMITS[MODULE_NOTES])
        notes = await _list_notes_for_context(
            db,
            user_id=user_id,
            limit=limit,
            offset=0,
            tag_id=filters.get("tag_id"),
            person_id=filters.get("person_id"),
            task_id=filters.get("task_id"),
            keyword=filters.get("keyword"),
            untagged=filters.get("untagged"),
        )

        cards: List[Card] = []
        base_tags = {"context", MODULE_NOTES}
        for note in notes:
            lines = [
                f"Note created at: {self._safe_iso(note.created_at) or 'unknown time'}"
            ]
            content = (note.content or "").strip()
            if content:
                lines.append("Content: " + content)

            person_ids: List[str] = []
            if getattr(note, "persons", None):
                names = []
                for person in note.persons:
                    display = getattr(person, "display_name", None) or getattr(
                        person, "name", None
                    )
                    if display:
                        names.append(display)
                    person_id = getattr(person, "id", None)
                    if person_id:
                        person_ids.append(str(person_id))
                if names:
                    lines.append("Related Persons: " + ", ".join(names))

            task_id_value = None
            if getattr(note, "task", None):
                lines.append(f"Related Tasks: {note.task.content}")
                task_id = getattr(note.task, "id", None)
                if task_id:
                    task_id_value = str(task_id)

            note_tags: List[str] = []
            note_tag_ids: List[str] = []
            for tag in getattr(note, "tags", []) or []:
                tag_name = getattr(tag, "name", None)
                if tag_name:
                    note_tags.append(tag_name)
                tag_id = getattr(tag, "id", None)
                if tag_id:
                    note_tag_ids.append(str(tag_id))
            if note_tags:
                lines.append("Tags: " + ", ".join(note_tags))

            metadata = {
                "role": "system",
                "type": ENTRY_TYPE,
                "module": MODULE_NOTES,
                "indexable": True,
                "tags": sorted(base_tags | set(note_tags)),
                "note_id": str(note.id),
                "created_at": self._safe_iso(note.created_at),
                "updated_at": self._safe_iso(note.updated_at),
            }
            if task_id_value:
                metadata["task_id"] = task_id_value
            if note_tag_ids:
                metadata["tag_ids"] = note_tag_ids
            if person_ids:
                metadata["person_ids"] = person_ids
            cards.append(
                Card(content=TextContent(text="\n".join(lines)), metadata=metadata)
            )

        meta = {
            "filters": filters,
            "items": len(cards),
        }
        return cards, meta

    async def _build_planning_task_cards(
        self,
        db: AsyncSession,
        user_id: UUID,
        filters: Dict[str, Any],
    ) -> Tuple[List[Card], Dict[str, Any]]:
        limit = int(filters.get("limit") or DEFAULT_LIMITS[MODULE_PLANNING_TASKS])
        cycle_type = str(filters.get("planning_cycle_type") or "week")
        start_date_str = filters.get("planning_cycle_start_date")
        if not start_date_str:
            raise ValueError(
                "planning_cycle_start_date is required for planning tasks context"
            )

        status_in = filters.get("status_in")
        if isinstance(status_in, list):
            status_param = ",".join(str(item) for item in status_in if item)
        else:
            status_param = status_in

        tasks = await list_tasks(
            db,
            user_id=user_id,
            skip=0,
            limit=limit,
            planning_cycle_type=cycle_type,
            planning_cycle_start_date=start_date_str,
            status_in=status_param,
        )

        vision_ids: set[UUID] = {
            task.vision_id
            for task in tasks
            if getattr(task, "vision_id", None) is not None
        }
        vision_name_map: Dict[UUID, str] = {}
        if vision_ids:
            fetched = await _list_visions_for_cardbox(
                db,
                user_id=user_id,
                limit=max(len(vision_ids), 20),
            )
            for vision in fetched:
                if vision.id in vision_ids:
                    vision_name_map[vision.id] = vision.name

        cards: List[Card] = []
        base_tags = {"context", MODULE_PLANNING_TASKS}
        for task in tasks:
            summary_payload = self._task_summary_payload(
                task,
                include_parent=False,
            )
            if summary_payload is None:
                continue

            status_value = summary_payload.get("status")
            priority_value = summary_payload.get("priority")
            lines: List[str] = []
            lines.append(f"Task: {summary_payload.get('content') or 'unknown task'}")
            if status_value:
                lines.append(f"Status: {status_value}")
            if priority_value is not None:
                lines.append(f"Priority: {priority_value}")
            if summary_payload.get("notes_count"):
                lines.append(f"Related Notes: {summary_payload.get('notes_count')}")

            planning_start = getattr(task, "planning_cycle_start_date", None)
            planning_days = getattr(task, "planning_cycle_days", None)
            if getattr(task, "planning_cycle_type", None):
                lines.append(
                    "Planning Cycle: {cycle}(start from {start})".format(
                        cycle=task.planning_cycle_type,
                        start=(
                            planning_start.isoformat()
                            if hasattr(planning_start, "isoformat")
                            else planning_start
                        ),
                    )
                )
            if planning_days:
                lines.append(f"Planning Days: {planning_days}")

            if getattr(task, "vision_id", None):
                vision_name = vision_name_map.get(task.vision_id)
                if vision_name:
                    lines.append(f"Owned by Vision: {vision_name}")

            if getattr(task, "persons", None):
                people = [
                    person.display_name or person.name
                    for person in task.persons
                    if getattr(person, "display_name", None)
                    or getattr(person, "name", None)
                ]
                if people:
                    lines.append("Related Persons: " + ", ".join(people))

            # Attach up to 3 related notes for additional context
            note_snippets: List[str] = []
            note_ids: List[str] = []
            try:
                task_notes = await note_service.list_notes(
                    db,
                    user_id=user_id,
                    limit=3,
                    offset=0,
                    task_id=task.id,
                )
                for note in task_notes:
                    snippet = (note.content or "").strip()
                    if snippet:
                        note_snippets.append(snippet[:160])
                    note_ids.append(str(note.id))
            except Exception:  # pragma: no cover - defensive
                task_notes = []

            if note_snippets:
                lines.append("Notes: ")
                for snippet in note_snippets:
                    lines.append(f"- {snippet}")

            metadata: Dict[str, Any] = {
                "role": "system",
                "type": ENTRY_TYPE,
                "module": MODULE_PLANNING_TASKS,
                "indexable": True,
                "tags": sorted(
                    base_tags | {f"status:{status_value}"}
                    if status_value
                    else base_tags
                ),
                "task_id": summary_payload.get("id"),
                "task_summary": summary_payload,
                "vision_id": summary_payload.get("vision_id"),
                "status": status_value,
                "priority": priority_value,
                "planning_cycle_type": getattr(task, "planning_cycle_type", None),
                "planning_cycle_start_date": (
                    getattr(task, "planning_cycle_start_date").isoformat()
                    if hasattr(task, "planning_cycle_start_date")
                    and getattr(task, "planning_cycle_start_date") is not None
                    else getattr(task, "planning_cycle_start_date", None)
                ),
                "planning_cycle_days": getattr(task, "planning_cycle_days", None),
                "actual_effort_total": summary_payload.get("actual_effort_total"),
                "notes_count": summary_payload.get("notes_count"),
                "created_at": summary_payload.get("created_at"),
                "updated_at": summary_payload.get("updated_at"),
            }

            if getattr(task, "persons", None):
                metadata["person_ids"] = [
                    str(person.id)
                    for person in task.persons
                    if getattr(person, "id", None) is not None
                ]
            if note_ids:
                metadata["note_ids"] = note_ids
                metadata["note_count"] = len(note_ids)

            # Drop None values for cleaner metadata
            metadata = {k: v for k, v in metadata.items() if v is not None}
            cards.append(
                Card(content=TextContent(text="\n".join(lines)), metadata=metadata)
            )

        meta = {
            "filters": filters,
            "items": len(cards),
        }
        return cards, meta

    async def _build_vision_progress_cards(
        self,
        db: AsyncSession,
        user_id: UUID,
        filters: Dict[str, Any],
    ) -> Tuple[List[Card], Dict[str, Any]]:
        vision_ids_raw = filters.get("vision_ids") or []
        requested_ids: List[UUID] = []
        if isinstance(vision_ids_raw, list):
            for raw in vision_ids_raw:
                try:
                    requested_ids.append(UUID(str(raw)))
                except Exception:
                    continue
        elif vision_ids_raw:
            try:
                requested_ids.append(UUID(str(vision_ids_raw)))
            except Exception:
                pass

        if not requested_ids:
            return [], {"filters": filters, "items": 0}

        limit = int(filters.get("limit") or DEFAULT_LIMITS[MODULE_VISION_PROGRESS])
        status_in = filters.get("task_status_in")
        if isinstance(status_in, list):
            status_param = ",".join(str(item) for item in status_in if item)
        else:
            status_param = status_in

        visions = await _list_visions_for_cardbox(
            db,
            user_id=user_id,
            limit=max(limit, len(requested_ids)),
        )
        selected_visions = [vision for vision in visions if vision.id in requested_ids]

        cards: List[Card] = []
        base_tags = {"context", MODULE_VISION_PROGRESS}
        task_limit = int(filters.get("task_limit") or 50)

        for vision in selected_visions[:limit]:
            tasks = await list_tasks(
                db,
                user_id=user_id,
                skip=0,
                limit=task_limit,
                vision_id=vision.id,
                status_in=status_param,
            )

            lines: List[str] = []
            lines.append(f"Vison: {vision.name}")
            lines.append(f"Status: {vision.status}")
            lines.append(f"Stage: {getattr(vision, 'stage', '')}")
            lines.append(
                f"Total actual effort: {getattr(vision, 'total_actual_effort', 0)} mins"
            )
            if vision.description:
                lines.append("Description: " + vision.description.strip())

            if getattr(vision, "persons", None):
                people = [
                    person.display_name or person.name
                    for person in vision.persons
                    if getattr(person, "display_name", None)
                    or getattr(person, "name", None)
                ]
                if people:
                    lines.append("Persons: " + ", ".join(people))

            task_summaries: List[Dict[str, Any]] = []
            if tasks:
                lines.append("Tasks: ")
                for task in tasks[: min(len(tasks), 8)]:
                    summary_payload = self._task_summary_payload(
                        task,
                        include_parent=False,
                    )
                    if summary_payload is None:
                        continue
                    task_summaries.append(summary_payload)
                    lines.append(
                        "- {content}(status: {status}, priority:{priority})".format(
                            content=summary_payload.get("content"),
                            status=summary_payload.get("status"),
                            priority=summary_payload.get("priority"),
                        )
                    )

            metadata: Dict[str, Any] = {
                "role": "system",
                "type": ENTRY_TYPE,
                "module": MODULE_VISION_PROGRESS,
                "indexable": True,
                "tags": sorted(base_tags | {f"vision:{vision.id}"}),
                "vision_id": str(vision.id),
                "status": vision.status,
                "stage": getattr(vision, "stage", None),
                "total_actual_effort": getattr(vision, "total_actual_effort", None),
                "created_at": self._safe_iso(vision.created_at),
                "updated_at": self._safe_iso(vision.updated_at),
                "task_ids": [
                    summary.get("id") for summary in task_summaries if summary.get("id")
                ],
                "task_summaries": task_summaries,
                "task_count": len(task_summaries),
            }
            if getattr(vision, "persons", None):
                metadata["person_ids"] = [
                    str(person.id)
                    for person in vision.persons
                    if getattr(person, "id", None) is not None
                ]

            metadata = {k: v for k, v in metadata.items() if v is not None}
            cards.append(
                Card(content=TextContent(text="\n".join(lines)), metadata=metadata)
            )

        meta = {
            "filters": filters,
            "items": len(cards),
        }
        return cards, meta

    async def _build_vision_task_cards(
        self,
        db: AsyncSession,
        user_id: UUID,
        filters: Dict[str, Any],
    ) -> Tuple[List[Card], Dict[str, Any]]:
        vision_limit = int(
            filters.get("vision_limit") or DEFAULT_LIMITS[MODULE_VISION_TASKS]
        )
        task_limit = int(filters.get("task_limit") or 50)

        requested_vision_ids = self._parse_uuid_list(filters.get("vision_ids"))
        status_filter = filters.get("vision_status") or filters.get("status_filter")

        visions = await _list_visions_for_cardbox(
            db,
            user_id=user_id,
            limit=vision_limit,
            status_filter=status_filter,
        )
        if requested_vision_ids:
            visions = [
                vision for vision in visions if vision.id in requested_vision_ids
            ]

        vision_ids = [vision.id for vision in visions]
        tasks = await list_tasks(
            db,
            user_id=user_id,
            skip=0,
            limit=task_limit,
            vision_id=vision_ids[0] if len(vision_ids) == 1 else None,
            status_filter=filters.get("task_status"),
            status_in=filters.get("task_status_in"),
            exclude_status=filters.get("exclude_status"),
            planning_cycle_type=filters.get("planning_cycle_type"),
            planning_cycle_start_date=filters.get("planning_cycle_start_date"),
        )

        tasks_by_vision: Dict[UUID, List[Dict[str, Any]]] = defaultdict(list)
        orphan_task_summaries: List[Dict[str, Any]] = []
        for task in tasks:
            summary_payload = self._task_summary_payload(task)
            if summary_payload is None:
                continue
            vision_key = getattr(task, "vision_id", None)
            entry = {"task": task, "summary": summary_payload}
            tasks_by_vision[vision_key].append(entry)
            if vision_key is None:
                orphan_task_summaries.append(entry)

        cards: List[Card] = []
        base_tags = {"context", MODULE_VISION_TASKS}
        for vision in visions:
            lines: List[str] = []
            lines.append(f"Vision: {vision.name}")
            lines.append(f"Status: {vision.status}")
            if vision.description:
                lines.append("Description: " + vision.description.strip())
            lines.append(f"Stage: {getattr(vision, 'stage', '')}")
            lines.append(
                f"Total actual effort: {getattr(vision, 'total_actual_effort', 0)} minutes"
            )
            if getattr(vision, "persons", None):
                people = [
                    p.display_name or p.name
                    for p in vision.persons
                    if getattr(p, "display_name", None) or getattr(p, "name", None)
                ]
                if people:
                    lines.append("Key participants: " + ", ".join(people))

            related_entries = tasks_by_vision.get(vision.id, [])[
                : max(1, math.ceil(task_limit / max(len(visions), 1)))
            ]
            if related_entries:
                lines.append("Key tasks:")
                for entry in related_entries:
                    summary_payload = entry["summary"]
                    lines.append(
                        "- {content} (status: {status}, priority: {priority})".format(
                            content=summary_payload.get("content"),
                            status=summary_payload.get("status"),
                            priority=summary_payload.get("priority"),
                        )
                    )

            metadata = {
                "role": "system",
                "type": ENTRY_TYPE,
                "module": MODULE_VISION_TASKS,
                "indexable": True,
                "tags": sorted(base_tags | {f"vision:{vision.id}"}),
                "vision_id": str(vision.id),
                "created_at": self._safe_iso(vision.created_at),
                "updated_at": self._safe_iso(vision.updated_at),
                "status": getattr(vision, "status", None),
                "stage": getattr(vision, "stage", None),
                "total_actual_effort": getattr(vision, "total_actual_effort", None),
            }
            if getattr(vision, "persons", None):
                vision_person_ids = [
                    str(getattr(person, "id"))
                    for person in vision.persons
                    if getattr(person, "id", None) is not None
                ]
                if vision_person_ids:
                    metadata["person_ids"] = vision_person_ids
            if related_entries:
                metadata["task_summaries"] = [
                    entry["summary"] for entry in related_entries
                ]
                metadata["task_ids"] = [
                    entry["summary"].get("id")
                    for entry in related_entries
                    if entry["summary"].get("id")
                ]
            cards.append(
                Card(content=TextContent(text="\n".join(lines)), metadata=metadata)
            )

        # Include orphan tasks without a selected vision (when vision filter absent)
        if not vision_ids:
            for entry in orphan_task_summaries[:task_limit]:
                task = entry["task"]
                summary_payload = entry["summary"]
                lines = [f"Task: {summary_payload.get('content')}"]
                status_value = summary_payload.get("status")
                if status_value:
                    lines.append(f"Status: {status_value}")
                notes_count = summary_payload.get("notes_count") or 0
                if notes_count:
                    lines.append(f"Notes count: {notes_count}")
                metadata = {
                    "role": "system",
                    "type": ENTRY_TYPE,
                    "module": MODULE_VISION_TASKS,
                    "indexable": True,
                    "tags": sorted(base_tags | {"task"}),
                    "task_id": summary_payload.get("id"),
                    "vision_id": summary_payload.get("vision_id"),
                    "created_at": summary_payload.get("created_at"),
                    "updated_at": summary_payload.get("updated_at"),
                    "status": status_value,
                    "priority": summary_payload.get("priority"),
                    "task_summary": summary_payload,
                }
                if getattr(task, "notes", None):
                    metadata["has_notes"] = True
                cards.append(
                    Card(content=TextContent(text="\n".join(lines)), metadata=metadata)
                )

        meta = {
            "filters": filters,
            "items": len(cards),
        }
        return cards, meta

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_manifest_card(
        self,
        *,
        module: str,
        box_name: str,
        display_name: Optional[str],
        generated_at: datetime,
        filters: Dict[str, Any],
        payload_meta: Dict[str, Any],
        total_cards: int,
        legacy_module: Optional[str] = None,
    ) -> Card:
        label = MODULE_LABELS.get(module, module.title())
        human_name = display_name or f"{label} {generated_at:%Y-%m-%d %H:%M}"
        manifest = {
            "title": human_name,
            "module": module,
            "source_type": module,
            "box_name": box_name,
            "generated_at": generated_at.isoformat(),
            "filters": filters,
            "card_count": total_cards,
            "details": payload_meta,
        }
        if legacy_module and legacy_module != module:
            manifest["legacy_module"] = legacy_module
        metadata = {
            "role": "system",
            "type": MANIFEST_TYPE,
            "module": module,
            "source_type": module,
            "title": human_name,
            "generated_at": generated_at.isoformat(),
            "filters": filters,
            "card_count": total_cards,
            "indexable": False,
            "tags": ["context", module, "manifest"],
        }
        if legacy_module and legacy_module != module:
            metadata["legacy_module"] = legacy_module
        return Card(
            content=TextContent(
                text=json_dumps(manifest, ensure_ascii=False, indent=2)
            ),
            metadata=metadata,
        )

    def _build_default_display_name(
        self,
        module: str,
        filters: Dict[str, Any],
        timestamp: datetime,
    ) -> str:
        label = MODULE_LABELS.get(module, module.title())
        parts = self._summarise_filters(module, filters)
        if parts:
            name = " | ".join([label, *parts])
        else:
            name = f"{label} | {timestamp:%Y-%m-%d %H:%M}"
        return name[:160]

    def _summarise_filters(self, module: str, filters: Dict[str, Any]) -> List[str]:
        module_key = self._canonical_module_key(module)

        if not filters:
            return []

        summary: List[str] = []

        def add(label: str, value: Any) -> None:
            if value is None or value == "" or value == []:
                return
            if isinstance(value, (list, tuple, set)):
                items = [
                    self._stringify_value(item, max_length=16) for item in value if item
                ]
                if not items:
                    return
                text = ",".join(items)
                if len(text) > 60:
                    text = text[:59] + "…"
            else:
                text = self._stringify_value(value)
            if text:
                summary.append(f"{label}={text}")

        if module_key == MODULE_ACTUAL_EVENT:
            start = self._extract_date(filters.get("start_date"))
            end = self._extract_date(filters.get("end_date"))
            if start and end:
                if start == end:
                    summary.append(f"date={start}")
                else:
                    summary.append(f"{start}~{end}")
            elif start:
                summary.append(f"from={start}")
            elif end:
                summary.append(f"until={end}")
            add("dimension", filters.get("dimension_name"))
            keyword = filters.get("keyword") or filters.get("description_keyword")
            add("keyword", keyword)
            add("task", filters.get("task_id"))
            add("tracking", filters.get("tracking_method"))
        elif module_key == MODULE_NOTES:
            add("keyword", filters.get("keyword"))
            add("tag", filters.get("tag_id"))
            add("person", filters.get("person_id"))
        elif module_key == MODULE_PLANNING_TASKS:
            add("cycle", filters.get("planning_cycle_type"))
            start = self._extract_date(filters.get("planning_cycle_start_date"))
            add("start", start)
            add("status", filters.get("status_in"))
        elif module_key == MODULE_VISION_PROGRESS:
            vision_ids = filters.get("vision_ids")
            if isinstance(vision_ids, (list, tuple)):
                if vision_ids:
                    summary.append(f"visions={len(vision_ids)}")
            elif vision_ids:
                add("vision", vision_ids)
            add("task_status", filters.get("task_status_in"))
        else:
            for key in sorted(filters):
                if key == "limit":
                    continue
                add(key, filters[key])

        return summary

    def _stringify_value(self, value: Any, *, max_length: int = 32) -> str:
        if value is None:
            return ""
        if isinstance(value, (datetime, date)):
            return value.isoformat()[:10]
        text = str(value).strip()
        if len(text) > max_length:
            return text[: max_length - 1] + "…"
        return text

    def _extract_date(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, str):
            match = re.search(r"\d{4}-\d{2}-\d{2}", value)
            if match:
                return match.group(0)
        return None

    def _build_box_name(
        self,
        user_id: UUID,
        module: str,
        display_name: Optional[str],
        timestamp: datetime,
    ) -> str:
        base = f"context/{module}/{user_id}"
        if display_name:
            suffix = self._slugify(display_name)
            if suffix == "context":
                digest = hashlib.sha1(display_name.encode("utf-8")).hexdigest()[:10]
                suffix = f"context-{digest}"
        else:
            suffix = timestamp.strftime("%Y%m%dT%H%M%SZ")
        return f"{base}/{suffix}"

    def _fetch_record_by_name(
        self, tenant_id: str, box_name: str
    ) -> Optional[ContextBoxRecord]:
        engine, storage, connection = self._get_engine_and_connection(tenant_id)
        row = connection.execute(
            "SELECT box_id, name, card_ids, updated_at FROM card_boxes WHERE tenant_id = ? AND name = ?",
            (tenant_id, box_name),
        ).fetchone()
        if not row:
            return None
        return self._build_record_from_row(engine, row)

    def _fetch_record_by_id(
        self, tenant_id: str, box_id: int
    ) -> Optional[ContextBoxRecord]:
        engine, storage, connection = self._get_engine_and_connection(tenant_id)
        row = connection.execute(
            "SELECT box_id, name, card_ids, updated_at FROM card_boxes WHERE tenant_id = ? AND box_id = ?",
            (tenant_id, box_id),
        ).fetchone()
        if not row:
            return None
        return self._build_record_from_row(engine, row)

    def _build_record_from_row(
        self, engine, row: Sequence[Any]
    ) -> Optional[ContextBoxRecord]:
        if not row:
            return None
        box_id, name, card_ids_raw, updated_at_raw = row
        card_ids = []
        if card_ids_raw:
            try:
                card_ids = json.loads(card_ids_raw)
            except (TypeError, json.JSONDecodeError):
                card_ids = []
        manifest_metadata: Dict[str, Any] = {}
        if card_ids:
            first_card = engine.card_store.get(card_ids[0])
            if first_card and isinstance(first_card.content, TextContent):
                manifest_metadata = dict(first_card.metadata or {})
        module_raw = manifest_metadata.get("module", "unknown")
        module = self._canonical_module_key(module_raw)
        if module and module_raw != module:
            manifest_metadata.setdefault("legacy_module", module_raw)
            manifest_metadata["module"] = module
        display_name = manifest_metadata.get("title") or name
        updated_at = self._ensure_datetime(updated_at_raw)
        return ContextBoxRecord(
            box_id=box_id,
            name=name,
            module=module,
            display_name=display_name,
            card_count=max(len(card_ids) - 1, 0),
            updated_at=updated_at,
            manifest_metadata=manifest_metadata,
        )

    def _get_engine_and_connection(self, tenant_id: str):
        engine = self._cardbox_service._get_engine(tenant_id)
        storage = engine.storage_adapter
        if hasattr(storage, "_get_connection"):
            connection = storage._get_connection()
        elif hasattr(storage, "_connection"):
            connection = storage._connection
        else:  # pragma: no cover - defensive
            raise RuntimeError("Storage adapter does not expose a connection")
        return engine, storage, connection

    def _canonical_module_key(self, module: Optional[str]) -> str:
        if not module:
            return "unknown"
        normalized = module.lower()
        return LEGACY_MODULE_ALIASES.get(normalized, normalized)

    def _normalise_filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        def _convert(value: Any) -> Any:
            if isinstance(value, datetime):
                return value.astimezone(timezone.utc).isoformat()
            if isinstance(value, date):
                return datetime.combine(
                    value, time.min, tzinfo=timezone.utc
                ).isoformat()
            if isinstance(value, UUID):
                return str(value)
            if isinstance(value, list):
                return [_convert(item) for item in value]
            return value

        return {
            key: _convert(val)
            for key, val in (filters or {}).items()
            if val is not None
        }

    def _resolve_time_window(
        self, filters: Dict[str, Any]
    ) -> Tuple[Optional[datetime], Optional[datetime]]:
        start_raw = filters.get("start_date") or filters.get("start_time")
        end_raw = filters.get("end_date") or filters.get("end_time")
        if filters.get("date") and not start_raw:
            start_raw = filters["date"]
            end_raw = filters["date"]

        start_dt = self._coerce_datetime(start_raw, default_min=True)
        end_dt = self._coerce_datetime(end_raw, default_min=False)
        return start_dt, end_dt

    async def _resolve_user_timezone_info(
        self, db: AsyncSession, user_id: UUID
    ) -> Tuple[str, ZoneInfo]:
        timezone_value = DEFAULT_TIMEZONE
        try:
            pref = await user_preferences_service.get_preference_by_key(
                db, user_id=user_id, key="system.timezone"
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Failed to load user timezone preference",
                extra={"user_id": user_id, "error": str(exc)},
            )
            pref = None

        if pref:
            candidate = getattr(pref, "value", None)
            if isinstance(candidate, str) and candidate.strip():
                timezone_value = candidate.strip()

        tzinfo = resolve_timezone(timezone_value, default=DEFAULT_TIMEZONE)
        tz_name = getattr(tzinfo, "key", DEFAULT_TIMEZONE)
        if tz_name != timezone_value:
            logger.warning(
                "Invalid timezone preference; falling back to %s",
                tz_name,
                extra={"user_id": user_id, "timezone": timezone_value},
            )
        return tz_name, tzinfo

    def _resolve_event_local_day(self, event: Any, tzinfo: ZoneInfo) -> date:
        candidates = [
            getattr(event, "start_time", None),
            getattr(event, "end_time", None),
            getattr(event, "created_at", None),
        ]
        for candidate in candidates:
            if candidate is None:
                continue
            if candidate.tzinfo is None:
                candidate = candidate.replace(tzinfo=timezone.utc)
            return candidate.astimezone(tzinfo).date()

        return utc_now().astimezone(tzinfo).date()

    def _coerce_datetime(self, value: Any, *, default_min: bool) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        if isinstance(value, date):
            base_time = time.min if default_min else time.max
            return datetime.combine(value, base_time, tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed.astimezone(timezone.utc)
            except ValueError:
                return None
        return None

    def _format_time_range(
        self, start: Optional[datetime], end: Optional[datetime]
    ) -> Optional[str]:
        if start is None and end is None:
            return None
        start_text = self._safe_iso(start, timespec="minutes") or "?"
        end_text = self._safe_iso(end, timespec="minutes") or "?"
        return f"{start_text} ~ {end_text}"

    def _safe_iso(
        self, value: Optional[datetime], *, timespec: str = "seconds"
    ) -> Optional[str]:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec=timespec)

    def _calculate_duration_minutes(
        self, start: Optional[datetime], end: Optional[datetime]
    ) -> Optional[int]:
        if not start or not end:
            return None
        delta = end - start
        return max(int(delta.total_seconds() // 60), 0)

    def _slugify(self, value: str) -> str:
        lowered = value.strip().lower()
        cleaned = re.sub(r"[^a-z0-9]+", "-", lowered)
        cleaned = cleaned.strip("-") or "context"
        return cleaned[:64]

    def _ensure_datetime(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                parsed = utc_now()
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        return utc_now()

    def _parse_uuid_list(self, value: Any) -> List[UUID]:
        result: List[UUID] = []
        if not value:
            return result
        if isinstance(value, (list, tuple)):
            candidates = value
        else:
            candidates = str(value).split(",")
        for item in candidates:
            try:
                result.append(UUID(str(item).strip()))
            except (ValueError, TypeError):
                continue
        return result


context_box_manager = ContextBoxManager()

__all__ = ["ContextBoxManager", "ContextBoxRecord", "context_box_manager"]
