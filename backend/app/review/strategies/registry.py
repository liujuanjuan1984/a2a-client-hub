"""Registry for Compass-specific Cardbox strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from app.review.strategies.llm import DailyReviewLLMClient
from app.review.strategies.runtime import (
    build_daily_review_plan_strategy,
    build_daily_review_summary_strategy,
)

StrategyInstance = Any
StrategyInput = Any


@dataclass
class StrategyEntry:
    """Metadata for registered strategies."""

    name: str
    builder: Callable[
        [Optional[Dict[str, Any]], DailyReviewLLMClient],
        Tuple[StrategyInstance, StrategyInput],
    ]
    description: str


def _default_client() -> DailyReviewLLMClient:
    return DailyReviewLLMClient()


STRATEGY_BUILDERS: Dict[str, StrategyEntry] = {
    "compass_daily_summary": StrategyEntry(
        name="compass_daily_summary",
        builder=lambda params, client=_default_client(): build_daily_review_summary_strategy(
            params or {}, client
        ),
        description="将每日复盘输入卡汇总为亮点/问题/统计的 Markdown 总结",
    ),
    "compass_daily_plan": StrategyEntry(
        name="compass_daily_plan",
        builder=lambda params, client=_default_client(): build_daily_review_plan_strategy(
            params or {}, client
        ),
        description="基于总结与任务背景生成今日行动建议",
    ),
}


def list_strategies() -> Dict[str, StrategyEntry]:
    """Return registered strategy entries."""

    return STRATEGY_BUILDERS.copy()


def build_strategy(
    name: str, params: Optional[Dict[str, Any]] = None
) -> Tuple[StrategyInstance, StrategyInput]:
    """Instantiate strategy and its input from registry."""

    entry = STRATEGY_BUILDERS.get(name)
    if entry is None:
        raise KeyError(f"Strategy '{name}' not registered")
    return entry.builder(params, _default_client())
