"""Simple translation utilities for backend services."""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, Iterable

DEFAULT_LOCALE = "zh"
SUPPORTED_LOCALES = {"zh", "en"}

_LOCALE_ALIASES = {
    "zh": "zh",
    "zh_cn": "zh",
    "zh-hans": "zh",
    "zh-hans-cn": "zh",
    "en": "en",
    "en-us": "en",
    "en_us": "en",
    "en-gb": "en",
}


def normalize_locale(raw_locale: str | None) -> str:
    """Normalize incoming locale values to a supported locale."""
    if not raw_locale:
        return DEFAULT_LOCALE

    lowered = raw_locale.strip().lower().replace("_", "-")
    if lowered in _LOCALE_ALIASES:
        return _LOCALE_ALIASES[lowered]

    if lowered.startswith("zh"):
        return "zh"

    if lowered.startswith("en"):
        return "en"

    return DEFAULT_LOCALE


class Translator:
    """In-memory translator with simple fallback chain."""

    def __init__(self, locale: str) -> None:
        self.locale = normalize_locale(locale)
        self._fallbacks: Iterable[str] = self._build_fallback_chain(self.locale)

    @staticmethod
    def _build_fallback_chain(locale: str) -> Iterable[str]:
        chain = [locale]
        if locale != "en":
            chain.append("en")
        if locale != DEFAULT_LOCALE:
            chain.append(DEFAULT_LOCALE)
        return chain

    def gettext(self, key: str, default: str | None = None, **kwargs) -> str:
        """Return translated text for *key*, formatted with kwargs when provided."""
        text: str | None = None

        for loc in self._fallbacks:
            catalog = _TRANSLATIONS.get(loc)
            if catalog and key in catalog:
                text = catalog[key]
                break

        if text is None:
            text = default if default is not None else key

        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, ValueError):  # Gracefully ignore formatting issues
                pass
        return text

    __call__ = gettext


@lru_cache(maxsize=16)
def get_translator(locale: str | None) -> Translator:
    """Cached translator accessor."""
    return Translator(locale or DEFAULT_LOCALE)


# Translation catalog -------------------------------------------------------

_TRAN_ = {
    "export.common.query_conditions": {
        "zh": "查询条件：",
        "en": "Query Conditions:",
    },
    "export.common.start_date": {"zh": "开始日期：", "en": "Start Date:"},
    "export.common.end_date": {"zh": "结束日期：", "en": "End Date:"},
    "export.common.dimension_filter": {
        "zh": "维度筛选：",
        "en": "Dimension Filter:",
    },
    "export.common.keyword": {"zh": "关键词：", "en": "Keyword:"},
    "export.common.statistics": {"zh": "统计信息：", "en": "Statistics:"},
    "export.common.stats.total_records": {
        "zh": "总记录数：{count} 条",
        "en": "Total records: {count}",
    },
    "export.common.stats.total_duration": {
        "zh": "总时长：{duration}",
        "en": "Total duration: {duration}",
    },
    "export.common.data_list": {"zh": "数据列表：", "en": "Data List:"},
    "export.common.no_data": {"zh": "无数据", "en": "No data"},
    "export.common.dimension_stats.title": {
        "zh": "按维度统计：",
        "en": "By dimension:",
    },
    "export.common.dimension_stats.header": {
        "zh": "维度\t记录数\t总时长\t占比",
        "en": "Dimension\tRecords\tDuration\tShare",
    },
    "export.common.dimension_stats.total": {
        "zh": "总计\t{count}\t{duration}\t{percentage}%",
        "en": "Total\t{count}\t{duration}\t{percentage}%",
    },
    "export.common.export_success": {"zh": "导出成功", "en": "Export successful"},
    "export.common.export_failed": {"zh": "导出失败", "en": "Export failed"},
    "export.common.duration.hour": {"zh": "小时", "en": "h"},
    "export.common.duration.minute": {"zh": "分钟", "en": "m"},
    "export.common.unknown": {"zh": "未知", "en": "Unknown"},
    "export.common.task": {"zh": "任务", "en": "Task"},
    "export.common.notes": {"zh": "备注", "en": "Notes"},
    # Planning export
    "export.planning.header": {"zh": "规划导出", "en": "Planning Export"},
    "export.planning.empty.title": {
        "zh": "=== 规划{view_label}：{date} ===",
        "en": "=== Planning {view_label}: {date} ===",
    },
    "export.planning.empty.total": {
        "zh": "总任务数：0",
        "en": "Total tasks: 0",
    },
    "export.planning.empty.list_title": {
        "zh": "任务列表：",
        "en": "Task List:",
    },
    "export.planning.empty.no_tasks": {"zh": "暂无任务", "en": "No tasks"},
    "export.planning.view.year": {"zh": "年视图", "en": "Year"},
    "export.planning.view.month": {"zh": "月视图", "en": "Month"},
    "export.planning.view.week": {"zh": "周视图", "en": "Week"},
    "export.planning.view.day": {"zh": "日视图", "en": "Day"},
    "export.planning.view_line": {
        "zh": "{view_label}：{date}",
        "en": "{view_label}: {date}",
    },
    "export.planning.stats.total": {
        "zh": "总任务数：{count}{status_details}",
        "en": "Total tasks: {count}{status_details}",
    },
    "export.planning.stats.status_detail": {
        "zh": " ({details})",
        "en": " ({details})",
    },
    "export.planning.task_list.title": {
        "zh": "任务列表：",
        "en": "Task List:",
    },
    "export.planning.task_list.header": {
        "zh": "序号\t状态\t愿景\t时长\t内容\t创建时间",
        "en": "#\tStatus\tVision\tDuration\tContent\tCreated At",
    },
    "export.planning.status.todo": {"zh": "待办", "en": "Todo"},
    "export.planning.status.in_progress": {"zh": "进行中", "en": "In progress"},
    "export.planning.status.done": {"zh": "已完成", "en": "Done"},
    "export.planning.status.paused": {"zh": "暂停", "en": "Paused"},
    "export.planning.status.cancelled": {"zh": "已取消", "en": "Cancelled"},
    "export.planning.notes.title": {
        "zh": "相关笔记：",
        "en": "Related Notes:",
    },
    "export.planning.notes.none": {
        "zh": "暂无相关笔记",
        "en": "No related notes",
    },
    "export.planning.notes.summary": {
        "zh": "共找到 {count} 条相关笔记：",
        "en": "Found {count} related notes:",
    },
    "export.planning.notes.date_section": {
        "zh": "时间段笔记：",
        "en": "Notes in Date Range:",
    },
    "export.planning.group.title": {"zh": "分组：{label}", "en": "Group: {label}"},
    "export.planning.group.date": {"zh": "日期：{date}", "en": "Date: {date}"},
    "export.planning.group.task_count": {
        "zh": "任务数：{count}",
        "en": "Task count: {count}",
    },
    "export.planning.group.duration": {
        "zh": "时长：{duration}",
        "en": "Duration: {duration}",
    },
    "export.planning.group.task_list_header": {
        "zh": "序号\t状态\t愿景\t时长\t内容\t创建时间",
        "en": "#\tStatus\tVision\tDuration\tContent\tCreated At",
    },
    "export.planning.group.label.week": {
        "zh": "{date} 当周",
        "en": "Week of {date}",
    },
    "export.planning.group.label.month": {
        "zh": "{date} 当月",
        "en": "Month of {date}",
    },
    "export.planning.group.label.year": {
        "zh": "{year} 年",
        "en": "Year {year}",
    },
    "export.planning.no_vision": {"zh": "未知愿景", "en": "Unknown vision"},
    "export.planning.notes.header": {
        "zh": "任务笔记",
        "en": "Task Notes",
    },
    "export.planning.notes.date_range_header": {
        "zh": "日期范围笔记",
        "en": "Date Range Notes",
    },
    "export.planning.notes.for_task": {
        "zh": "任务 {task_index} 的笔记：",
        "en": "Notes for task {task_index}:",
    },
    # Notes export
    "export.notes.header": {"zh": "笔记搜索结果", "en": "Notes Search Results"},
    "export.notes.empty.title": {
        "zh": "=== 笔记导出 ===",
        "en": "=== Notes Export ===",
    },
    "export.notes.empty.no_match": {
        "zh": "筛选条件：无匹配结果",
        "en": "Filters: No matching results",
    },
    "export.notes.search_conditions": {
        "zh": "搜索条件：",
        "en": "Search Conditions:",
    },
    "export.notes.filter.tags": {
        "zh": "标签筛选：{tags}",
        "en": "Tag filters: {tags}",
    },
    "export.notes.filter.persons": {
        "zh": "人员筛选：{persons}",
        "en": "Person filters: {persons}",
    },
    "export.notes.filter.keyword": {
        "zh": "关键词搜索：{keyword}",
        "en": "Keyword search: {keyword}",
    },
    "export.notes.filter.none": {
        "zh": "筛选条件：无（显示全部笔记）",
        "en": "Filters: None (showing all notes)",
    },
    "export.notes.note.created_at": {
        "zh": "==========创建日期: {datetime}=========",
        "en": "==========Created At: {datetime}=========",
    },
    "export.notes.note.related_persons": {
        "zh": "相关人: {persons}",
        "en": "Related persons: {persons}",
    },
    "export.notes.note.tags": {
        "zh": "标签: {tags}",
        "en": "Tags: {tags}",
    },
    "export.notes.note.related_task": {
        "zh": "相关任务: {task}",
        "en": "Related task: {task}",
    },
    "export.notes.note.related_task_with_status": {
        "zh": "相关任务: {task} ({status})",
        "en": "Related task: {task} ({status})",
    },
    # Timelog export
    "export.timelog.header": {
        "zh": "高级查询结果",
        "en": "Advanced Query Results",
    },
    "export.timelog.empty.title": {
        "zh": "=== 时间记录导出 ===",
        "en": "=== Time Logs Export ===",
    },
    "export.timelog.table.header": {
        "zh": "日期\t开始时间\t结束时间\t时长\t维度\t行为描述\t相关任务\t相关人",
        "en": "Date\tStart\tEnd\tDuration\tDimension\tDescription\tRelated Task\tRelated People",
    },
    "export.timelog.dimension.unknown": {
        "zh": "未知维度",
        "en": "Unknown dimension",
    },
    "export.timelog.task.vision_label": {
        "zh": "愿景: ",
        "en": "Vision: ",
    },
    "export.timelog.task.vision_unknown": {
        "zh": "未知愿景",
        "en": "Unknown vision",
    },
    "export.timelog.task.status_label": {
        "zh": "状态: ",
        "en": "Status: ",
    },
    "export.timelog.task.status_unknown": {
        "zh": "未知状态",
        "en": "Unknown status",
    },
    # Vision export
    "export.vision.header": {"zh": "愿景导出", "en": "Vision Export"},
    "export.vision.empty": {
        "zh": "=== 愿景导出 ===\n\n暂无愿景数据",
        "en": "=== Vision Export ===\n\nNo vision data",
    },
    "export.vision.not_found": {
        "zh": "=== 愿景导出 ===\n\n愿景不存在或无权访问",
        "en": "=== Vision Export ===\n\nVision not found or access denied",
    },
    "export.vision.name_line": {
        "zh": "[愿景] {name}",
        "en": "[Vision] {name}",
    },
    "export.vision.unnamed": {"zh": "未命名愿景", "en": "Untitled vision"},
    "export.vision.description": {
        "zh": "[描述] {text}",
        "en": "[Description] {text}",
    },
    "export.vision.stage": {
        "zh": "[阶段] {stage_text} ({stage_value}/10)",
        "en": "[Stage] {stage_text} ({stage_value}/10)",
    },
    "export.vision.stage.unknown": {"zh": "未知阶段", "en": "Unknown stage"},
    "export.vision.experience": {
        "zh": "[经验值] {value}",
        "en": "[Experience] {value}",
    },
    "export.vision.total_effort": {
        "zh": "[总投入] {duration}",
        "en": "[Total effort] {duration}",
    },
    "export.vision.created_at": {
        "zh": "[创建时间] {datetime}",
        "en": "[Created At] {datetime}",
    },
    "export.vision.updated_at": {
        "zh": "[最后更新] {datetime}",
        "en": "[Last Updated] {datetime}",
    },
    "export.vision.task_tree.title": {
        "zh": "[任务树] 共 {count} 个根任务:",
        "en": "[Task Tree] {count} root tasks:",
    },
    "export.vision.task_tree.empty": {
        "zh": "[任务树] 暂无任务",
        "en": "[Task Tree] No tasks",
    },
    "export.vision.stage.seed": {"zh": "种子期", "en": "Seed"},
    "export.vision.stage.sprout": {"zh": "发芽期", "en": "Sprout"},
    "export.vision.stage.growth": {"zh": "成长期", "en": "Growth"},
    "export.vision.stage.expansion": {"zh": "扩张期", "en": "Expansion"},
    "export.vision.stage.mature": {"zh": "成熟期", "en": "Mature"},
    "export.vision.stage.harvest": {"zh": "收获期", "en": "Harvest"},
    "export.vision.stage.legacy": {"zh": "传承期", "en": "Legacy"},
    "export.vision.stage.transcend": {"zh": "超越期", "en": "Transcend"},
    "export.vision.stage.complete": {"zh": "圆满期", "en": "Complete"},
    "export.vision.stage.elevate": {"zh": "升华期", "en": "Elevate"},
    "export.vision.stage.generic": {"zh": "阶段 {value}", "en": "Stage {value}"},
    "export.vision.priority.p1": {
        "zh": "[P1] 最高优先级",
        "en": "[P1] Highest priority",
    },
    "export.vision.priority.p2": {"zh": "[P2] 高优先级", "en": "[P2] High priority"},
    "export.vision.priority.p3": {
        "zh": "[P3] 中优先级",
        "en": "[P3] Medium priority",
    },
    "export.vision.priority.p4": {"zh": "[P4] 低优先级", "en": "[P4] Low priority"},
    "export.vision.priority.p5": {
        "zh": "[P5] 最低优先级",
        "en": "[P5] Lowest priority",
    },
    "export.vision.priority.p6": {"zh": "[P6] 无优先级", "en": "[P6] No priority"},
    "export.vision.status.todo": {"zh": "[待办]", "en": "[Todo]"},
    "export.vision.status.in_progress": {"zh": "[进行中]", "en": "[In progress]"},
    "export.vision.status.done": {"zh": "[已完成]", "en": "[Done]"},
    "export.vision.status.completed": {"zh": "[已完成]", "en": "[Completed]"},
    "export.vision.status.cancelled": {"zh": "[已取消]", "en": "[Cancelled]"},
    "export.vision.status.paused": {"zh": "[已暂停]", "en": "[Paused]"},
    "export.vision.status.postponed": {"zh": "[已推迟]", "en": "[Postponed]"},
    "export.vision.detail.record": {
        "zh": "记录: {duration}",
        "en": "Recorded: {duration}",
    },
    "export.vision.detail.total": {
        "zh": "累计: {duration}",
        "en": "Total: {duration}",
    },
    "export.vision.detail.estimate": {
        "zh": "预估: {duration}",
        "en": "Estimate: {duration}",
    },
    "export.vision.detail.notes": {"zh": "备注: {text}", "en": "Notes: {text}"},
    "export.vision.detail.assignees": {
        "zh": "负责人: {names}",
        "en": "Assignees: {names}",
    },
    # Onboarding default dimensions
    "onboarding.dimension.health.name": {"zh": "健康", "en": "Health"},
    "onboarding.dimension.health.description": {
        "zh": "关注身体与心理健康的日常投入。",
        "en": "Focus on daily actions that support physical and mental wellbeing.",
    },
    "onboarding.dimension.growth.name": {"zh": "成长", "en": "Growth"},
    "onboarding.dimension.growth.description": {
        "zh": "持续学习与自我提升的探索与实践。",
        "en": "Continual learning and personal development activities.",
    },
    "onboarding.dimension.family.name": {"zh": "家庭", "en": "Family"},
    "onboarding.dimension.family.description": {
        "zh": "与家人建立连结、照顾家庭关系的时间。",
        "en": "Time invested in nurturing family connections and responsibilities.",
    },
    "onboarding.dimension.work.name": {"zh": "工作", "en": "Work"},
    "onboarding.dimension.work.description": {
        "zh": "推进职业与事业目标的任务与项目。",
        "en": "Tasks and projects that advance professional and career goals.",
    },
    "onboarding.dimension.wealth.name": {"zh": "财富", "en": "Wealth"},
    "onboarding.dimension.wealth.description": {
        "zh": "提升财务健康与资源配置的活动。",
        "en": "Activities that strengthen financial health and resource management.",
    },
    "onboarding.dimension.relationships.name": {"zh": "人际", "en": "Relationships"},
    "onboarding.dimension.relationships.description": {
        "zh": "拓展并维护社交网络与重要伙伴关系。",
        "en": "Building and sustaining meaningful social and community relationships.",
    },
    "onboarding.dimension.leisure.name": {"zh": "休闲", "en": "Leisure"},
    "onboarding.dimension.leisure.description": {
        "zh": "让身心放松、激发灵感的休闲与兴趣。",
        "en": "Recreational and hobby activities that relax and inspire.",
    },
    "onboarding.dimension.contribution.name": {"zh": "贡献", "en": "Contribution"},
    "onboarding.dimension.contribution.description": {
        "zh": "回馈社会、支持他人或公共事务的投入。",
        "en": "Efforts that give back to others and support shared causes.",
    },
    "onboarding.dimension.other.name": {"zh": "其它", "en": "Other"},
    "onboarding.dimension.other.description": {
        "zh": "暂未归类或跨越多个维度的事项。",
        "en": "Items that span multiple areas or are not yet categorized.",
    },
    # API messages
    "export.api.timelog.success": {
        "zh": "时间记录导出成功",
        "en": "Time logs exported successfully",
    },
    "export.api.notes.success": {
        "zh": "笔记导出成功",
        "en": "Notes exported successfully",
    },
    "export.api.planning.success": {
        "zh": "规划导出成功",
        "en": "Planning exported successfully",
    },
    "export.api.vision.success": {
        "zh": "愿景导出成功",
        "en": "Vision exported successfully",
    },
}

_TRANSLATIONS: Dict[str, Dict[str, str]] = {locale: {} for locale in SUPPORTED_LOCALES}
for key, values in _TRAN_.items():
    for locale, text in values.items():
        _TRANSLATIONS.setdefault(locale, {})[key] = text
