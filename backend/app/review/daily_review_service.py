"""Daily review orchestration service."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.cardbox.engine_factory import create_engine
from app.cardbox.service import cardbox_service
from app.cardbox.utils import daily_review_output_box, tenant_for_user
from app.core.logging import get_logger
from app.db.models.daily_review_run import DailyReviewRun
from app.review.config import (
    DailyReviewWorkflowConfig,
    StrategySpec,
    get_daily_review_config,
)
from app.review.daily_review_builder import build_daily_review_input
from app.review.strategies import build_strategy

logger = get_logger(__name__)


@dataclass
class StrategyExecutionSummary:
    """Metadata about the generated cards."""

    stage: str
    card_id: Optional[str]
    content: Optional[str]
    metadata: Dict[str, Any]


@dataclass
class DailyReviewResult:
    status: str
    output_box: Optional[str]
    summaries: List[StrategyExecutionSummary]
    error: Optional[str] = None
    chat_markdown: Optional[str] = None
    input_box: Optional[str] = None


class DailyReviewError(Exception):
    """Raised when the daily review workflow fails irrecoverably."""


async def run_daily_review(
    db: AsyncSession,
    *,
    user_id: UUID,
    target_date: date,
    force: bool = False,
    trigger_source: str = "manual",
    config: Optional[DailyReviewWorkflowConfig] = None,
) -> DailyReviewResult:
    """Execute the daily review workflow for a user/date pair."""

    config = config or get_daily_review_config()

    async def _call_with_session(func, *args, **kwargs):
        def runner(sync_session: Session):
            return func(sync_session, *args, **kwargs)

        return await db.run_sync(runner)

    tenant_id = tenant_for_user(user_id)
    engine = create_engine(tenant_id)

    output_box_name = daily_review_output_box(user_id, target_date)
    if not force and _output_exists(engine, tenant_id, output_box_name):
        logger.info(
            "Daily review skipped: output already exists",
            extra={"user_id": str(user_id), "target_date": target_date.isoformat()},
        )
        result = DailyReviewResult(
            status="skipped",
            output_box=output_box_name,
            summaries=[],
            input_box=None,
        )
        await _record_run(
            db,
            user_id=user_id,
            target_date=target_date,
            trigger_source=trigger_source,
            input_box_name=None,
            result=result,
        )
        return result

    input_box_name = await _call_with_session(
        build_daily_review_input,
        user_id=user_id,
        target_date=target_date,
    )

    if input_box_name is None:
        logger.info(
            "Daily review skipped: builder produced no input",
            extra={"user_id": str(user_id), "target_date": target_date.isoformat()},
        )
        result = DailyReviewResult(
            status="no_data",
            output_box=None,
            summaries=[],
            chat_markdown=_compose_no_data_markdown(target_date),
            input_box=None,
        )
        await _record_run(
            db,
            user_id=user_id,
            target_date=target_date,
            trigger_source=trigger_source,
            input_box_name=None,
            result=result,
        )
        return result

    input_box = engine.storage_adapter.load_card_box(input_box_name, tenant_id)
    if input_box is None:
        raise DailyReviewError(
            f"Input CardBox '{input_box_name}' not found for tenant {tenant_id}"
        )

    strategy_pairs = _build_strategy_pairs(config.strategy_chain)

    try:
        result_box = await engine.transform(input_box, strategy_pairs)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception(
            "Daily review transform failed",
            extra={"user_id": str(user_id), "target_date": target_date.isoformat()},
        )
        fallback_summary = _create_failure_output(
            engine=engine,
            tenant_id=tenant_id,
            input_box=input_box,
            output_box_name=output_box_name,
            error=str(exc),
            target_date=target_date,
        )
        chat_markdown = _compose_chat_markdown(target_date, [fallback_summary])
        failure_result = DailyReviewResult(
            status="failed",
            output_box=output_box_name,
            summaries=[fallback_summary],
            error=str(exc),
            chat_markdown=chat_markdown,
            input_box=input_box_name,
        )
        await _record_run(
            db,
            user_id=user_id,
            target_date=target_date,
            trigger_source=trigger_source,
            input_box_name=input_box_name,
            result=failure_result,
        )
        return failure_result

    engine.storage_adapter.save_card_box(
        result_box, name=output_box_name, tenant_id=tenant_id
    )
    extracted = _extract_stage_cards(engine, result_box, stages=["summary", "plan"])
    chat_markdown = _compose_chat_markdown(target_date, extracted)

    logger.info(
        "Daily review completed",
        extra={
            "user_id": str(user_id),
            "target_date": target_date.isoformat(),
            "card_count": len(getattr(result_box, "card_ids", [])),
            "trigger": trigger_source,
        },
    )

    success_result = DailyReviewResult(
        status="completed",
        output_box=output_box_name,
        summaries=extracted,
        chat_markdown=chat_markdown,
        input_box=input_box_name,
    )
    await _record_run(
        db,
        user_id=user_id,
        target_date=target_date,
        trigger_source=trigger_source,
        input_box_name=input_box_name,
        result=success_result,
    )
    return success_result


def _output_exists(engine: Any, tenant_id: str, box_name: str) -> bool:
    card_box = engine.storage_adapter.load_card_box(box_name, tenant_id)
    return bool(card_box and getattr(card_box, "card_ids", []))


def _build_strategy_pairs(strategy_chain: List[StrategySpec]) -> List[Any]:
    pairs: List[Any] = []
    for spec in strategy_chain:
        strategy, strategy_input = build_strategy(spec.name, spec.params)
        pairs.append((strategy, strategy_input))
    return pairs


def _extract_stage_cards(
    engine: Any, card_box: Any, stages: List[str]
) -> List[StrategyExecutionSummary]:
    card_store = engine.card_store
    stage_set = set(stages)
    summaries: List[StrategyExecutionSummary] = []

    for card_id in getattr(card_box, "card_ids", []):
        card = card_store.get(card_id)
        if not card:
            continue
        metadata = getattr(card, "metadata", {}) or {}
        stage = metadata.get("daily_review_stage")
        if stage not in stage_set:
            continue
        content = getattr(getattr(card, "content", None), "text", "") or ""
        summaries.append(
            StrategyExecutionSummary(
                stage=stage,
                card_id=str(getattr(card, "card_id", card_id)),
                content=content,
                metadata=metadata,
            )
        )
    return summaries


def _create_failure_output(
    *,
    engine: Any,
    tenant_id: str,
    input_box: Any,
    output_box_name: str,
    error: str,
    target_date: date,
) -> StrategyExecutionSummary:
    try:
        from card_box_core.structures import Card, CardBox, TextContent
    except ImportError as exc:  # pragma: no cover
        raise DailyReviewError("card_box_core 未安装，无法创建失败兜底卡") from exc

    fallback_box = CardBox()
    for card_id in getattr(input_box, "card_ids", []):
        fallback_box.add(card_id)
    engine.storage_adapter.save_card_box(
        fallback_box, name=output_box_name, tenant_id=tenant_id
    )

    message = "自动生成每日复盘失败，请稍后重试。\n\n" "错误信息：" f"{error}"
    metadata = {
        "module": "daily_review_output",
        "daily_review_stage": "error",
        "category": "daily_summary",
        "target_date": target_date.isoformat(),
        "status": "failed",
    }

    failure_card = Card(content=TextContent(text=message), metadata=metadata)
    cardbox_service.add_cards(tenant_id, output_box_name, [failure_card])

    return StrategyExecutionSummary(
        stage="error",
        card_id=str(failure_card.card_id),
        content=message,
        metadata=metadata,
    )


def _compose_chat_markdown(
    target_date: date, summaries: List[StrategyExecutionSummary]
) -> str:
    lines = [f"# 每日复盘 ({target_date.isoformat()})"]
    stage_map = {summary.stage: summary for summary in summaries}

    summary_section = stage_map.get("summary")
    plan_section = stage_map.get("plan")
    error_section = stage_map.get("error")

    if summary_section:
        lines.append("\n## 昨日总结")
        lines.append(summary_section.content or "(暂无总结)")

    if plan_section:
        lines.append("\n## 今日行动建议")
        lines.append(plan_section.content or "(暂无建议)")

    if not summary_section and not plan_section and error_section:
        lines.append("\n## 提示")
        lines.append(error_section.content or "(生成失败)\n")

    if not summary_section and not plan_section and not error_section:
        lines.append("\n> 尚未生成新的复盘内容。")

    return "\n\n".join(lines)


def _compose_no_data_markdown(target_date: date) -> str:
    return (
        f"# 每日复盘 ({target_date.isoformat()})\n\n" "## 提示\n\n" "> 昨日没有可用的数据，请补充记录或稍后再试。"
    )


async def _record_run(
    db: AsyncSession,
    *,
    user_id: UUID,
    target_date: date,
    trigger_source: str,
    input_box_name: Optional[str],
    result: DailyReviewResult,
) -> None:
    try:
        record = DailyReviewRun(
            user_id=user_id,
            target_date=target_date,
            status=result.status,
            trigger_source=trigger_source,
            input_box_name=input_box_name,
            output_box_name=result.output_box,
            error_message=result.error,
            extra={
                "summaries": [asdict(summary) for summary in result.summaries],
                "chat_markdown": result.chat_markdown,
            },
        )
        db.add(record)
        await db.commit()
    except Exception:  # pragma: no cover - best effort persistence
        logger.warning(
            "Failed to persist daily review run record",
            exc_info=True,
            extra={
                "user_id": str(user_id),
                "target_date": target_date.isoformat(),
                "status": result.status,
            },
        )
        await db.rollback()
