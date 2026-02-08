"""Helpers for building daily review input Cardboxes."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple, Type
from uuid import UUID

from sqlalchemy.orm import Session

from app.cardbox.engine_factory import create_engine
from app.cardbox.service import cardbox_service
from app.cardbox.utils import daily_review_input_box, data_cardbox_name, tenant_for_user

_CARD_CLASS: Optional[Type[Any]] = None
_TEXT_CONTENT_CLASS: Optional[Type[Any]] = None

if TYPE_CHECKING:
    from app.cardbox.data_sync import CardBoxDataSyncService


@dataclass(frozen=True)
class SectionConfig:
    """Render configuration for a snapshot module."""

    title: str
    max_primary_items: int = 3
    max_secondary_items: int = 2


SECTION_CONFIG: Dict[str, SectionConfig] = {
    "actual_event": SectionConfig(title="## Timelog 概览"),
    "vision_tasks": SectionConfig(
        title="## 愿景与任务进展", max_primary_items=3, max_secondary_items=2
    ),
    "notes": SectionConfig(title="## 笔记摘要", max_primary_items=5, max_secondary_items=0),
}

SECTION_LEGACY_ALIASES: Dict[str, str] = {
    "timelog": "actual_event",
}


def _get_cardbox_sync_service() -> "CardBoxDataSyncService":
    from app.cardbox.data_sync import cardbox_data_sync_service

    return cardbox_data_sync_service


def build_daily_review_input(
    db: Session,
    *,
    user_id: UUID,
    target_date: date,
) -> Optional[str]:
    """Aggregate snapshot CardBoxes into a single daily review input card.

    Parameters
    ----------
    db:
        SQLAlchemy 会话，用于触发最新的数据同步。
    user_id:
        当前用户标识。
    target_date:
        需要复盘的自然日（按照用户本地日历）。

    Returns
    -------
    Optional[str]
        成功写入卡之后返回输入 CardBox 名称；若所有模块均无内容且无需写入则返回 ``None``。
    """

    card_cls, text_cls = _require_cardbox_structures()

    tenant_id = tenant_for_user(user_id)
    cardbox_name = daily_review_input_box(user_id, target_date)

    summaries = _get_cardbox_sync_service().sync_all(
        db,
        user_id=user_id,
        target_date=target_date,
    )

    engine = create_engine(tenant_id)

    sections: List[str] = []
    empty_modules: List[str] = []
    source_cards: Dict[str, Optional[str]] = {}

    for module_key, config in SECTION_CONFIG.items():
        snapshot_card = _load_latest_snapshot(
            engine, tenant_id, user_id, target_date, module_key
        )
        if snapshot_card is None:
            empty_modules.append(module_key)
            source_cards[module_key] = None
            sections.append(_format_section(config.title, ["- 暂无可用数据。"]))
            continue

        card_identifier = getattr(snapshot_card, "card_id", None)
        source_cards[module_key] = str(card_identifier) if card_identifier else None
        lines = _render_section(module_key, snapshot_card, config)
        if not lines:
            empty_modules.append(module_key)
            lines = ["- 暂无可用数据。"]
        sections.append(_format_section(config.title, lines))

    if not sections:
        return None

    document = _compose_document(target_date, sections)

    period_start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
    period_end = datetime.combine(target_date, time.max, tzinfo=timezone.utc)

    metadata = {
        "module": "daily_review_input",
        "category": "daily_summary",
        "target_date": target_date.isoformat(),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "status": "empty" if len(empty_modules) == len(SECTION_CONFIG) else "complete",
        "empty_modules": empty_modules,
        "source_cards": source_cards,
        "sync_summaries": [asdict(summary) for summary in summaries],
    }

    new_card = card_cls(content=text_cls(text=document), metadata=metadata)
    cardbox_service.add_cards(tenant_id, cardbox_name, [new_card])
    return cardbox_name


def _require_cardbox_structures() -> Tuple[Type[Any], Type[Any]]:
    global _CARD_CLASS, _TEXT_CONTENT_CLASS
    if _CARD_CLASS is None or _TEXT_CONTENT_CLASS is None:
        try:
            from card_box_core.structures import Card as CardClass
            from card_box_core.structures import TextContent as TextContentClass
        except ImportError as exc:  # pragma: no cover - 环境未安装 card_box_core
            raise RuntimeError("card_box_core 未安装，无法构建每日复盘输入卡。请确认依赖已安装。") from exc
        _CARD_CLASS = CardClass
        _TEXT_CONTENT_CLASS = TextContentClass
    return _CARD_CLASS, _TEXT_CONTENT_CLASS


def _load_latest_snapshot(
    engine: Any, tenant_id: str, user_id: UUID, target_date: date, module_key: str
) -> Optional[Any]:
    canonical_key = SECTION_LEGACY_ALIASES.get(module_key, module_key)
    box_name = data_cardbox_name(user_id, canonical_key, target_date)
    card_box = engine.storage_adapter.load_card_box(box_name, tenant_id)
    if card_box is None and module_key != canonical_key:
        legacy_box = data_cardbox_name(user_id, module_key, target_date)
        card_box = engine.storage_adapter.load_card_box(legacy_box, tenant_id)
    if card_box is None or not getattr(card_box, "card_ids", []):
        return None

    for card_id in reversed(card_box.card_ids):
        card = engine.card_store.get(card_id)
        if card is not None:
            return card
    return None


def _render_section(module_key: str, card: Any, config: SectionConfig) -> List[str]:
    text = getattr(getattr(card, "content", None), "text", "") or ""
    metadata = getattr(card, "metadata", {}) or {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None

    canonical_key = SECTION_LEGACY_ALIASES.get(module_key, module_key)

    if canonical_key == "actual_event":
        return _render_timelog_section(metadata.get("summary"), payload, text, config)
    if canonical_key == "vision_tasks":
        return _render_vision_section(payload, config)
    if canonical_key == "notes":
        return _render_notes_section(payload, config)

    snippet = text.strip()
    if not snippet:
        return []
    return [f"- {snippet[:200]}"]


def _render_timelog_section(
    summary_or_legacy: Optional[Dict[str, Any]],
    payload_or_config: Optional[Dict[str, Any] | SectionConfig],
    raw_text: str = "",
    config: Optional[SectionConfig] = None,
) -> List[str]:
    """Render timelog section supporting both legacy and summary-aware payloads."""

    summary: Optional[Dict[str, Any]]
    legacy_payload: Optional[Dict[str, Any]]
    section_config: Optional[SectionConfig] = config

    if section_config is None and isinstance(payload_or_config, SectionConfig):
        # Legacy signature: (_legacy_payload, config)
        section_config = payload_or_config
        legacy_payload = (
            summary_or_legacy if isinstance(summary_or_legacy, dict) else None
        )
        summary = None
        text_payload = ""
    else:
        legacy_payload = (
            payload_or_config if isinstance(payload_or_config, dict) else None
        )
        summary = summary_or_legacy if isinstance(summary_or_legacy, dict) else None
        if section_config is None and isinstance(payload_or_config, SectionConfig):
            section_config = payload_or_config
        text_payload = raw_text or ""

    if section_config is None:
        raise ValueError("SectionConfig is required to render timelog section")

    lines: List[str] = []

    summary_lines = _render_timelog_summary_lines(summary)
    lines.extend(summary_lines)

    snippet_lines = _render_timelog_text_snippet(
        text_payload, section_config.max_primary_items
    )
    lines.extend(snippet_lines)

    if lines:
        return lines

    return _render_timelog_section_legacy(legacy_payload, section_config)


def _render_timelog_summary_lines(summary: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(summary, dict):
        return []

    lines: List[str] = []
    range_info = summary.get("date_range") or {}
    start_label = _format_iso_label(range_info.get("start"))
    end_label = _format_iso_label(range_info.get("end"))
    if start_label and end_label:
        lines.append(f"- 时间范围：{start_label} ~ {end_label}")

    total_records = summary.get("total_records")
    if isinstance(total_records, int):
        lines.append(f"- 记录数：{total_records} 条")

    total_duration = summary.get("total_duration_minutes")
    if isinstance(total_duration, int) and total_duration > 0:
        lines.append(f"- 总时长：{_format_duration_label(total_duration)}")

    dimension_stats = summary.get("dimension_stats")
    if isinstance(dimension_stats, list) and dimension_stats:
        dim_lines: List[str] = []
        for stat in dimension_stats[:3]:
            if not isinstance(stat, dict):
                continue
            dimension_id = stat.get("dimension_id") or "未分配维度"
            dim_count = stat.get("count") or 0
            duration_value = stat.get("duration_minutes")
            duration_label = (
                _format_duration_label(int(duration_value))
                if isinstance(duration_value, int) and duration_value > 0
                else "--"
            )
            dim_lines.append(f"{dimension_id}：{dim_count} 条（{duration_label}）")
        if dim_lines:
            lines.append("- 主要维度：" + "；".join(dim_lines))

    return lines


def _render_timelog_text_snippet(raw_text: str, limit: int) -> List[str]:
    if not raw_text.strip() or limit <= 0:
        return []

    snippets: List[str] = []
    for line in raw_text.splitlines():
        text = line.strip()
        if not text:
            continue
        snippets.append(text[:160])
        if len(snippets) >= limit:
            break

    if not snippets:
        return []

    lines = ["- 文本摘录："]
    lines.extend(f"  · {snippet}" for snippet in snippets)
    return lines


def _render_timelog_section_legacy(
    payload: Optional[Dict[str, Any]], config: SectionConfig
) -> List[str]:
    if not isinstance(payload, dict):
        return []

    lines: List[str] = []
    range_info = payload.get("range") or {}
    start = range_info.get("start")
    end = range_info.get("end")
    if start and end:
        lines.append(f"- 时间范围：{start} ~ {end}")

    entries = payload.get("entries") or []
    lines.append(f"- 记录数：{len(entries)}")

    for entry in entries[: config.max_primary_items]:
        title = entry.get("title") or "未命名事件"
        start_time_str = entry.get("start_time")
        duration = entry.get("duration_minutes")
        details: List[str] = []
        if start_time_str:
            details.append(str(start_time_str))
        if duration:
            details.append(f"{duration} 分钟")
        detail_text = f" ({'; '.join(details)})" if details else ""
        lines.append(f"  - {title}{detail_text}")

    if len(entries) > config.max_primary_items:
        lines.append(f"  - … 其余 {len(entries) - config.max_primary_items} 条记录")
    return lines


def _format_iso_label(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M")


def _format_duration_label(total_minutes: int) -> str:
    hours, minutes = divmod(max(total_minutes, 0), 60)
    parts: List[str] = []
    if hours:
        parts.append(f"{hours} 小时")
    if minutes or not parts:
        parts.append(f"{minutes} 分钟")
    return "".join(parts)


def _render_vision_section(
    payload: Optional[Dict[str, Any]], config: SectionConfig
) -> List[str]:
    if not isinstance(payload, dict):
        return []

    counts = payload.get("count") or {}
    lines = [
        f"- 愿景数量：{counts.get('visions', 0)}",
        f"- 任务数量：{counts.get('tasks', 0)}",
    ]

    items = payload.get("items") or []
    for item in items[: config.max_primary_items]:
        vision = item.get("vision") or {}
        tasks = item.get("tasks") or []
        vision_name = vision.get("name") or "未命名愿景"
        lines.append(f"  - {vision_name}（任务 {len(tasks)} 项）")
        for task in tasks[: config.max_secondary_items]:
            content = task.get("content") or "未填写任务"
            status = task.get("status") or "unknown"
            lines.append(f"    • {content} [{status}]")
        if len(tasks) > config.max_secondary_items > 0:
            remaining = len(tasks) - config.max_secondary_items
            lines.append(f"    • … 其余 {remaining} 项任务")

    if len(items) > config.max_primary_items:
        lines.append(f"  - … 其余 {len(items) - config.max_primary_items} 个愿景")
    return lines


def _render_notes_section(
    payload: Optional[Dict[str, Any]], config: SectionConfig
) -> List[str]:
    if not isinstance(payload, dict):
        return []

    count = payload.get("count", 0)
    lines = [f"- 笔记数量：{count}"]

    items = payload.get("items") or []
    for note in items[: config.max_primary_items]:
        content = (note.get("content") or "").strip()
        if not content:
            summary = "(空内容)"
        else:
            first_line = content.splitlines()[0]
            summary = first_line[:120] + ("…" if len(first_line) > 120 else "")
        lines.append(f"  - {summary}")

    if len(items) > config.max_primary_items:
        lines.append(f"  - … 其余 {len(items) - config.max_primary_items} 条笔记")
    return lines


def _format_section(title: str, lines: Iterable[str]) -> str:
    body = list(lines)
    if not body:
        body = ["- 暂无可用数据。"]
    return "\n".join([title, *body])


def _compose_document(target_date: date, sections: List[str]) -> str:
    header = f"# 每日复盘原始数据（{target_date.isoformat()}）"
    return "\n\n".join([header, *sections])
