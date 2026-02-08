"""Configuration helpers for daily review workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class StrategySpec:
    """Describe a strategy invocation."""

    name: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DailyReviewWorkflowConfig:
    """Config values for the daily review orchestrator."""

    strategy_chain: List[StrategySpec] = field(
        default_factory=lambda: [
            StrategySpec(
                name="compass_daily_summary",
                params={"tone": "professional", "language": "zh"},
            ),
            StrategySpec(
                name="compass_daily_plan",
                params={"max_actions": 5, "language": "zh", "tone": "proactive"},
            ),
        ]
    )
    push_to_chat: bool = True


DEFAULT_WORKFLOW_CONFIG = DailyReviewWorkflowConfig()


def get_daily_review_config() -> DailyReviewWorkflowConfig:
    """Return default workflow configuration (placeholder for future overrides)."""

    return DEFAULT_WORKFLOW_CONFIG
