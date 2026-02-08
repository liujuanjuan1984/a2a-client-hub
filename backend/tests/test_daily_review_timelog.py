from __future__ import annotations

import pytest

from app.review.daily_review_builder import (
    SectionConfig,
    _render_notes_section,
    _render_timelog_section,
    _render_vision_section,
)

pytestmark = pytest.mark.unit


def test_render_timelog_section_with_range_and_entries():
    config = SectionConfig(title="Timelog", max_primary_items=2)
    payload = {
        "range": {"start": "2024-01-01T00:00:00Z", "end": "2024-01-01T23:59:59Z"},
        "entries": [
            {
                "title": "Morning Deep Work",
                "start_time": "09:00",
                "duration_minutes": 120,
            },
            {
                "title": "Lunch",
                "start_time": "12:30",
                "duration_minutes": 30,
            },
            {
                "title": "Evening Review",
                "duration_minutes": 45,
            },
        ],
    }

    lines = _render_timelog_section(payload, config)

    assert lines[0] == "- 时间范围：2024-01-01T00:00:00Z ~ 2024-01-01T23:59:59Z"
    assert "- 记录数：3" in lines
    assert "  - Morning Deep Work (09:00; 120 分钟)" in lines
    assert "  - Lunch (12:30; 30 分钟)" in lines
    assert lines[-1] == "  - … 其余 1 条记录"


def test_render_timelog_section_handles_missing_payload_fields():
    config = SectionConfig(title="Timelog", max_primary_items=3)
    payload = {
        "entries": [
            {"title": "Unnamed"},
            {},
        ],
    }

    lines = _render_timelog_section(payload, config)

    assert lines[0] == "- 记录数：2"
    assert "  - Unnamed" in lines
    assert "  - 未命名事件" in lines


def test_render_timelog_section_invalid_payload_returns_empty_list():
    assert _render_timelog_section(None, SectionConfig(title="Timelog")) == []
    assert _render_timelog_section("not a dict", SectionConfig(title="Timelog")) == []


def test_render_notes_section_with_content_and_limits():
    config = SectionConfig(title="Notes", max_primary_items=2)
    payload = {
        "count": 4,
        "items": [
            {"content": "第一条笔记\n包含多行"},
            {"content": "第二条笔记"},
            {"content": "第三条笔记"},
        ],
    }

    lines = _render_notes_section(payload, config)

    assert lines[0] == "- 笔记数量：4"
    assert "  - 第一条笔记" in lines[1]
    assert lines[2] == "  - 第二条笔记"
    assert lines[-1] == "  - … 其余 1 条笔记"


def test_render_notes_section_truncates_and_handles_empty():
    config = SectionConfig(title="Notes", max_primary_items=3)
    long_text = "A" * 150
    payload = {
        "count": 2,
        "items": [
            {"content": long_text},
            {"content": "   \t"},
        ],
    }

    lines = _render_notes_section(payload, config)

    assert lines[0] == "- 笔记数量：2"
    assert lines[1].endswith("…") and len(lines[1]) <= len("  - ") + 120 + 1
    assert lines[2] == "  - (空内容)"


def test_render_notes_section_invalid_payload():
    assert _render_notes_section(None, SectionConfig(title="Notes")) == []
    assert _render_notes_section("notes", SectionConfig(title="Notes")) == []


def test_render_vision_section_with_items_and_limits():
    config = SectionConfig(title="Vision", max_primary_items=1, max_secondary_items=1)
    payload = {
        "count": {"visions": 3, "tasks": 5},
        "items": [
            {
                "vision": {"name": "长远目标"},
                "tasks": [
                    {"content": "任务A", "status": "in_progress"},
                    {"content": "任务B", "status": "todo"},
                ],
            },
            {
                "vision": {"name": "备用目标"},
                "tasks": [],
            },
        ],
    }

    lines = _render_vision_section(payload, config)

    assert lines[0] == "- 愿景数量：3"
    assert lines[1] == "- 任务数量：5"
    assert "  - 长远目标（任务 2 项）" in lines
    assert "    • 任务A [in_progress]" in lines
    assert lines[-2] == "    • … 其余 1 项任务"
    assert lines[-1] == "  - … 其余 1 个愿景"


def test_render_vision_section_invalid_and_empty_payload():
    assert _render_vision_section(None, SectionConfig(title="Vision")) == []
    assert _render_vision_section("invalid", SectionConfig(title="Vision")) == []

    empty_lines = _render_vision_section({"items": []}, SectionConfig(title="Vision"))
    assert empty_lines == ["- 愿景数量：0", "- 任务数量：0"]
