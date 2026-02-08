"""
统一的工具响应与序列化工具集。

本模块提供结构化的 `ToolResult`，用于替代以往的 JSON 字符串返回值，并保留实体序列化
能力，确保工具层与上层运行时之间的数据契约清晰、可扩展。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.actual_event import ActualEventResponse
from app.schemas.dimension import DimensionResponse
from app.schemas.food import FoodResponse
from app.schemas.food_entry import FoodEntryResponse
from app.schemas.habit import HabitResponse
from app.schemas.note import NoteResponse
from app.schemas.person import PersonResponse, PersonSummaryResponse
from app.schemas.tag import TagResponse
from app.schemas.task import TaskResponse, TaskSummaryResponse
from app.schemas.vision import VisionResponse
from app.serialization import (
    SerializeParams,
    fallback_serialize,
    register_schema,
    serialize,
)
from app.utils.json_encoder import json_dumps


class ToolResult(BaseModel):
    """
    结构化的工具执行结果。

    - status: success / error / validation_error / timeout / 等
    - message: 机器可读的提示信息
    - data: 结构化载荷，供后续 LLM/业务逻辑使用
    - display: 面向用户展示的文本（优先用于上下文追加）
    - error_category: 错误分类，便于统计与治理
    - detail: 更详细的错误描述
    - metrics: 执行指标（例如耗时、重试次数）
    """

    status: str = "success"
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    display: Optional[str] = None
    error_category: Optional[str] = Field(default=None, alias="errorCategory")
    detail: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    audit: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(populate_by_name=True)

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    def to_payload(self) -> Dict[str, Any]:
        """返回用于上下游传递的精简字典。"""
        return self.model_dump(exclude_none=True, by_alias=True)

    def to_content(self) -> str:
        """
        生成追加到对话上下文中的文本表示。
        优先使用 display，其次 message，再次 data+status。
        """
        if self.display:
            return self.display
        if self.message:
            return self.message
        if self.data:
            try:
                payload = {"status": self.status, "data": self.data}
                return json_dumps(payload, ensure_ascii=False)
            except TypeError:
                # 回退为字符串化展示
                return f"{self.status}: {self.data}"
        return self.status


def create_tool_response(
    data: Optional[Dict[str, Any]] = None,
    message: Optional[str] = None,
    status: str = "success",
    *,
    display: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
    audit: Optional[Dict[str, Any]] = None,
) -> ToolResult:
    """构造标准成功响应。"""
    return ToolResult(
        status=status,
        message=message,
        data=data,
        display=display or message,
        metrics=metrics,
        audit=audit,
    )


def create_tool_error(
    message: str,
    kind: str = "error",
    detail: Optional[str] = None,
    *,
    display: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
    audit: Optional[Dict[str, Any]] = None,
) -> ToolResult:
    """构造标准错误响应。"""
    return ToolResult(
        status="error",
        message=message,
        error_category=kind,
        detail=detail,
        display=display or message,
        metrics=metrics,
        audit=audit,
    )


# Schema mapping for common entity types
SCHEMA_MAPPING = {
    "note": NoteResponse,
    "person": PersonResponse,
    "person_summary": PersonSummaryResponse,
    "tag": TagResponse,
    "task": TaskResponse,
    "task_summary": TaskSummaryResponse,
    "habit": HabitResponse,
    "food": FoodResponse,
    "food_entry": FoodEntryResponse,
    "actual_event": ActualEventResponse,
    "vision": VisionResponse,
    "dimension": DimensionResponse,
}


for entity_type, schema in SCHEMA_MAPPING.items():
    register_schema(entity_type, schema)


def serialize_entity(entity: Any, entity_type: str) -> Dict[str, Any]:
    """
    根据实体类型进行序列化。

    Args:
        entity: 待序列化实体
        entity_type: 类型标签，如 note/person 等
    """
    schema_class = SCHEMA_MAPPING.get(entity_type)
    if schema_class:
        result = serialize(entity, entity_type)
        if result is None:
            return {}
        return result  # type: ignore[return-value]

    return fallback_serialize(entity, SerializeParams())
