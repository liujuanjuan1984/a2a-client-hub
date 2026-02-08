"""Tool registry for automatic discovery and execution of agent tools."""

from __future__ import annotations

import asyncio
import inspect
import pkgutil
import sys
import threading
import time
from typing import Any, Dict, Iterable, List, MutableMapping, Optional, Type
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import tools as tools_module
from app.agents.agent_registry import agent_registry
from app.agents.tools.base import AbstractTool, ToolMetadata
from app.agents.tools.lifecycle import ToolLifecycleManager, ToolUnavailableError
from app.agents.tools.responses import ToolResult, create_tool_error
from app.core.config import settings
from app.core.logging import get_logger, log_exception

logger = get_logger(__name__)

_TOOL_CLASS_CACHE: Dict[str, Type[AbstractTool]] = {}
_TOOL_CACHE_INITIALIZED = False
_TOOL_CACHE_LOCK = threading.Lock()


def _is_tool_class(candidate: Type[Any]) -> bool:
    """Return True when candidate is a concrete `AbstractTool` subclass."""

    return (
        inspect.isclass(candidate)
        and issubclass(candidate, AbstractTool)
        and candidate is not AbstractTool
        and not inspect.isabstract(candidate)
    )


def _iter_tool_modules() -> Iterable[str]:
    """Yield dotted module paths under the tools package."""

    yield tools_module.__name__
    for _, module_name, _ in pkgutil.walk_packages(
        tools_module.__path__, tools_module.__name__ + "."
    ):
        yield module_name


def _load_tool_classes() -> Dict[str, Type[AbstractTool]]:
    """Discover all tool classes once and cache them."""

    global _TOOL_CLASS_CACHE, _TOOL_CACHE_INITIALIZED
    if _TOOL_CACHE_INITIALIZED:
        return _TOOL_CLASS_CACHE

    with _TOOL_CACHE_LOCK:
        if _TOOL_CACHE_INITIALIZED:
            return _TOOL_CLASS_CACHE

        discovered: Dict[str, Type[AbstractTool]] = {}

        for module_path in _iter_tool_modules():
            try:
                module = __import__(module_path, fromlist=["*"])
            except Exception as exc:  # pragma: no cover - defensive logging
                log_exception(
                    logger,
                    f"Failed to import module {module_path}: {exc}",
                    sys.exc_info(),
                )
                continue

            for _, attr in inspect.getmembers(module, _is_tool_class):
                tool_name = getattr(attr, "name", None)
                if not tool_name:
                    logger.warning(
                        "Tool class %s missing required 'name' attribute; skipping",
                        attr.__name__,
                    )
                    continue

                existing = discovered.get(tool_name)
                if existing is not None:
                    raise ValueError(
                        f"Duplicate tool name detected: '{tool_name}' defined in "
                        f"{existing.__module__}.{existing.__name__} and {attr.__module__}.{attr.__name__}"
                    )

                discovered[tool_name] = attr
                logger.debug("Discovered tool class '%s'", tool_name)

        _TOOL_CLASS_CACHE = discovered
        _TOOL_CACHE_INITIALIZED = True
        logger.info("Tool class cache primed with %d tools", len(discovered))
        return _TOOL_CLASS_CACHE


class ToolAccessRegistry:
    """
    Tool registry for automatic discovery and management of all tools.

    This class automatically discovers all AbstractTool subclasses,
    instantiates them, and provides methods for tool execution and definition retrieval.
    """

    def __init__(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        agent_name: str = "root_agent",
        allowed_tools: Optional[Iterable[str]] = None,
    ):
        """
        Initialize the tool registry.

        Args:
            db: Database session for tool instantiation
            user_id: User ID for tool context
            agent_name: Name of the agent requesting access
            allowed_tools: Optional explicit whitelist; when omitted the registry will
                derive the allowed set using agent profiles and tool ownership config.
        """
        if not hasattr(db, "run_sync"):
            raise TypeError(
                "ToolAccessRegistry requires an AsyncSession (object with run_sync)"
            )
        self.db = db
        self.user_id = user_id
        self._tool_classes = _load_tool_classes()
        self._tool_instances: MutableMapping[str, AbstractTool] = {}
        self._lifecycle = ToolLifecycleManager()
        self._agent_name = agent_name

        available_tool_names = list(self._tool_classes.keys())
        if allowed_tools is None:
            self._allowed_tools = agent_registry.resolve_allowed_tools(
                agent_name, available_tool_names
            )
        else:
            self._allowed_tools = {
                name for name in allowed_tools if name in self._tool_classes
            }

        if not settings.a2a_enabled and "a2a_agent" in self._allowed_tools:
            self._allowed_tools.discard("a2a_agent")
            logger.info(
                "A2A tool removed from registry because integration disabled",
                extra={"agent_name": agent_name},
            )
        elif settings.a2a_enabled and "a2a_agent" in self._allowed_tools:
            logger.info(
                "A2A tool available for agent",
                extra={"agent_name": agent_name},
            )

        logger.info(
            "ToolAccessRegistry ready for user %s (agent=%s) with %d/%d tool classes",
            user_id,
            agent_name,
            len(self._allowed_tools),
            len(self._tool_classes),
            extra={"allowed_tools": sorted(self._allowed_tools)},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_tool_instance(self, tool_name: str) -> AbstractTool:
        """Instantiate and cache tool instances per registry."""

        if tool_name not in self._allowed_tools:
            raise ValueError(
                f"Tool '{tool_name}' is not available for agent '{self._agent_name}'"
            )

        if tool_name in self._tool_instances:
            return self._tool_instances[tool_name]

        tool_class = self._tool_classes.get(tool_name)
        if tool_class is None:
            available = list(self._tool_classes.keys())
            raise ValueError(
                f"Tool '{tool_name}' not found. Available tools: {available}"
            )

        try:
            instance = tool_class(db=self.db, user_id=self.user_id)
        except Exception as exc:  # pragma: no cover - 防御性分支
            log_exception(
                logger,
                f"Failed to instantiate tool '{tool_name}': {exc}",
                sys.exc_info(),
            )
            raise

        self._tool_instances[tool_name] = instance
        self._lifecycle.get_state(tool_name)
        return instance

    def get_all_tool_definitions(self) -> List[Dict[str, Any]]:
        """
        Get OpenAI-compatible definitions for all registered tools.

        Returns:
            List of tool definitions compatible with OpenAI function calling
        """
        definitions: List[Dict[str, Any]] = []
        for tool_name in sorted(self._allowed_tools):
            tool_class = self._tool_classes[tool_name]
            definitions.append(tool_class.get_definition())
        return definitions

    async def execute_tool(
        self,
        tool_name: str,
        *,
        timeout: Optional[float] = None,
        metadata_override: Optional[ToolMetadata] = None,
        **kwargs,
    ) -> ToolResult:
        """
        Execute a tool by name with the provided arguments.

        Args:
            tool_name: Name of the tool to execute
            timeout: Optional timeout in seconds overriding metadata default
            metadata_override: Optional metadata override (e.g. from policy)
            **kwargs: Arguments to pass to the tool

        Returns:
            ToolResult of the tool execution

        Raises:
            ValueError: If the tool is not found or arguments invalid
        """

        tool = self._get_tool_instance(tool_name)
        try:
            await self._lifecycle.ensure_ready(tool_name, tool)
        except ToolUnavailableError as exc:
            logger.warning("Tool '%s' unavailable: %s", tool_name, exc)
            return create_tool_error(
                message=f"Tool '{tool_name}' temporarily unavailable",
                kind="unavailable",
                detail=str(exc),
                metrics={"attempt": 0},
            )

        try:
            validated_args = tool.args_schema(**kwargs)
        except ValidationError as exc:
            logger.warning(
                "Invalid arguments for tool '%s': %s",
                tool_name,
                str(exc),
                exc_info=False,
            )
            raise ValueError(
                f"Invalid arguments for tool '{tool_name}': {exc}"
            ) from exc

        payload = validated_args.model_dump()
        metadata = metadata_override or tool.get_metadata()
        effective_timeout = timeout if timeout is not None else metadata.default_timeout
        attempts = max(1, metadata.max_retries + 1)
        backoff = max(0.0, metadata.retry_backoff)

        last_exception: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            start_time = time.perf_counter()
            try:
                logger.info(
                    "Executing tool '%s' attempt %s/%s with args: %s",
                    tool_name,
                    attempt,
                    attempts,
                    payload,
                )
                coro = tool.execute(**payload)
                if effective_timeout and effective_timeout > 0:
                    result = await asyncio.wait_for(coro, timeout=effective_timeout)
                else:
                    result = await coro
                duration = time.perf_counter() - start_time

                if not isinstance(result, ToolResult):
                    logger.error(
                        "Tool '%s' returned non ToolResult payload: %s",
                        tool_name,
                        type(result),
                    )
                    await self._lifecycle.record_failure(
                        tool_name,
                        TypeError(
                            f"Invalid result type from tool '{tool_name}': "
                            f"{type(result)}"
                        ),
                    )
                    return create_tool_error(
                        message=f"Tool '{tool_name}' produced invalid result",
                        kind="invalid_result",
                        detail=str(type(result)),
                        metrics={
                            "duration_seconds": duration,
                            "attempt": attempt,
                        },
                    )

                logger.info(
                    "Tool '%s' executed successfully in %.3fs (status=%s)",
                    tool_name,
                    duration,
                    result.status,
                )
                await self._lifecycle.record_success(tool_name)
                metrics = result.metrics or {}
                result.metrics = {
                    **metrics,
                    "duration_seconds": duration,
                    "attempt": attempt,
                }
                return result

            except asyncio.TimeoutError:
                duration = time.perf_counter() - start_time
                timeout_error = asyncio.TimeoutError(
                    f"Tool '{tool_name}' timed out after {effective_timeout}s"
                )
                await self._lifecycle.record_failure(tool_name, timeout_error)
                logger.warning(
                    "Tool '%s' timed out after %.3fs (attempt %s/%s)",
                    tool_name,
                    duration,
                    attempt,
                    attempts,
                )
                last_exception = timeout_error
                if attempt >= attempts:
                    return create_tool_error(
                        message=f"Tool '{tool_name}' timed out",
                        kind="timeout",
                        detail=f"Exceeded timeout of {effective_timeout}s",
                        metrics={
                            "duration_seconds": duration,
                            "attempt": attempt,
                        },
                    )
                await asyncio.sleep(backoff * attempt)
            except Exception as exc:  # pragma: no cover - 防御性分支
                duration = time.perf_counter() - start_time
                last_exception = exc
                await self._lifecycle.record_failure(tool_name, exc)
                log_exception(
                    logger,
                    f"Tool '{tool_name}' execution failed: {exc}",
                    sys.exc_info(),
                )
                if attempt >= attempts:
                    return create_tool_error(
                        message=f"Tool '{tool_name}' execution failed",
                        kind="exception",
                        detail=str(exc),
                        metrics={
                            "duration_seconds": duration,
                            "attempt": attempt,
                        },
                    )
                await asyncio.sleep(backoff * attempt)

        # 应该不会到达此处，兜底返回错误。
        await self._lifecycle.record_failure(
            tool_name,
            last_exception or RuntimeError("Unknown tool failure"),
        )
        return create_tool_error(
            message=f"Tool '{tool_name}' execution failed",
            kind="unknown",
            detail=str(last_exception) if last_exception else None,
        )

    def get_tool_metadata(self, tool_name: str) -> ToolMetadata:
        tool = self._get_tool_instance(tool_name)
        return tool.get_metadata()

    def __len__(self) -> int:
        """Return the number of registered tools."""
        return len(self._tool_classes)

    def __contains__(self, tool_name: str) -> bool:
        """Check if a tool is registered."""
        return tool_name in self._tool_classes

    def __repr__(self) -> str:
        """String representation of the registry."""
        return f"ToolAccessRegistry(tools={list(self._tool_classes.keys())})"
