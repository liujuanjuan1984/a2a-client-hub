"""LLM extraction service for note auto-ingest jobs."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from litellm import exceptions as litellm_exceptions
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.llm import llm_client
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.note import Note
from app.db.models.person import Person
from app.db.models.tag import Tag
from app.db.models.task import Task
from app.db.models.vision import Vision
from app.schemas.entity_ingest import EntityExtraction

logger = get_logger(__name__)


class NoteIngestExtractionError(RuntimeError):
    """Raised when the extractor fails to build a valid EntityExtraction."""


@dataclass(slots=True)
class ExtractionResult:
    """Container for LLM extraction output and token usage."""

    extraction: EntityExtraction
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: Optional[Decimal] = None


class NoteIngestExtractor:
    """Invoke LiteLLM once to convert笔记 into structured实体说明。"""

    _MAX_CANDIDATES = 20
    _MAX_ATTEMPTS = 3
    _NETWORK_RETRY_ATTEMPTS = 2
    _NETWORK_RETRY_BASE_DELAY_SECONDS = 1.5
    _RETRYABLE_ERRORS = (
        litellm_exceptions.Timeout,
        httpx.TimeoutException,
        asyncio.TimeoutError,
    )

    def __init__(self) -> None:
        self._schema_json = json.dumps(
            EntityExtraction.model_json_schema(), ensure_ascii=False, indent=2
        )

    async def extract(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        note_id: UUID,
    ) -> ExtractionResult:
        note = await self._load_note(db, user_id=user_id, note_id=note_id)
        context = await self._load_context(db, user_id=user_id)
        feedback: Optional[str] = None
        last_error: Optional[str] = None
        response = None

        for attempt in range(1, self._MAX_ATTEMPTS + 1):
            messages = self._build_messages(note.content, context, feedback)
            response = await self._completion_with_retry(
                note_id=note_id,
                user_id=user_id,
                messages=messages,
                metadata={
                    "module": "note_auto_ingest",
                    "note_id": str(note_id),
                    "user_id": str(user_id),
                },
                temperature=settings.litellm_temperature,
                max_tokens=min(settings.litellm_completion_max_tokens, 2000),
                response_format={"type": "json_object"},
            )

            payload = self._parse_completion(response)
            try:
                extraction = EntityExtraction.model_validate(payload)
            except ValidationError as exc:  # pragma: no cover - defensive
                last_error = f"Schema validation failed: {exc}"
                feedback = self._format_validation_feedback(exc)
                continue

            rule_errors = self._check_business_rules(extraction)
            if not rule_errors:
                break

            last_error = "; ".join(rule_errors)
            feedback = self._format_rule_feedback(rule_errors)
        else:
            raise NoteIngestExtractionError(
                f"LLM failed to satisfy extraction rules after {self._MAX_ATTEMPTS} attempts: {last_error}"
            )

        usage = getattr(response, "usage", None) or {}
        prompt_tokens = int(
            getattr(usage, "prompt_tokens", 0) or usage.get("prompt_tokens", 0) or 0
        )
        completion_tokens = int(
            getattr(usage, "completion_tokens", 0)
            or usage.get("completion_tokens", 0)
            or 0
        )
        total_tokens = int(
            getattr(usage, "total_tokens", 0)
            or usage.get("total_tokens", 0)
            or (prompt_tokens + completion_tokens)
        )
        cost_usd: Optional[Decimal] = None
        cost_value = getattr(usage, "cost", None) or usage.get("cost")
        if cost_value is not None:
            cost_usd = Decimal(str(cost_value))

        return ExtractionResult(
            extraction=extraction,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
        )

    async def _completion_with_retry(
        self, *, note_id: UUID, user_id: UUID, **params: Any
    ) -> Any:
        attempts = self._NETWORK_RETRY_ATTEMPTS + 1
        last_error: Optional[Exception] = None

        for attempt in range(1, attempts + 1):
            try:
                return await llm_client.completion(**params)
            except self._RETRYABLE_ERRORS as exc:  # pragma: no cover - network flake
                last_error = exc
                logger.warning(
                    "LLM completion transport error user=%s note=%s attempt=%s/%s err=%s",
                    user_id,
                    note_id,
                    attempt,
                    attempts,
                    exc,
                )
                if attempt >= attempts:
                    break
                delay = min(
                    self._NETWORK_RETRY_BASE_DELAY_SECONDS * attempt,
                    self._NETWORK_RETRY_BASE_DELAY_SECONDS
                    * self._NETWORK_RETRY_ATTEMPTS,
                )
                if delay > 0:
                    await asyncio.sleep(delay)

        message = "LLM transport failed after retries"
        if last_error is not None:
            message = f"{message}: {last_error}"
        raise NoteIngestExtractionError(message) from last_error

    async def _load_note(
        self, db: AsyncSession, *, user_id: UUID, note_id: UUID
    ) -> Note:
        stmt = (
            select(Note)
            .where(
                Note.user_id == user_id,
                Note.id == note_id,
                Note.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        note = result.scalars().first()
        if note is None:
            raise NoteIngestExtractionError(
                "Note not found or deleted before ingestion"
            )
        return note

    async def _load_context(
        self, db: AsyncSession, *, user_id: UUID
    ) -> Dict[str, List[Dict[str, Any]]]:
        persons_stmt = (
            select(Person)
            .options(selectinload(Person.tags))
            .where(Person.user_id == user_id, Person.deleted_at.is_(None))
            .order_by(Person.updated_at.desc())
            .limit(self._MAX_CANDIDATES)
        )
        tags_stmt = (
            select(Tag)
            .where(Tag.user_id == user_id, Tag.deleted_at.is_(None))
            .order_by(Tag.updated_at.desc())
            .limit(self._MAX_CANDIDATES)
        )
        visions_stmt = (
            select(Vision)
            .where(Vision.user_id == user_id, Vision.deleted_at.is_(None))
            .order_by(Vision.updated_at.desc())
            .limit(self._MAX_CANDIDATES)
        )
        tasks_stmt = (
            select(Task)
            .where(Task.user_id == user_id, Task.deleted_at.is_(None))
            .order_by(Task.updated_at.desc())
            .limit(self._MAX_CANDIDATES)
        )

        persons_result = await db.execute(persons_stmt)
        tags_result = await db.execute(tags_stmt)
        visions_result = await db.execute(visions_stmt)
        tasks_result = await db.execute(tasks_stmt)

        persons = persons_result.scalars().all()
        tags = tags_result.scalars().all()
        visions = visions_result.scalars().all()
        tasks = tasks_result.scalars().all()

        return {
            "persons": [self._summarize_person(person) for person in persons],
            "tags": [self._summarize_tag(tag) for tag in tags],
            "visions": [self._summarize_vision(vision) for vision in visions],
            "tasks": [self._summarize_task(task) for task in tasks],
        }

    @staticmethod
    def _summarize_person(person: Person) -> Dict[str, Any]:
        tags = getattr(person, "tags", []) or []
        tag_names = [
            getattr(tag, "name", "") for tag in tags if getattr(tag, "name", None)
        ]
        return {
            "id": str(person.id),
            "name": getattr(person, "name", None),
            "nicknames": getattr(person, "nicknames", []) or [],
            "tags": tag_names,
        }

    @staticmethod
    def _summarize_tag(tag: Tag) -> Dict[str, Any]:
        return {
            "id": str(tag.id),
            "name": tag.name,
            "entity_type": tag.entity_type,
        }

    @staticmethod
    def _summarize_vision(vision: Vision) -> Dict[str, Any]:
        return {
            "id": str(vision.id),
            "name": vision.name,
            "status": vision.status,
        }

    @staticmethod
    def _summarize_task(task: Task) -> Dict[str, Any]:
        return {
            "id": str(task.id),
            "content": task.content,
            "vision_id": str(task.vision_id) if task.vision_id else None,
            "status": task.status,
        }

    def _build_messages(
        self,
        note_content: str,
        context: Dict[str, List[Dict[str, Any]]],
        feedback: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        system_prompt = (
            "你是结构化助手，负责把用户的笔记拆解成 JSON。遵守以下规则：\n"
            "1. 始终输出符合 EntityExtraction schema 的 JSON，不要加解释。\n"
            "2. 若某些实体在候选列表中不存在，可以直接创建。\n"
            "3. note.content 必须是原文，不得改写。\n"
            "4. 无法确定的字段请省略。\n"
            "5. 严格按照下列流程在心中推理后再输出 JSON：\n"
            "   步骤1（标签）: 至少提炼 1 个且至多 3 个 note.tags，优先选择最能概括内容的关键词；若确实无法给出标签，请在内部说明原因再重新思考——不允许输出空数组。\n"
            "   步骤2（实体拆解）: 根据文本决定是否需要 visions/tasks/habits/persons/tags；引用 ID 时可以使用上文 context 中的候选，也可以创建新实体并分配 ref。\n"
            "   步骤3（自检）: 输出前自查 note.tags 数量是否在 1-3 范围、refs 是否可解析、JSON 是否满足 schema，若发现问题必须修正后再输出。"
        )
        context_section = json.dumps(context, ensure_ascii=False, indent=2)
        user_prompt = (
            f"# 用户笔记\n{note_content}\n\n"
            f"# 现有实体候选\n{context_section}\n\n"
            f"# 输出 JSON Schema\n{self._schema_json}\n"
        )
        if feedback:
            user_prompt += "\n# 修正反馈\n" f"{feedback}\n" "请根据上述反馈重新生成完全合规的 JSON。"
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def _check_business_rules(extraction: EntityExtraction) -> List[str]:
        errors: List[str] = []
        tags = extraction.note.tags or []
        if len(tags) < 1:
            errors.append("note.tags 必须包含 1~3 个条目，当前为空")
        elif len(tags) > 3:
            errors.append(f"note.tags 最多 3 个，当前为 {len(tags)} 个")
        return errors

    @staticmethod
    def _format_validation_feedback(exc: ValidationError) -> str:
        messages = []
        for error in exc.errors():
            loc = ".".join(str(part) for part in error.get("loc", []))
            messages.append(f"{loc}: {error.get('msg', '')}")
        return "上一次输出未通过 JSON Schema 校验：" + (
            "; ".join(messages) if messages else str(exc)
        )

    @staticmethod
    def _format_rule_feedback(errors: List[str]) -> str:
        joined = "；".join(errors)
        return "上一次输出违反业务约束：" f"{joined}。请修正后重新输出符合 schema 的 JSON。"

    def _parse_completion(self, response: Any) -> Dict[str, Any]:
        choices = getattr(response, "choices", None)
        if choices is None and isinstance(response, dict):
            choices = response.get("choices")
        choices = choices or []
        if not choices:
            raise NoteIngestExtractionError("LLM returned empty choices")
        first = choices[0]
        message = getattr(first, "message", None)
        if message is None and isinstance(first, dict):
            message = first.get("message", {})
        message = message or {}

        structured_payload = self._extract_structured_payload(message)
        if structured_payload is not None:
            return structured_payload

        raw_content = self._message_attr(message, "content")
        content = self._coerce_text_content(raw_content)

        if not content:
            refusal = self._message_attr(message, "refusal")
            if refusal:
                raise NoteIngestExtractionError(
                    f"LLM refused to return extraction JSON: {refusal}"
                )
            raise NoteIngestExtractionError("LLM completion missing content")

        logger.debug(
            "LLM extraction raw content: %s",
            (content[:500] + "...") if len(content) > 500 else content,
        )

        try:
            payload = json.loads(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LLM extraction non-JSON output: %s",
                (content[:500] + "...") if len(content) > 500 else content,
            )
            raise NoteIngestExtractionError(
                f"Failed to parse LLM output: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise NoteIngestExtractionError("LLM output必须是JSON对象")

        return payload

    @staticmethod
    def _message_attr(message: Any, attr: str) -> Any:
        if message is None:
            return None
        if isinstance(message, dict):
            return message.get(attr)
        return getattr(message, attr, None)

    def _extract_structured_payload(self, message: Any) -> Optional[Dict[str, Any]]:
        for attr in (
            "parsed",
            "parsed_output",
            "parsed_response",
            "parsed_json",
            "parsed_data",
        ):
            candidate = self._message_attr(message, attr)
            normalized = self._normalize_structured_payload(candidate)
            if normalized is not None:
                return normalized
        return None

    @staticmethod
    def _normalize_structured_payload(candidate: Any) -> Optional[Dict[str, Any]]:
        if candidate is None:
            return None

        if isinstance(candidate, EntityExtraction):
            return candidate.model_dump(mode="json")

        model_dump = getattr(candidate, "model_dump", None)
        if callable(model_dump):
            try:
                return model_dump(mode="json")
            except TypeError:
                return model_dump()

        dict_method = getattr(candidate, "dict", None)
        if callable(dict_method):
            return dict_method()

        to_dict = getattr(candidate, "to_dict", None)
        if callable(to_dict):
            return to_dict()

        if isinstance(candidate, str):
            stripped = candidate.strip()
            if not stripped:
                return None
            try:
                parsed = json.loads(stripped)
            except Exception:  # noqa: BLE001
                return None
            return parsed if isinstance(parsed, dict) else None

        if isinstance(candidate, dict):
            return candidate

        return None

    def _coerce_text_content(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: List[str] = []
            for chunk in content:
                text = self._chunk_text(chunk)
                if text:
                    parts.append(text)
            return "".join(parts).strip()
        if isinstance(content, dict):
            if "content" in content:
                return self._coerce_text_content(content["content"])
            if isinstance(content.get("text"), str):
                return str(content["text"]).strip()
            return json.dumps(content, ensure_ascii=False)

        text_attr = getattr(content, "text", None)
        if isinstance(text_attr, str):
            return text_attr.strip()

        nested_content = getattr(content, "content", None)
        if nested_content is not None:
            return self._coerce_text_content(nested_content)

        return str(content).strip()

    @staticmethod
    def _chunk_text(chunk: Any) -> str:
        if chunk is None:
            return ""
        if isinstance(chunk, str):
            return chunk
        if isinstance(chunk, dict):
            for key in ("text", "content", "value", "data"):
                value = chunk.get(key)
                if isinstance(value, str):
                    return value
            return ""

        text_attr = getattr(chunk, "text", None)
        if isinstance(text_attr, str):
            return text_attr

        content_attr = getattr(chunk, "content", None)
        if isinstance(content_attr, str):
            return content_attr

        return ""


note_ingest_extractor = NoteIngestExtractor()

__all__ = [
    "note_ingest_extractor",
    "ExtractionResult",
    "NoteIngestExtractionError",
]
