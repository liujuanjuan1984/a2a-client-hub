"""Note reference data caching and resolution for note-related agent tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.person import Person
from app.db.models.tag import Tag
from app.db.models.task import Task
from app.utils.json_encoder import json_dumps
from app.utils.timezone_util import utc_now

NOTE_METADATA_TTL = timedelta(minutes=60)
MAX_TAGS = 120
MAX_TASKS = 120
MAX_PERSONS = 120
NOTE_TOOL_NAMES = {"create_note", "update_note"}


@dataclass
class _CacheEntry:
    data: "NoteReferenceData"
    fetched_at: datetime


@dataclass
class NoteReferenceData:
    tags: List[Dict[str, Any]]
    tasks: List[Dict[str, Any]]
    persons: List[Dict[str, Any]]

    def as_compact_json(self) -> str:
        payload = {
            "tags": self.tags,
            "tasks": self.tasks,
            "persons": self.persons,
        }
        return json_dumps(payload, ensure_ascii=False, separators=(",", ":"))


class NoteReferenceLookup:
    def __init__(self, data: NoteReferenceData) -> None:
        self.tag_ids: Dict[str, str] = {}
        self.person_ids: Dict[str, str] = {}
        self.task_ids: Dict[str, str] = {}

        for item in data.tags:
            name = item.get("name")
            tag_id = item.get("id")
            if not name or not tag_id:
                continue
            self.tag_ids[name.strip().lower()] = tag_id

        for item in data.persons:
            person_id = item.get("id")
            if not person_id:
                continue
            name = (item.get("name") or "").strip()
            if name:
                self.person_ids[name.lower()] = person_id
            for nickname in item.get("nicknames") or []:
                if nickname:
                    self.person_ids[nickname.strip().lower()] = person_id

        for item in data.tasks:
            task_id = item.get("id")
            title = item.get("title")
            if task_id and title:
                self.task_ids[title.strip().lower()] = task_id

    @staticmethod
    def _is_uuid(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        try:
            UUID(value)
        except (ValueError, TypeError):
            return False
        return True

    def resolve_tag(self, value: str) -> Optional[str]:
        if self._is_uuid(value):
            return value
        return self.tag_ids.get(value.strip().lower())

    def resolve_person(self, value: str) -> Optional[str]:
        if self._is_uuid(value):
            return value
        return self.person_ids.get(value.strip().lower())

    def resolve_task(self, value: str) -> Optional[str]:
        if self._is_uuid(value):
            return value
        return self.task_ids.get(value.strip().lower())


class NoteReferenceResolutionError(Exception):
    def __init__(self, detail: Dict[str, Any]) -> None:
        super().__init__("Failed to resolve note reference identifiers")
        self.detail = detail


class NoteReferenceService:
    def __init__(self) -> None:
        self._cache: Dict[Tuple[UUID, Optional[UUID]], _CacheEntry] = {}

    async def get_reference_data(
        self,
        db: AsyncSession,
        user_id: UUID,
        session_id: Optional[UUID],
    ) -> NoteReferenceData:
        key = (user_id, session_id)
        now = utc_now()
        entry = self._cache.get(key)
        if entry and now - entry.fetched_at < NOTE_METADATA_TTL:
            return entry.data

        data = await self._load_reference_data(db, user_id)
        self._cache[key] = _CacheEntry(data=data, fetched_at=now)
        return data

    def build_prompt_message(
        self,
        data: NoteReferenceData,
        fetched_at: Optional[datetime] = None,
    ) -> str:
        timestamp = (fetched_at or utc_now()).isoformat()
        return (
            "Note reference snapshot (" + timestamp + ")\n"
            "Use ONLY the names listed here when choosing tags, persons, or tasks. "
            "Tool arguments must use the corresponding IDs.\n" + data.as_compact_json()
        )

    def build_lookup(self, data: NoteReferenceData) -> NoteReferenceLookup:
        return NoteReferenceLookup(data)

    def resolve_tool_arguments(
        self,
        function_name: str,
        arguments: Dict[str, Any],
        lookup: NoteReferenceLookup,
    ) -> Dict[str, Any]:
        if function_name not in NOTE_TOOL_NAMES:
            return arguments

        resolved = dict(arguments)
        issues: Dict[str, List[str]] = {}

        tag_values = resolved.get("tag_ids")
        if isinstance(tag_values, list):
            resolved_tags: List[str] = []
            unresolved: List[str] = []
            for value in tag_values:
                if not isinstance(value, str):
                    continue
                mapped = lookup.resolve_tag(value)
                if mapped:
                    resolved_tags.append(mapped)
                else:
                    unresolved.append(value)
            if unresolved:
                issues["tag_ids"] = unresolved
            resolved["tag_ids"] = resolved_tags

        person_values = resolved.get("person_ids")
        if isinstance(person_values, list):
            resolved_persons: List[str] = []
            unresolved_persons: List[str] = []
            for value in person_values:
                if not isinstance(value, str):
                    continue
                mapped = lookup.resolve_person(value)
                if mapped:
                    resolved_persons.append(mapped)
                else:
                    unresolved_persons.append(value)
            if unresolved_persons:
                issues["person_ids"] = unresolved_persons
            resolved["person_ids"] = resolved_persons

        task_value = resolved.get("task_id")
        if isinstance(task_value, str):
            mapped_task = lookup.resolve_task(task_value)
            if mapped_task:
                resolved["task_id"] = mapped_task
            else:
                issues["task_id"] = [task_value]

        if issues:
            detail = {
                "unresolved_fields": issues,
                "hint": "请选择上方提供的名称，或先创建新的标签/联系人/任务后再尝试。",
            }
            raise NoteReferenceResolutionError(detail)

        return resolved

    async def _load_reference_data(
        self, db: AsyncSession, user_id: UUID
    ) -> NoteReferenceData:
        tags = await self._load_tags(db, user_id)
        tasks = await self._load_tasks(db, user_id)
        persons = await self._load_persons(db, user_id)
        return NoteReferenceData(tags=tags, tasks=tasks, persons=persons)

    async def _load_tags(self, db: AsyncSession, user_id: UUID) -> List[Dict[str, Any]]:
        stmt = (
            select(Tag.id, Tag.name, Tag.entity_type)
            .where(Tag.user_id == user_id, Tag.deleted_at.is_(None))
            .order_by(Tag.updated_at.desc())
            .limit(MAX_TAGS)
        )
        result = await db.execute(stmt)
        rows = result.all()
        return [
            {"id": str(row.id), "name": row.name, "entity_type": row.entity_type}
            for row in rows
            if row.name
        ]

    async def _load_tasks(
        self, db: AsyncSession, user_id: UUID
    ) -> List[Dict[str, Any]]:
        stmt = (
            select(Task.id, Task.content, Task.status)
            .where(Task.user_id == user_id, Task.deleted_at.is_(None))
            .order_by(Task.updated_at.desc())
            .limit(MAX_TASKS)
        )
        result = await db.execute(stmt)
        rows = result.all()
        return [
            {
                "id": str(row.id),
                "title": row.content,
                "status": row.status,
            }
            for row in rows
            if row.content
        ]

    async def _load_persons(
        self, db: AsyncSession, user_id: UUID
    ) -> List[Dict[str, Any]]:
        stmt = (
            select(Person)
            .options(selectinload(Person.tags))
            .where(Person.user_id == user_id, Person.deleted_at.is_(None))
            .order_by(Person.updated_at.desc())
            .limit(MAX_PERSONS)
        )
        result = await db.execute(stmt)
        persons = result.scalars().all()
        payload: List[Dict[str, Any]] = []
        for person in persons:
            tag_names = [tag.name for tag in person.tags if tag and tag.name]
            nicknames = [alias for alias in (person.nicknames or []) if alias]
            payload.append(
                {
                    "id": str(person.id),
                    "name": person.name or "",
                    "nicknames": nicknames,
                    "tags": tag_names,
                }
            )
        return payload


note_reference_service = NoteReferenceService()
