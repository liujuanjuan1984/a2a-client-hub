"""Batch synchronisation of structured Compass data into Cardbox."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

from card_box_core.structures import Card, TextContent
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.cardbox.service import cardbox_service
from app.cardbox.utils import data_cardbox_name, tenant_for_user
from app.core.constants import USER_PREFERENCE_DEFAULTS
from app.core.i18n import DEFAULT_LOCALE, normalize_locale
from app.core.logging import get_logger
from app.db.models.actual_event import ActualEvent
from app.db.models.note import Note
from app.db.models.task import Task
from app.db.models.user_preference import UserPreference
from app.db.models.vision import Vision
from app.handlers.associations import (
    LinkType,
    ModelName,
    attach_persons_for_sources,
    load_persons_for_sources,
)
from app.handlers.exports.timelog_export import (
    ActualEventExportService,
    TimeLogExportParams,
)
from app.handlers.exports.vision_export import VisionExportParams, VisionExportService
from app.serialization.entities import (
    build_task_summary,
    normalize_task_summary,
    serialize_person_summary,
)
from app.utils.json_encoder import json_dumps
from app.utils.person_utils import convert_persons_to_summary
from app.utils.timezone_util import utc_now

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

_DEFAULT_LANGUAGE = normalize_locale(
    USER_PREFERENCE_DEFAULTS.get("system.language", {}).get("value", DEFAULT_LOCALE)
)
_DEFAULT_TIMEZONE = USER_PREFERENCE_DEFAULTS.get("system.timezone", {}).get(
    "value", "UTC"
)


def _resolve_language_preference(db: Session, user_id: UUID) -> str:
    pref = (
        db.query(UserPreference)
        .filter(
            UserPreference.user_id == user_id,
            UserPreference.key == "system.language",
            UserPreference.deleted_at.is_(None),
        )
        .first()
    )
    if pref and isinstance(pref.value, str):
        value = pref.value.strip()
        if value:
            lowered = value.lower()
            if lowered == "auto":
                return _DEFAULT_LANGUAGE
            return normalize_locale(lowered)
    return _DEFAULT_LANGUAGE


def _resolve_timezone_preference(db: Session, user_id: UUID) -> str:
    pref = (
        db.query(UserPreference)
        .filter(
            UserPreference.user_id == user_id,
            UserPreference.key == "system.timezone",
            UserPreference.deleted_at.is_(None),
        )
        .first()
    )
    if pref and isinstance(pref.value, str):
        value = pref.value.strip()
        if value:
            return value
    return _DEFAULT_TIMEZONE or "UTC"


@dataclass
class SyncSummary:
    """Lightweight summary for a single dataset synchronisation."""

    module: str
    cards_added: int
    skipped: int
    item_count: int


class CardBoxDataSyncService:
    """Provide helpers to batch-sync structured data into Cardbox."""

    SNAPSHOT_VERSION = "1.0"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def sync_all(
        self,
        db: Session,
        *,
        user_id: UUID,
        target_date: Optional[date] = None,
        timelog_window: Optional[tuple[datetime, datetime]] = None,
        task_limit: int = 200,
        note_limit: int = 200,
    ) -> List[SyncSummary]:
        """Synchronise all configured datasets to Cardbox."""

        target = target_date or date.today()
        summaries: List[SyncSummary] = []

        try:
            summaries.append(
                self.sync_timelog(
                    db,
                    user_id=user_id,
                    target_date=target,
                    window=timelog_window,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Cardbox actual_event sync failed for user %s: %s",
                user_id,
                exc,
                exc_info=True,
            )

        try:
            summaries.append(
                self.sync_visions_and_tasks(
                    db,
                    user_id=user_id,
                    target_date=target,
                    limit=task_limit,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Cardbox vision/task sync failed for user %s: %s",
                user_id,
                exc,
                exc_info=True,
            )

        try:
            summaries.append(
                self.sync_notes(
                    db,
                    user_id=user_id,
                    target_date=target,
                    limit=note_limit,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Cardbox note sync failed for user %s: %s", user_id, exc, exc_info=True
            )

        return summaries

    def sync_timelog(
        self,
        db: Session,
        *,
        user_id: UUID,
        target_date: date,
        window: Optional[tuple[datetime, datetime]] = None,
        limit: int = 200,
    ) -> SyncSummary:
        """Synchronise actual_event (time log) snapshot into Cardbox."""

        start_dt, end_dt = self._resolve_window(target_date, window)
        filters: Dict[str, Any] = {"limit": limit}
        keyword: Optional[str] = None
        events = (
            ActualEvent.active(db)
            .filter(ActualEvent.user_id == user_id)
            .filter(ActualEvent.start_time >= start_dt)
            .filter(ActualEvent.start_time <= end_dt)
            .order_by(ActualEvent.start_time.desc())
            .limit(limit)
            .all()
        )

        event_ids = [event.id for event in events]
        persons_map = (
            load_persons_for_sources(
                db,
                source_model=ModelName.ActualEvent,
                source_ids=event_ids,
                link_type=LinkType.ATTENDED_BY,
                user_id=user_id,
            )
            if event_ids
            else {}
        )

        task_ids = {event.task_id for event in events if event.task_id}
        task_map: Dict[UUID, Dict[str, Any]] = {}
        if task_ids:
            tasks = (
                Task.active(db)
                .filter(Task.user_id == user_id)
                .filter(Task.id.in_(task_ids))
                .all()
            )
            for task in tasks:
                summary = build_task_summary(task, include_parent_summary=False)
                normalized = normalize_task_summary(summary)
                if normalized:
                    task_map[task.id] = normalized

        enriched_events: List[ActualEvent] = []
        for event in events:
            persons_summary = convert_persons_to_summary(persons_map.get(event.id, []))
            serialized_persons = [
                serialize_person_summary(person) for person in persons_summary or []
            ]
            setattr(event, "export_person_summaries", serialized_persons)
            if event.task_id:
                setattr(event, "export_task_summary", task_map.get(event.task_id))
            enriched_events.append(event)

        export_locale = _resolve_language_preference(db, user_id=user_id)
        export_timezone = _resolve_timezone_preference(db, user_id=user_id)
        export_service = ActualEventExportService(
            locale=export_locale,
            db=db,
            user_id=user_id,
            user_timezone=export_timezone,
        )

        export_params = TimeLogExportParams(
            start_date=start_dt,
            end_date=end_dt,
            dimension_id=None,
            description_keyword=keyword,
            locale=export_service.locale,
        )
        export_text = export_service.generate_export_text(
            export_params, enriched_events
        )

        stats = export_service._calculate_statistics(enriched_events, None)
        summary_model = export_service.build_snapshot_summary(
            events=enriched_events,
            stats=stats,
            start_dt=start_dt,
            end_dt=end_dt,
        )
        summary_query_model = export_service.build_snapshot_query(filters)

        metadata_extra = {
            "module": "actual_event",
            "legacy_module": "timelog",
            "snapshot_range": {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
            },
            "document_locale": export_locale,
            "summary": summary_model.model_dump(mode="json", exclude_none=True),
            "query": summary_query_model.model_dump(exclude_none=True),
        }
        return self._write_snapshot(
            user_id=user_id,
            module_key="actual_event",
            target_date=target_date,
            payload=export_text,
            metadata_extra=metadata_extra,
            item_count=len(events),
        )

    def sync_visions_and_tasks(
        self,
        db: Session,
        *,
        user_id: UUID,
        target_date: date,
        limit: int = 200,
    ) -> SyncSummary:
        """Synchronise the current snapshot of visions and tasks."""

        visions = (
            Vision.active(db)
            .filter(Vision.user_id == user_id)
            .order_by(Vision.created_at.desc())
            .limit(limit)
            .all()
        )

        vision_ids = [vision.id for vision in visions]

        if visions:
            attach_persons_for_sources(
                db,
                source_model=ModelName.Vision,
                items=visions,
                link_type=LinkType.INVOLVES,
                user_id=user_id,
            )

        if vision_ids:
            totals = (
                db.query(
                    Task.vision_id, func.sum(Task.actual_effort_total).label("total")
                )
                .filter(Task.user_id == user_id)
                .filter(Task.parent_task_id.is_(None))
                .filter(Task.vision_id.in_(vision_ids))
                .group_by(Task.vision_id)
                .all()
            )
            total_map = {vision_id: int(total or 0) for vision_id, total in totals}
        else:
            total_map = {}

        for vision in visions:
            setattr(vision, "total_actual_effort", total_map.get(vision.id, 0))

        tasks = (
            (
                Task.active(db)
                .filter(Task.user_id == user_id)
                .filter(Task.vision_id.in_(vision_ids))
                .order_by(Task.display_order, Task.created_at)
                .limit(limit)
                .all()
            )
            if vision_ids
            else []
        )

        if tasks:
            attach_persons_for_sources(
                db,
                source_model=ModelName.Task,
                items=tasks,
                link_type=LinkType.INVOLVES,
                user_id=user_id,
            )

        tasks_by_vision: Dict[UUID, List[Any]] = {}
        for task in tasks:
            task.actual_effort_total = task.actual_effort_total or 0
            task.actual_effort_self = task.actual_effort_self or 0
            tasks_by_vision.setdefault(task.vision_id, []).append(task)

        def _task_status(value: Any) -> str:
            status = getattr(value, "status", None)
            return status.lower() if isinstance(status, str) else ""

        total_tasks = len(tasks)
        total_completed = sum(1 for task in tasks if _task_status(task) == "done")
        total_open = sum(
            1 for task in tasks if _task_status(task) not in {"done", "cancelled"}
        )

        vision_summaries: List[Dict[str, Any]] = []
        for vision in visions:
            vision_tasks = tasks_by_vision.get(vision.id, [])
            vision_summaries.append(
                {
                    "vision_id": (
                        str(vision.id) if getattr(vision, "id", None) else None
                    ),
                    "name": getattr(vision, "name", None),
                    "status": getattr(vision, "status", None),
                    "stage": getattr(vision, "stage", None),
                    "total_tasks": len(vision_tasks),
                    "completed_tasks": sum(
                        1 for item in vision_tasks if _task_status(item) == "done"
                    ),
                    "open_tasks": sum(
                        1
                        for item in vision_tasks
                        if _task_status(item) not in {"done", "cancelled"}
                    ),
                    "total_actual_effort": total_map.get(vision.id, 0),
                }
            )

        export_locale = _resolve_language_preference(db, user_id=user_id)
        vision_export_service = VisionExportService(locale=export_locale)
        vision_params = VisionExportParams()

        vision_texts: List[str] = []
        for vision in visions:
            vision_tasks = tasks_by_vision.get(vision.id, [])
            payload = {"vision": vision, "tasks": vision_tasks}
            text = vision_export_service.generate_export_text(vision_params, payload)
            vision_texts.append(text)

        if vision_texts:
            export_text = "\n\n---\n\n".join(vision_texts)
        else:
            export_text = vision_export_service._create_empty_export()  # type: ignore[attr-defined]

        metadata_extra = {
            "module": "vision_tasks",
            "snapshot_range": {
                "reference_date": target_date.isoformat(),
            },
            "document_locale": export_locale,
            "summary": {
                "vision_count": len(visions),
                "total_tasks": total_tasks,
                "completed_tasks": total_completed,
                "open_tasks": total_open,
                "visions": vision_summaries,
            },
            "query": {
                "limit": limit,
            },
        }

        return self._write_snapshot(
            user_id=user_id,
            module_key="vision_tasks",
            target_date=target_date,
            payload=export_text,
            metadata_extra=metadata_extra,
            item_count=len(tasks),
        )

    def sync_notes(
        self,
        db: Session,
        *,
        user_id: UUID,
        target_date: date,
        limit: int = 200,
    ) -> SyncSummary:
        """Synchronise recent notes into Cardbox."""

        from app.handlers.exports.notes_export import (
            NotesExportParams,
            NotesExportService,
        )

        filters: Dict[str, Any] = {"limit": limit}

        notes = (
            Note.active(db)
            .filter(Note.user_id == user_id)
            .options(joinedload(Note.tags))
            .order_by(Note.created_at.desc())
            .limit(limit)
            .all()
        )

        export_locale = _resolve_language_preference(db, user_id=user_id)
        notes_export_service = NotesExportService(locale=export_locale)
        notes_params = NotesExportParams(
            search_keyword=filters.get("keyword", ""),
            locale=export_locale,
        )
        export_text = notes_export_service.generate_export_text(notes_params, notes)

        summary = self._build_notes_summary(notes)
        summary_query = self._build_notes_query(filters)

        metadata_extra = {
            "module": "notes",
            "snapshot_range": {
                "reference_date": target_date.isoformat(),
            },
            "document_locale": export_locale,
            "summary": summary,
            "query": summary_query,
        }

        return self._write_snapshot(
            user_id=user_id,
            module_key="notes",
            target_date=target_date,
            payload=export_text,
            metadata_extra=metadata_extra,
            item_count=len(notes),
        )

    def sync_timelog_for_event(
        self,
        db: Session,
        *,
        user_id: UUID,
        event: ActualEvent,
    ) -> None:
        """Trigger an actual_event (time log) sync anchored to the event's date."""

        reference = event.start_time or event.end_time or event.created_at or utc_now()
        self.sync_timelog(db, user_id=user_id, target_date=reference.date())

    def sync_visions_and_tasks_for_user(
        self,
        db: Session,
        *,
        user_id: UUID,
        target_date: Optional[date] = None,
    ) -> None:
        """Trigger a vision/task snapshot refresh."""

        self.sync_visions_and_tasks(
            db,
            user_id=user_id,
            target_date=target_date or date.today(),
        )

    def sync_notes_for_user(
        self,
        db: Session,
        *,
        user_id: UUID,
        target_date: Optional[date] = None,
    ) -> None:
        """Trigger a notes snapshot refresh."""

        self.sync_notes(
            db,
            user_id=user_id,
            target_date=target_date or date.today(),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_notes_summary(self, notes: List[Note]) -> Dict[str, Any]:
        note_ids = [
            str(getattr(note, "id", ""))
            for note in notes
            if getattr(note, "id", None) is not None
        ]
        return {
            "total_records": len(notes),
            "note_ids": note_ids,
            "has_tags": any(getattr(note, "tags", None) for note in notes),
            "has_persons": any(getattr(note, "persons", None) for note in notes),
        }

    def _build_notes_query(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        query: Dict[str, Any] = {}
        if filters.get("keyword"):
            query["keyword"] = filters["keyword"]
        if filters.get("tag_id"):
            query["tag_id"] = filters["tag_id"]
        if filters.get("person_id"):
            query["person_id"] = filters["person_id"]
        if filters.get("limit"):
            query["limit"] = filters["limit"]
        return query

    def _write_snapshot(
        self,
        *,
        user_id: UUID,
        module_key: str,
        target_date: date,
        payload: Any,
        metadata_extra: Optional[Dict[str, Any]] = None,
        item_count: int,
    ) -> SyncSummary:
        tenant_id = tenant_for_user(user_id)
        box_name = data_cardbox_name(user_id, module_key, target_date)

        if isinstance(payload, str):
            text_payload = payload
        else:
            text_payload = json_dumps(payload, ensure_ascii=False, indent=2)
        snapshot_hash = hashlib.sha256(text_payload.encode("utf-8")).hexdigest()

        metadata = {
            "type": "data_snapshot",
            "module": module_key,
            "source_type": module_key,
            "snapshot_version": self.SNAPSHOT_VERSION,
            "target_date": target_date.isoformat(),
            "snapshot_hash": snapshot_hash,
        }
        if metadata_extra:
            metadata.update(metadata_extra)

        card = Card(content=TextContent(text=text_payload), metadata=metadata)

        existing_hashes = self._load_existing_hashes(tenant_id, box_name)
        if snapshot_hash in existing_hashes:
            return SyncSummary(
                module=module_key,
                cards_added=0,
                skipped=1,
                item_count=item_count,
            )

        cardbox_service.add_cards(tenant_id, box_name, [card])
        return SyncSummary(
            module=module_key,
            cards_added=1,
            skipped=0,
            item_count=item_count,
        )

    def _load_existing_hashes(self, tenant_id: str, box_name: str) -> set[str]:
        # Use cached engine from cardbox_service instead of creating a new one
        engine = cardbox_service._get_engine(tenant_id)
        box = engine.storage_adapter.load_card_box(box_name, tenant_id)
        if box is None:
            return set()

        hashes: set[str] = set()
        for card_id in getattr(box, "card_ids", []):
            card = engine.card_store.get(card_id)
            if card is None:
                continue
            hash_value = card.metadata.get("snapshot_hash")
            if isinstance(hash_value, str):
                hashes.add(hash_value)
        return hashes

    def _resolve_window(
        self,
        target_date: date,
        window: Optional[tuple[datetime, datetime]],
    ) -> tuple[datetime, datetime]:
        if window is not None:
            return window

        start_dt = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
        end_dt = datetime.combine(target_date, time.max, tzinfo=timezone.utc)
        return start_dt, end_dt


cardbox_data_sync_service = CardBoxDataSyncService()

__all__ = ["CardBoxDataSyncService", "cardbox_data_sync_service", "SyncSummary"]
