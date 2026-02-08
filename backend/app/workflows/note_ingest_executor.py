"""Executor that converts extraction JSON into concrete entity operations."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.habit import Habit
from app.db.models.person import Person
from app.db.models.tag import Tag
from app.db.models.task import Task
from app.db.models.vision import Vision
from app.handlers import habits as habit_service
from app.handlers import notes as note_service
from app.handlers import persons as person_service
from app.handlers import tags as tag_service
from app.handlers import tasks as task_service
from app.handlers import visions as vision_service
from app.handlers.habits import ValidationError as HabitValidationError
from app.handlers.tasks import VisionNotFoundError
from app.handlers.visions import VisionAlreadyExistsError
from app.schemas.entity_ingest import EntityExtraction
from app.schemas.habit import HabitCreate
from app.schemas.note import NoteUpdate
from app.schemas.person import PersonCreate
from app.schemas.tag import TagCreate
from app.schemas.task import TaskCreate
from app.schemas.vision import VisionCreate

logger = get_logger(__name__)


class NoteIngestExecutor:
    """Apply `EntityExtraction` instructions to the database."""

    async def execute(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        note_id: UUID,
        extraction: EntityExtraction,
    ) -> Dict[str, Any]:
        state = _ExecutionState(
            db=db,
            user_id=user_id,
            note_id=note_id,
            extraction=extraction,
        )
        return await state.run()


class _ExecutionState:
    def __init__(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        note_id: UUID,
        extraction: EntityExtraction,
    ) -> None:
        self.db = db
        self.user_id = user_id
        self.note_id = note_id
        self.extraction = extraction
        self.tag_cache: Dict[tuple[str, str], UUID] = {}
        self.person_refs: Dict[str, UUID] = {}
        self.vision_refs: Dict[str, UUID] = {}
        self.task_refs: Dict[str, UUID] = {}
        self.habit_refs: Dict[str, UUID] = {}
        self.primary_task_id: Optional[UUID] = None
        self.ingested_person_ids: list[UUID] = []
        self.summary: Dict[str, Any] = {
            "tags": {"created": 0, "reused": 0},
            "persons": {"created": 0, "reused": 0},
            "visions": {"created": 0, "reused": 0},
            "tasks": {"created": 0, "reused": 0},
            "habits": {"created": 0, "reused": 0},
            "note_updated": False,
        }

    async def run(self) -> Dict[str, Any]:
        await self._ingest_declared_tags()
        await self._ingest_persons()
        await self._ingest_visions()
        await self._ingest_tasks()
        await self._ingest_habits()
        await self._update_note()
        return self.summary

    # --------------------- entity ingestion helpers ---------------------
    async def _ingest_declared_tags(self) -> None:
        for draft in self.extraction.tags or []:
            await self._ensure_tag(draft.name, draft.entity_type or "general")

    async def _ingest_persons(self) -> None:
        for draft in self.extraction.persons or []:
            person_id = await self._get_or_create_person(draft)
            if person_id:
                self._remember_person_ref(person_id, draft.ref)
                if person_id not in self.ingested_person_ids:
                    self.ingested_person_ids.append(person_id)

    async def _ingest_visions(self) -> None:
        for draft in self.extraction.visions or []:
            vision_id = await self._get_or_create_vision(draft)
            if draft.ref and vision_id:
                self.vision_refs[draft.ref] = vision_id

    async def _ingest_tasks(self) -> None:
        for draft in self.extraction.tasks or []:
            task_id = await self._get_or_create_task(draft)
            if task_id:
                self._remember_task_ref(task_id, draft.ref)
                if self.primary_task_id is None:
                    self.primary_task_id = task_id

    async def _ingest_habits(self) -> None:
        for draft in self.extraction.habits or []:
            habit_id = await self._get_or_create_habit(draft)
            if draft.ref and habit_id:
                self.habit_refs[draft.ref] = habit_id

    # --------------------- tag helpers ---------------------
    async def _ensure_tag(
        self, name: Optional[str], entity_type: str
    ) -> Optional[UUID]:
        if not name:
            return None
        key = (name.strip().lower(), entity_type or "general")
        cached = self.tag_cache.get(key)
        if cached:
            return cached

        stmt = (
            select(Tag)
            .where(
                Tag.user_id == self.user_id,
                Tag.deleted_at.is_(None),
                Tag.name == key[0],
                Tag.entity_type == key[1],
            )
            .limit(1)
        )
        existing = (await self.db.execute(stmt)).scalars().first()
        if existing:
            self.summary["tags"]["reused"] += 1
            self.tag_cache[key] = existing.id
            return existing.id

        try:
            created = await tag_service.create_tag(
                self.db,
                user_id=self.user_id,
                tag_in=TagCreate(name=name, entity_type=key[1]),
            )
            self.summary["tags"]["created"] += 1
            self.tag_cache[key] = created.id
            return created.id
        except Exception:  # pragma: no cover - defensive log
            logger.warning("Failed to create tag name=%s", name, exc_info=True)
            return None

    # --------------------- person helpers ---------------------
    def _remember_person_ref(self, person_id: UUID, ref: Optional[str] = None) -> None:
        if ref:
            self.person_refs[ref] = person_id
        self.person_refs[str(person_id)] = person_id

    async def _resolve_person_ref(self, ref: Optional[str]) -> Optional[UUID]:
        if not ref:
            return None
        cached = self.person_refs.get(ref)
        if cached:
            return cached
        try:
            candidate = UUID(str(ref))
        except (ValueError, TypeError):
            return None
        stmt = (
            select(Person.id)
            .where(
                Person.user_id == self.user_id,
                Person.deleted_at.is_(None),
                Person.id == candidate,
            )
            .limit(1)
        )
        person_id = (await self.db.execute(stmt)).scalar_one_or_none()
        if person_id:
            self._remember_person_ref(candidate, ref)
            return candidate
        return None

    async def _resolve_person_ids(self, refs: Optional[list[str]]) -> list[UUID]:
        resolved: list[UUID] = []
        for ref in refs or []:
            person_id = await self._resolve_person_ref(ref)
            if person_id:
                resolved.append(person_id)
        return resolved

    def _remember_task_ref(self, task_id: UUID, ref: Optional[str] = None) -> None:
        if ref:
            self.task_refs[ref] = task_id
        self.task_refs[str(task_id)] = task_id

    async def _resolve_task_ref(self, ref: Optional[str]) -> Optional[UUID]:
        if not ref:
            return None
        cached = self.task_refs.get(ref)
        if cached:
            return cached
        try:
            candidate = UUID(str(ref))
        except (ValueError, TypeError):
            return None
        stmt = (
            select(Task.id)
            .where(
                Task.user_id == self.user_id,
                Task.deleted_at.is_(None),
                Task.id == candidate,
            )
            .limit(1)
        )
        task_id = (await self.db.execute(stmt)).scalar_one_or_none()
        if task_id:
            self._remember_task_ref(task_id, ref)
            return task_id
        return None

    async def _get_or_create_person(self, draft) -> Optional[UUID]:
        name = draft.name or (draft.nicknames[0] if draft.nicknames else None)
        if not name:
            return None
        normalized = name.strip().lower()
        stmt = (
            select(Person)
            .where(
                Person.user_id == self.user_id,
                Person.deleted_at.is_(None),
                func.lower(Person.name) == normalized,
            )
            .limit(1)
        )
        existing = (await self.db.execute(stmt)).scalars().first()

        nickname_tokens = {
            nick.strip().lower()
            for nick in draft.nicknames or []
            if nick and nick.strip()
        }
        if existing is None and nickname_tokens:
            stmt = select(Person).where(
                Person.user_id == self.user_id,
                Person.deleted_at.is_(None),
                Person.nicknames.isnot(None),
            )
            candidates = (await self.db.execute(stmt)).scalars().all()
            for candidate in candidates:
                for candidate_nick in candidate.nicknames or []:
                    if (
                        isinstance(candidate_nick, str)
                        and candidate_nick.strip().lower() in nickname_tokens
                    ):
                        existing = candidate
                        break
                if existing:
                    break
        if existing:
            self.summary["persons"]["reused"] += 1
            self._remember_person_ref(existing.id, draft.ref)
            return existing.id

        payload = PersonCreate(
            name=name,
            nicknames=draft.nicknames or None,
            birth_date=draft.birth_date,
            location=draft.location,
            tag_ids=None,
        )
        try:
            person = await person_service.create_person(
                self.db, user_id=self.user_id, person_in=payload
            )
            self.summary["persons"]["created"] += 1
            self._remember_person_ref(person.id, draft.ref)
            return person.id
        except Exception:
            logger.warning("Failed to create person name=%s", name, exc_info=True)
            return None

    # --------------------- vision helpers ---------------------
    async def _get_or_create_vision(self, draft) -> Optional[UUID]:
        name = draft.name.strip() if draft.name else None
        if not name:
            return None
        normalized = name.lower()
        stmt = (
            select(Vision)
            .where(
                Vision.user_id == self.user_id,
                Vision.deleted_at.is_(None),
                func.lower(Vision.name) == normalized,
            )
            .limit(1)
        )
        existing = (await self.db.execute(stmt)).scalars().first()
        if existing:
            self.summary["visions"]["reused"] += 1
            return existing.id

        payload = VisionCreate(
            name=name,
            description=draft.description,
            person_ids=None,
        )
        try:
            vision = await vision_service.create_vision(
                self.db, user_id=self.user_id, vision_in=payload
            )
            self.summary["visions"]["created"] += 1
            return vision.id
        except VisionAlreadyExistsError:
            refreshed = (await self.db.execute(stmt)).scalars().first()
            if refreshed:
                self.summary["visions"]["reused"] += 1
                return refreshed.id
            logger.warning(
                "Vision unexpectedly missing after duplicate error: %s", name
            )
        except Exception:
            logger.warning("Failed to create vision %s", name, exc_info=True)
        return None

    async def _resolve_default_vision_id(self) -> Optional[UUID]:
        stmt = (
            select(Vision)
            .where(
                Vision.user_id == self.user_id,
                Vision.deleted_at.is_(None),
                func.lower(Vision.name) == "todos inbox",
            )
            .limit(1)
        )
        inbox = (await self.db.execute(stmt)).scalars().first()
        if inbox:
            return inbox.id
        try:
            created = await vision_service.create_vision(
                self.db,
                user_id=self.user_id,
                vision_in=VisionCreate(name="Todos Inbox"),
            )
            self.summary["visions"]["created"] += 1
            return created.id
        except Exception:
            logger.warning("Failed to create default vision", exc_info=True)
            return None

    # --------------------- task helpers ---------------------
    async def _get_or_create_task(self, draft) -> Optional[UUID]:
        content = draft.content.strip() if draft.content else None
        if not content:
            return None
        if draft.vision_ref and draft.vision_ref in self.vision_refs:
            vision_id = self.vision_refs[draft.vision_ref]
        else:
            vision_id = await self._resolve_default_vision_id()
        if vision_id is None:
            return None

        stmt = (
            select(Task)
            .where(
                Task.user_id == self.user_id,
                Task.deleted_at.is_(None),
                Task.vision_id == vision_id,
                func.lower(Task.content) == content.lower(),
            )
            .limit(1)
        )
        existing = (await self.db.execute(stmt)).scalars().first()
        if existing:
            self.summary["tasks"]["reused"] += 1
            self._remember_task_ref(existing.id, draft.ref)
            return existing.id

        person_ids = await self._resolve_person_ids(draft.person_refs)
        payload = TaskCreate(
            content=content,
            vision_id=vision_id,
            person_ids=[str(pid) for pid in person_ids] or None,
        )
        try:
            task = await task_service.create_task(
                self.db,
                user_id=self.user_id,
                task_data=payload,
                run_async=False,
            )
            self.summary["tasks"]["created"] += 1
            self._remember_task_ref(task.id, draft.ref)
            return task.id
        except VisionNotFoundError:
            logger.warning("Vision not found when creating task", exc_info=True)
        except Exception:
            logger.warning("Failed to create task", exc_info=True)
        return None

    # --------------------- habit helpers ---------------------
    async def _get_or_create_habit(self, draft) -> Optional[UUID]:
        title = draft.title.strip() if draft.title else None
        if not title:
            return None
        # Dedup by title + task
        stmt = select(Habit).where(
            Habit.user_id == self.user_id,
            Habit.deleted_at.is_(None),
            func.lower(Habit.title) == title.lower(),
        )
        resolved_task_id = await self._resolve_task_ref(draft.task_ref)
        if resolved_task_id:
            stmt = stmt.where(Habit.task_id == resolved_task_id)
        existing = (await self.db.execute(stmt.limit(1))).scalars().first()
        if existing:
            self.summary["habits"]["reused"] += 1
            return existing.id

        start_date = self._parse_date(draft.start_date) or date.today()
        allowed_durations = {5, 7, 14, 21, 100, 365, 1000}
        duration_days = (
            draft.duration_days if draft.duration_days in allowed_durations else 21
        )
        payload = HabitCreate(
            title=title,
            description=draft.description,
            start_date=start_date,
            duration_days=duration_days,
            task_id=resolved_task_id,
        )
        try:
            habit = await habit_service.create_habit(
                self.db, user_id=self.user_id, habit_in=payload
            )
            self.summary["habits"]["created"] += 1
            return habit.id
        except (HabitValidationError, ValueError):
            logger.warning("Habit validation failed for %s", title, exc_info=True)
        except Exception:
            logger.warning("Failed to create habit %s", title, exc_info=True)
        return None

    @staticmethod
    def _parse_date(candidate: Optional[str]) -> Optional[date]:
        if not candidate:
            return None
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            return None

    # --------------------- note update ---------------------
    async def _update_note(self) -> None:
        note_spec = getattr(self.extraction, "note", None)
        if note_spec is None:
            return
        note_tags = [
            await self._ensure_tag(name, "note") for name in (note_spec.tags or [])
        ]
        note_tag_ids = [tid for tid in note_tags if tid]
        note_person_ids = await self._resolve_person_ids(note_spec.person_refs)
        if not note_person_ids and self.ingested_person_ids:
            note_person_ids = list(self.ingested_person_ids)
        task_id = await self._resolve_task_ref(note_spec.task_ref)
        if task_id is None and self.primary_task_id:
            task_id = self.primary_task_id
        update_payload = NoteUpdate(
            person_ids=[str(pid) for pid in note_person_ids] or None,
            tag_ids=[str(tid) for tid in note_tag_ids] or None,
            task_id=task_id,
        )
        if (
            update_payload.person_ids
            or update_payload.tag_ids
            or update_payload.task_id
        ):
            try:
                await note_service.update_note(
                    self.db,
                    user_id=self.user_id,
                    note_id=self.note_id,
                    note_in=update_payload,
                )
                self.summary["note_updated"] = True
            except Exception:
                logger.warning(
                    "Failed to update note associations note_id=%s",
                    self.note_id,
                    exc_info=True,
                )


note_ingest_executor = NoteIngestExecutor()

__all__ = ["note_ingest_executor"]
