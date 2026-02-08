from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests


@dataclass
class Tag:
    id: str
    name: str
    entity_type: str


@dataclass
class NoteTagSummary:
    id: str
    name: str


@dataclass
class Note:
    id: str
    content: str
    tags: List[NoteTagSummary]


@dataclass
class Task:
    id: str
    content: str
    vision_id: str
    priority: int
    parent_task_id: Optional[str] = None
    person_ids: Optional[List[str]] = None
    planning_cycle_type: Optional[str] = None
    planning_cycle_days: Optional[int] = None
    planning_cycle_start_date: Optional[str] = None


class ApiClient:
    """通用 API 客户端，封装所有 API 交互逻辑"""

    def __init__(self, session: requests.Session, base_url: str, timeout_s: int = 15):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def _url(self, path: str) -> str:
        """构建完整的 API URL"""
        if path.startswith("/"):
            return f"{self.base_url}{path}"
        return f"{self.base_url}/{path}"

    def _handle_response(self, response: requests.Response, operation: str) -> Dict[str, Any]:
        """统一处理 API 响应"""
        if response.status_code not in (200, 201):
            raise RuntimeError(f"{operation} failed: {response.status_code} {response.text}")
        return response.json() or {}

    # ==================== Tags API ====================

    def get_note_tags(self) -> List[Tag]:
        """获取所有笔记类型的标签"""
        url = self._url("/tags/")
        response = self.session.get(url, params={"entity_type": "note"}, timeout=self.timeout_s)
        data = self._handle_response(response, "Failed to fetch tags")

        result: List[Tag] = []
        for item in data:
            result.append(Tag(
                id=str(item["id"]),
                name=item["name"],
                entity_type=item.get("entity_type", "note")
            ))
        return result

    def create_note_tag(self, name: str) -> Tag:
        """创建新的笔记标签"""
        url = self._url("/tags/")
        payload = {"name": name, "entity_type": "note"}
        response = self.session.post(url, json=payload, timeout=self.timeout_s)
        data = self._handle_response(response, f"Failed to create tag '{name}'")

        return Tag(
            id=str(data["id"]),
            name=data["name"],
            entity_type=data.get("entity_type", "note")
        )

    # ==================== Notes API ====================

    def list_notes_by_tag(self, tag_id: str, limit: int = 50, offset: int = 0) -> List[Note]:
        """按标签获取笔记列表"""
        url = self._url("/notes")
        params = {"tag_id": tag_id, "limit": limit, "offset": offset}
        response = self.session.get(url, params=params, timeout=self.timeout_s)
        data = self._handle_response(response, f"Failed to fetch notes for tag {tag_id}")

        notes: List[Note] = []
        for item in data:
            tags = [NoteTagSummary(id=str(t["id"]), name=t["name"]) for t in item.get("tags", [])]
            notes.append(Note(
                id=str(item["id"]),
                content=item.get("content", ""),
                tags=tags
            ))
        return notes

    def create_note(self, content: str, tag_ids: List[str], task_id: Optional[str] = None) -> Note:
        """创建新笔记"""
        url = self._url("/notes/")
        payload = {
            "content": content,
            "tag_ids": tag_ids
        }
        if task_id is not None:
            payload["task_id"] = task_id

        response = self.session.post(url, json=payload, timeout=self.timeout_s)
        data = self._handle_response(response, "Failed to create note")

        tags = [NoteTagSummary(id=str(t["id"]), name=t["name"]) for t in data.get("tags", [])]
        return Note(
            id=str(data["id"]),
            content=data.get("content", ""),
            tags=tags
        )

    def replace_note_tags(self, note_id: str, tag_ids: List[str]) -> Note:
        """替换笔记的标签（完全覆盖）"""
        url = self._url(f"/notes/{note_id}")
        payload = {"tag_ids": tag_ids}
        response = self.session.put(url, json=payload, timeout=self.timeout_s)
        data = self._handle_response(response, f"Failed to update note {note_id}")

        tags = [NoteTagSummary(id=str(t["id"]), name=t["name"]) for t in data.get("tags", [])]
        return Note(
            id=str(data["id"]),
            content=data.get("content", ""),
            tags=tags
        )

    # ==================== Tasks API ====================

    def create_task(
        self,
        content: str,
        vision_id: str,
        priority: int = 1,
        parent_task_id: Optional[str] = None,
        person_ids: Optional[List[str]] = None,
        planning_cycle_type: Optional[str] = None,
        planning_cycle_days: Optional[int] = None,
        planning_cycle_start_date: Optional[str] = None,
        display_order: int = 0
    ) -> Task:
        """创建新任务"""
        url = self._url("/tasks/")
        payload = {
            "content": content,
            "vision_id": vision_id,
            "priority": priority,
            "display_order": display_order,
            "person_ids": person_ids or []
        }

        # 可选参数
        if parent_task_id is not None:
            payload["parent_task_id"] = parent_task_id
        if planning_cycle_type is not None:
            payload["planning_cycle_type"] = planning_cycle_type
        if planning_cycle_days is not None:
            payload["planning_cycle_days"] = planning_cycle_days
        if planning_cycle_start_date is not None:
            payload["planning_cycle_start_date"] = planning_cycle_start_date

        response = self.session.post(url, json=payload, timeout=self.timeout_s)
        data = self._handle_response(response, "Failed to create task")

        parent_id = data.get("parent_task_id")
        persons = data.get("person_ids", [])
        return Task(
            id=str(data["id"]),
            content=data.get("content", content),
            vision_id=str(data.get("vision_id", vision_id)),
            priority=data.get("priority", priority),
            parent_task_id=str(parent_id) if parent_id is not None else None,
            person_ids=[str(pid) for pid in persons] if persons else [],
            planning_cycle_type=data.get("planning_cycle_type"),
            planning_cycle_days=data.get("planning_cycle_days"),
            planning_cycle_start_date=data.get("planning_cycle_start_date")
        )

    def get_task(self, task_id: str) -> Task:
        """获取单个任务详情"""
        url = self._url(f"/tasks/{task_id}")
        response = self.session.get(url, timeout=self.timeout_s)
        data = self._handle_response(response, f"Failed to fetch task {task_id}")

        parent_id = data.get("parent_task_id")
        persons = data.get("person_ids", [])
        return Task(
            id=str(data["id"]),
            content=data.get("content", ""),
            vision_id=str(data.get("vision_id", "")),
            priority=data.get("priority", 1),
            parent_task_id=str(parent_id) if parent_id is not None else None,
            person_ids=[str(pid) for pid in persons] if persons else [],
            planning_cycle_type=data.get("planning_cycle_type"),
            planning_cycle_days=data.get("planning_cycle_days"),
            planning_cycle_start_date=data.get("planning_cycle_start_date")
        )

    def list_tasks(
        self,
        vision_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Task]:
        """获取任务列表"""
        url = self._url("/tasks/")
        params = {"limit": limit, "offset": offset}

        if vision_id is not None:
            params["vision_id"] = vision_id
        if parent_task_id is not None:
            params["parent_task_id"] = parent_task_id

        response = self.session.get(url, params=params, timeout=self.timeout_s)
        data = self._handle_response(response, "Failed to fetch tasks")

        tasks: List[Task] = []
        for item in data:
            parent_id = item.get("parent_task_id")
            persons = item.get("person_ids", [])
            tasks.append(Task(
                id=str(item["id"]),
                content=item.get("content", ""),
                vision_id=str(item.get("vision_id", "")),
                priority=item.get("priority", 1),
                parent_task_id=str(parent_id) if parent_id is not None else None,
                person_ids=[str(pid) for pid in persons] if persons else [],
                planning_cycle_type=item.get("planning_cycle_type"),
                planning_cycle_days=item.get("planning_cycle_days"),
                planning_cycle_start_date=item.get("planning_cycle_start_date")
            ))
        return tasks
