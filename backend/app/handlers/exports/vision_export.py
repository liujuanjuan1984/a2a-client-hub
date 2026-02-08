"""
Vision export service
"""

from typing import Any, Dict, List, Set, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.actual_event import ActualEvent
from app.db.models.task import Task
from app.db.models.vision import Vision
from app.handlers import user_preferences as user_preferences_service
from app.handlers.exports.export_base import BaseExportService, ExportFormatter
from app.handlers.tasks import get_vision_task_hierarchy
from app.schemas.export import ExportParams, VisionExportParams
from app.serialization.entities import build_task_summary

# Priority and status translation keys
PRIORITY_KEYS = [
    "export.vision.priority.p1",
    "export.vision.priority.p2",
    "export.vision.priority.p3",
    "export.vision.priority.p4",
    "export.vision.priority.p5",
    "export.vision.priority.p6",
]

# Status translation keys
STATUS_KEYS = {
    "todo": "export.vision.status.todo",
    "in_progress": "export.vision.status.in_progress",
    "done": "export.vision.status.done",
    "completed": "export.vision.status.completed",
    "cancelled": "export.vision.status.cancelled",
    "paused": "export.vision.status.paused",
    "postponed": "export.vision.status.postponed",
}


def get_stage_key(stage: int) -> str:
    """Return translation key for stage description."""
    stage_keys = [
        "export.vision.stage.seed",
        "export.vision.stage.sprout",
        "export.vision.stage.growth",
        "export.vision.stage.expansion",
        "export.vision.stage.mature",
        "export.vision.stage.harvest",
        "export.vision.stage.legacy",
        "export.vision.stage.transcend",
        "export.vision.stage.complete",
        "export.vision.stage.elevate",
    ]
    if 0 <= stage < len(stage_keys):
        return stage_keys[stage]
    return "export.vision.stage.generic"


class VisionExportService(BaseExportService):
    """Export service for vision data."""

    def __init__(self, locale: str = "zh-CN") -> None:
        super().__init__(locale)
        self._logger = get_logger(__name__)
        self._time_spent_map: Dict[UUID, int] = {}

    def set_time_spent_map(self, time_spent_map: Dict[UUID, int]) -> None:
        """Inject pre-computed time spend map for tasks."""
        self._time_spent_map = time_spent_map

    def generate_export_text(self, params: ExportParams, data: Any) -> str:
        """
        Generate export text for vision data.

        Args:
            params: VisionExportParams
            data: Dictionary containing vision and task hierarchy

        Returns:
            Formatted export text
        """
        if not isinstance(params, VisionExportParams):
            raise ValueError("Expected VisionExportParams")

        vision = data.get("vision")
        tasks = data.get("tasks", [])

        if not vision:
            return self._create_empty_export()

        lines = []

        # Vision header
        lines.extend(self._create_vision_header(vision))

        # Task tree
        if tasks:
            lines.extend(self._create_task_tree_section(tasks, params))
        else:
            lines.append(self.t("export.vision.task_tree.empty"))

        return "\n".join(lines)

    def _create_empty_export(self) -> str:
        """Create export for empty vision data."""
        return self.t("export.vision.empty")

    def _create_vision_header(self, vision: Vision) -> List[str]:
        """Create the vision header section."""
        vision_name = vision.name or self.t("export.vision.unnamed")
        lines = [self.t("export.vision.name_line", name=vision_name)]

        if vision.description:
            lines.append(self.t("export.vision.description", text=vision.description))

        # Stage information
        if hasattr(vision, "stage") and vision.stage is not None:
            stage_key = get_stage_key(vision.stage)
            stage_text = self.t(stage_key, value=vision.stage)
            stage_value = vision.stage
        else:
            stage_text = self.t("export.vision.stage.unknown")
            stage_value = 0
        lines.append(
            self.t(
                "export.vision.stage",
                stage_text=stage_text,
                stage_value=stage_value,
            )
        )

        # Experience points
        if hasattr(vision, "experience_points"):
            lines.append(
                self.t("export.vision.experience", value=vision.experience_points)
            )

        # Total effort
        if hasattr(vision, "total_actual_effort") and vision.total_actual_effort:
            effort_text = self.format_duration(vision.total_actual_effort)
            lines.append(self.t("export.vision.total_effort", duration=effort_text))

        # Dates
        if vision.created_at:
            created_str = self.format_datetime(vision.created_at)
            lines.append(self.t("export.vision.created_at", datetime=created_str))

        if vision.updated_at:
            updated_str = self.format_datetime(vision.updated_at)
            lines.append(self.t("export.vision.updated_at", datetime=updated_str))

        lines.append("")  # Empty line for separation
        return lines

    def _create_task_tree_section(
        self, tasks: List[Task], params: VisionExportParams
    ) -> List[str]:
        """Create the task tree section."""
        lines = [
            self.t("export.vision.task_tree.title", count=len(tasks)),
            "",
        ]

        # Format tasks recursively
        self._format_tasks_recursively(tasks, lines, params)

        return lines

    def _format_tasks_recursively(
        self,
        tasks: List[Task],
        lines: List[str],
        params: VisionExportParams,
        depth: int = 0,
    ) -> None:
        """Format tasks using an explicit stack to avoid recursion depth issues."""
        if not tasks:
            return

        visited: Set[Any] = set()
        stack: List[Tuple[Task, int]] = [(task, depth) for task in reversed(tasks)]

        while stack:
            current_task, current_depth = stack.pop()
            marker = getattr(current_task, "id", None) or id(current_task)

            if marker in visited:
                self._logger.warning(
                    "Detected cycle in task hierarchy while exporting task %s",
                    getattr(current_task, "id", None),
                )
                continue

            visited.add(marker)
            task_lines = self._format_single_task(current_task, current_depth, params)
            lines.extend(task_lines)

            if (
                params.include_subtasks
                and hasattr(current_task, "subtasks")
                and current_task.subtasks
            ):
                # Push children in reverse so they are processed in original order.
                for child in reversed(list(current_task.subtasks)):
                    stack.append((child, current_depth + 1))

    def _format_single_task(
        self, task: Task, depth: int, params: VisionExportParams
    ) -> List[str]:
        """Format a single task with all its details on a single line."""

        summary_model = build_task_summary(task)
        if summary_model is None:
            return []
        summary_payload = summary_model.model_dump(mode="json", exclude_none=True)

        # Use tree-style indentation similar to TaskSelector
        if depth > 0:
            indent = "    " * (depth - 1) + "└── "
        else:
            indent = ""

        # Status label
        status_value = summary_payload.get("status") or "todo"
        status_key = STATUS_KEYS.get(status_value, STATUS_KEYS["todo"])
        status_label = self.t(status_key)

        # Priority label
        priority = summary_payload.get("priority", 0) or 0
        priority_index = max(0, min(5, priority))
        priority_label = self.t(PRIORITY_KEYS[priority_index])

        # Main task line with all details
        content = ExportFormatter.clean_text(summary_payload.get("content") or "")
        main_line = f"{indent}{status_label} {priority_label} {content}"

        # Add details to the same line
        details_added = []

        # Time information (consolidated logic)
        record_minutes = (
            self._time_spent_map.get(task.id, 0) if params.include_time_records else 0
        )
        record_text = (
            self.format_duration(record_minutes) if record_minutes > 0 else None
        )

        actual_minutes = summary_payload.get("actual_effort_total") or 0
        actual_text = (
            self.format_duration(actual_minutes) if actual_minutes > 0 else None
        )

        if record_text and actual_text:
            if abs(record_minutes - actual_minutes) <= 5:
                details_added.append(
                    self.t("export.vision.detail.total", duration=actual_text)
                )
            else:
                details_added.append(
                    self.t("export.vision.detail.record", duration=record_text)
                )
                details_added.append(
                    self.t("export.vision.detail.total", duration=actual_text)
                )
        elif record_text:
            details_added.append(
                self.t("export.vision.detail.record", duration=record_text)
            )
        elif actual_text:
            details_added.append(
                self.t("export.vision.detail.total", duration=actual_text)
            )

        # Estimated effort
        if summary_payload.get("estimated_effort"):
            estimated_text = self.format_duration(summary_payload["estimated_effort"])
            details_added.append(
                self.t("export.vision.detail.estimate", duration=estimated_text)
            )

        # Persons
        if hasattr(task, "persons") and task.persons:
            person_names = [
                p.name or p.display_name or p.primary_nickname
                for p in task.persons
                if p
            ]
            if person_names:
                persons_str = ", ".join(person_names)
                details_added.append(
                    self.t("export.vision.detail.assignees", names=persons_str)
                )

        # Append all details to the main line if any exist
        if details_added:
            main_line += f" [{', '.join(details_added)}]"

        return [main_line]


async def export_vision_data(
    db: AsyncSession, params: VisionExportParams, user_id: str, vision_id: str
) -> str:
    """
    Export vision data for a user.

    Args:
        db: Database session
        params: Export parameters
        user_id: User ID
        vision_id: Vision ID to export

    Returns:
        Formatted export text
    """
    # Convert user_id and vision_id to UUID
    user_uuid = UUID(user_id)
    vision_uuid = UUID(vision_id)

    export_locale = await user_preferences_service.resolve_language_preference(
        db, user_id=user_uuid
    )
    service = VisionExportService(locale=export_locale)

    # Query vision
    stmt = (
        select(Vision)
        .where(Vision.id == vision_uuid, Vision.user_id == user_uuid)
        .limit(1)
    )
    vision = (await db.execute(stmt)).scalars().first()

    if not vision:
        return service.t("export.vision.not_found")

    # Use existing get_vision_task_hierarchy function
    task_hierarchy = await get_vision_task_hierarchy(
        db, user_id=user_uuid, vision_id=vision_uuid
    )

    # Extract root tasks from the hierarchy
    tasks = task_hierarchy.root_tasks if hasattr(task_hierarchy, "root_tasks") else []

    # Prepare time records map when requested
    time_spent_map: Dict[UUID, int] = {}

    if params.include_time_records and tasks:

        def _collect_task_ids(task_list: List[Any]) -> Set[UUID]:
            task_ids: Set[UUID] = set()
            for item in task_list:
                task_ids.add(item.id)
                if getattr(item, "subtasks", None):
                    task_ids.update(_collect_task_ids(item.subtasks))
            return task_ids

        task_ids = _collect_task_ids(tasks)

        if task_ids:
            stmt = select(ActualEvent).where(
                ActualEvent.task_id.in_(list(task_ids)),
                ActualEvent.deleted_at.is_(None),
                ActualEvent.start_time.isnot(None),
                ActualEvent.end_time.isnot(None),
            )
            time_entries = (await db.execute(stmt)).scalars().all()

            for entry in time_entries:
                if not entry.task_id or not entry.start_time or not entry.end_time:
                    continue
                try:
                    duration_minutes = int(
                        (entry.end_time - entry.start_time).total_seconds() / 60
                    )
                except Exception:
                    duration_minutes = 0

                if duration_minutes < 0:
                    continue

                current_total = time_spent_map.get(entry.task_id, 0)
                time_spent_map[entry.task_id] = current_total + duration_minutes

    service.set_time_spent_map(time_spent_map)

    # Prepare data for export
    data = {"vision": vision, "tasks": tasks}

    # Generate export text
    return service.generate_export_text(params, data)


async def estimate_vision_export(
    db: AsyncSession, params: VisionExportParams, user_id: str, vision_id: str
) -> tuple[int, int]:
    user_uuid = UUID(user_id)
    vision_uuid = UUID(vision_id)
    task_hierarchy = await get_vision_task_hierarchy(
        db, user_id=user_uuid, vision_id=vision_uuid
    )
    tasks = task_hierarchy.root_tasks if hasattr(task_hierarchy, "root_tasks") else []
    count = len(tasks)
    estimated_size = count * 600
    return count, estimated_size
