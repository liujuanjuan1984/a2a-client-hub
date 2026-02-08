"""Runtime builders for Compass strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger
from app.review.strategies.llm import DailyReviewLLMClient

logger = get_logger(__name__)


@dataclass
class DailySummaryParams:
    tone: str = "professional"
    language: str = "zh"
    include_metrics: bool = True

    def to_string(self) -> str:
        """Convert params to string representation for logging."""
        return f"DailySummaryParams(tone={self.tone}, language={self.language}, include_metrics={self.include_metrics})"


@dataclass
class DailyPlanParams:
    max_actions: int = 5
    language: str = "zh"
    tone: str = "proactive"

    def to_string(self) -> str:
        """Convert params to string representation for logging."""
        return f"DailyPlanParams(max_actions={self.max_actions}, language={self.language}, tone={self.tone})"


def build_daily_review_summary_strategy(
    params: Dict[str, Any],
    client: DailyReviewLLMClient,
) -> Tuple[Any, DailySummaryParams]:
    """Return runtime strategy instance and input for daily summary."""

    summary_params = DailySummaryParams(**params)
    (
        StrategyBase,
        CardBoxClass,
        CardClass,
        TextContentClass,
        TransformationResult,
    ) = _require_core()

    class DailyReviewSummaryStrategy(StrategyBase):
        def __init__(
            self, llm_client: DailyReviewLLMClient, config: DailySummaryParams
        ) -> None:
            self.llm_client = llm_client
            self.config = config

        async def apply(
            self,
            card_box: Any,
            card_store: Any,
            _input: Optional[Any] = None,
            _fs: Optional[Any] = None,
        ) -> Any:
            source_cards = _resolve_cards(card_box, card_store)
            if not source_cards:
                logger.info("DailyReviewSummaryStrategy: no source cards found")
                return TransformationResult(card_box, {})

            aggregated_text = (
                "\n\n".join(card["content"] for card in source_cards if card["content"])
                or ""
            )
            metadata = source_cards[0]["metadata"]
            target_date = (
                metadata.get("target_date") if isinstance(metadata, dict) else None
            )

            prompt = _build_summary_prompt(aggregated_text, self.config)
            result = await self.llm_client.complete(
                messages=[
                    {
                        "role": "system",
                        "content": _summary_system_prompt(self.config),
                    },
                    {"role": "user", "content": prompt},
                ],
                metadata={
                    "workflow": "daily_review",
                    "stage": "summary",
                    "target_date": target_date,
                },
            )

            summary_text = result.content.strip() or "(未能生成总结)"
            new_card = CardClass(
                content=TextContentClass(text=summary_text),
                metadata=_summary_metadata(metadata, self.config, result.raw_response),
            )
            card_store.add(new_card)

            new_box = CardBoxClass()
            for card_id in getattr(card_box, "card_ids", []):
                new_box.add(card_id)
            new_box.add(new_card.card_id)

            relationship = {}
            if source_cards:
                source_id = source_cards[-1]["card_id"]
                if source_id:
                    relationship[str(source_id)] = [str(new_card.card_id)]

            return TransformationResult(new_box, relationship)

    return DailyReviewSummaryStrategy(client, summary_params), summary_params


def build_daily_review_plan_strategy(
    params: Dict[str, Any],
    client: DailyReviewLLMClient,
) -> Tuple[Any, DailyPlanParams]:
    plan_params = DailyPlanParams(**params)
    (
        StrategyBase,
        CardBoxClass,
        CardClass,
        TextContentClass,
        TransformationResult,
    ) = _require_core()

    class DailyReviewPlanStrategy(StrategyBase):
        def __init__(
            self, llm_client: DailyReviewLLMClient, config: DailyPlanParams
        ) -> None:
            self.llm_client = llm_client
            self.config = config

        async def apply(
            self,
            card_box: Any,
            card_store: Any,
            _input: Optional[Any] = None,
            _fs: Optional[Any] = None,
        ) -> Any:
            cards = _resolve_cards(card_box, card_store)
            summary_card = _find_card_by_stage(cards, "summary")
            if summary_card is None:
                logger.info("DailyReviewPlanStrategy: summary card missing, skip")
                return TransformationResult(card_box, {})

            aggregated_card = _find_card_by_module(cards, "daily_review_input")
            aggregated_text = aggregated_card["content"] if aggregated_card else ""
            plan_prompt = _build_plan_prompt(
                summary_text=summary_card["content"],
                aggregated_text=aggregated_text,
                config=self.config,
            )

            metadata = (
                summary_card["metadata"] if isinstance(summary_card, dict) else {}
            )
            target_date = (
                metadata.get("target_date") if isinstance(metadata, dict) else None
            )

            result = await self.llm_client.complete(
                messages=[
                    {
                        "role": "system",
                        "content": _plan_system_prompt(self.config),
                    },
                    {"role": "user", "content": plan_prompt},
                ],
                metadata={
                    "workflow": "daily_review",
                    "stage": "plan",
                    "target_date": target_date,
                },
            )

            plan_text = result.content.strip() or "(未能生成行动建议)"
            new_card = CardClass(
                content=TextContentClass(text=plan_text),
                metadata=_plan_metadata(metadata, self.config, result.raw_response),
            )
            card_store.add(new_card)

            new_box = CardBoxClass()
            for card_id in getattr(card_box, "card_ids", []):
                new_box.add(card_id)
            new_box.add(new_card.card_id)

            relationship = {}
            source_id = (
                summary_card.get("card_id") if isinstance(summary_card, dict) else None
            )
            if source_id:
                relationship[str(source_id)] = [str(new_card.card_id)]

            return TransformationResult(new_box, relationship)

    return DailyReviewPlanStrategy(client, plan_params), plan_params


def _require_core() -> Any:
    try:
        from card_box_core.strategies import Strategy, TransformationResult
        from card_box_core.structures import Card, CardBox, TextContent
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("未安装 card_box_core，无法构建策略。") from exc
    return Strategy, CardBox, Card, TextContent, TransformationResult


def _resolve_cards(card_box: Any, card_store: Any) -> List[Dict[str, Any]]:
    resolved: List[Dict[str, Any]] = []
    card_ids = getattr(card_box, "card_ids", []) or []
    for cid in card_ids:
        card = card_store.get(cid)
        if not card:
            continue
        content = getattr(getattr(card, "content", None), "text", "") or ""
        metadata = getattr(card, "metadata", {}) or {}
        resolved.append(
            {
                "card_id": getattr(card, "card_id", None),
                "content": content,
                "metadata": metadata,
            }
        )
    return resolved


def _find_card_by_stage(
    cards: List[Dict[str, Any]], stage: str
) -> Optional[Dict[str, Any]]:
    for card in reversed(cards):
        metadata = card.get("metadata") or {}
        if metadata.get("daily_review_stage") == stage:
            return card
    return None


def _find_card_by_module(
    cards: List[Dict[str, Any]], module: str
) -> Optional[Dict[str, Any]]:
    for card in cards:
        metadata = card.get("metadata") or {}
        if metadata.get("module") == module:
            return card
    return None


def _build_summary_prompt(aggregated_text: str, config: DailySummaryParams) -> str:
    return (
        "Review the following daily inputs and craft a concise Markdown summary that covers:\n"
        "1. Key highlights from yesterday (max 3 bullets)\n"
        "2. Challenges or risks that require attention (max 3 bullets)\n"
        "3. Quantitative metrics, if available\n\n"
        f"Write the summary in {config.language}.\n"
        "Raw data:\n\n"
        f"{aggregated_text}"
    )


def _summary_system_prompt(config: DailySummaryParams) -> str:
    return (
        "You are the Compass personal assistant, skilled at extracting insights from structured and semi-structured data. "
        f"Maintain a {config.tone} tone, respond in {config.language}, and format the output as clean Markdown with headings and lists."
    )


def _summary_metadata(
    base_metadata: Dict[str, Any], config: DailySummaryParams, raw_response: Any
) -> Dict[str, Any]:
    metadata = dict(base_metadata or {})
    metadata.update(
        {
            "module": "daily_review_output",
            "daily_review_stage": "summary",
            "category": "daily_summary",
            "language": config.language,
            "tone": config.tone,
            "llm_model": getattr(raw_response, "model", None),
        }
    )
    return metadata


def _build_plan_prompt(
    summary_text: str, aggregated_text: str, config: DailyPlanParams
) -> str:
    return (
        "Using the context below, propose today's top action items with the following constraints:\n"
        f"- Provide no more than {config.max_actions} recommendations\n"
        "- Each action must include a clear objective or expected outcome\n"
        "- Flag any blockers and suggest ways to resolve them\n"
        "- Keep the tone positive and execution-focused\n\n"
        "Yesterday's summary:\n"
        f"{summary_text}\n\n"
        "Additional data:\n"
        f"{aggregated_text}"
    )


def _plan_system_prompt(config: DailyPlanParams) -> str:
    return (
        "You are a task planning assistant. Produce an actionable list for the day, written in Markdown, "
        f"using {config.language} and maintaining a {config.tone} tone."
    )


def _plan_metadata(
    base_metadata: Dict[str, Any], config: DailyPlanParams, raw_response: Any
) -> Dict[str, Any]:
    metadata = dict(base_metadata or {})
    metadata.update(
        {
            "module": "daily_review_output",
            "daily_review_stage": "plan",
            "category": "daily_summary",
            "language": config.language,
            "tone": config.tone,
            "llm_model": getattr(raw_response, "model", None),
        }
    )
    return metadata
