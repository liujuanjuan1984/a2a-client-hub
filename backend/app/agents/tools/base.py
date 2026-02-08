"""
Tool 基础抽象。

新增异步执行与元数据支持，以便上层运行时实现智能调度、观察与治理。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Type
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.responses import ToolResult


@dataclass(frozen=True)
class ToolHealthStatus:
    """健康检查的返回结果，默认视为健康。"""

    healthy: bool = True
    message: Optional[str] = None
    detail: Optional[str] = None


@dataclass(frozen=True)
class ToolMetadata:
    """工具描述信息，用于治理与调度。"""

    read_only: bool = True
    requires_confirmation: bool = False
    default_timeout: float = 30.0
    max_retries: int = 0
    retry_backoff: float = 0.5
    idempotent: bool = True
    labels: tuple[str, ...] = field(default_factory=tuple)


class AbstractTool(ABC):
    """
    Agentic 工具抽象基类。

    所有工具需实现异步 `execute` 方法，并可覆盖 `metadata` 以提供治理所需的信息。
    """

    # 需由子类定义
    name: str
    description: str
    args_schema: Type[BaseModel]
    metadata: ToolMetadata = ToolMetadata()

    def __init__(self, db: AsyncSession, user_id: UUID):
        """
        初始化工具实例。

        Args:
            db: 数据库会话
            user_id: 当前用户，用于权限隔离
        """
        if not hasattr(db, "run_sync"):
            raise ValueError("Tool 需要 AsyncSession 或兼容的适配器，请使用 get_async_db 依赖")
        self.db = db
        self.user_id = user_id

    @classmethod
    def get_metadata(cls) -> ToolMetadata:
        """返回工具的元数据信息。"""
        return cls.metadata

    @classmethod
    def get_definition(cls) -> Dict[str, Any]:
        """
        生成 OpenAI Function Calling 兼容的工具定义。
        """
        schema = cls.args_schema.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": cls.name,
                "description": cls.description,
                "parameters": {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                },
            },
        }

    async def initialise(self) -> None:
        """
        工具初始化钩子。

        子类可覆盖此方法以进行连接池预热等操作，默认无动作。
        """

    async def health_check(self) -> ToolHealthStatus:
        """
        工具健康检查钩子。

        默认返回健康状态；子类可覆盖，用于探测外部依赖状态。
        """
        return ToolHealthStatus()

    async def shutdown(self) -> None:
        """
        工具资源清理钩子。

        默认无动作，留给需要关闭连接或释放资源的子类使用。
        """

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """
        执行工具。

        Args:
            **kwargs: 通过 Pydantic 校验后的参数
        Returns:
            ToolResult: 结构化执行结果
        """

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"{self.__class__.__name__}(name='{self.name}')"

    def _ensure_db(self):
        """
        返回可 await 的数据库会话，若当前仍为同步 Session 则包一层适配器。

        注：适配器依旧执行同步 IO，应尽快切换到原生 AsyncSession。
        """

        return self.db
