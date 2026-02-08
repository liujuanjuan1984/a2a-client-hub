"""
Planning export service
"""

from datetime import datetime
from typing import Any, Dict, List
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actual_event import ActualEvent
from app.db.models.vision import Vision
from app.handlers import notes as note_service
from app.handlers import user_preferences as user_preferences_service
from app.handlers.exports.export_base import BaseExportService, ExportFormatter
from app.handlers.exports.notes_export import NotesExportService
from app.handlers.tasks import (
    _get_cycle_date_range,
    _get_user_calendar_system,
    list_tasks,
)
from app.schemas.export import ExportParams, ExportStatistics, PlanningExportParams
from app.serialization.entities import serialize_note as core_serialize_note
from app.serialization.entities import serialize_task as core_serialize_task


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.lower() == "true"
    return default


def _serialize_task_for_export(task_obj: Any) -> Dict[str, Any]:
    if not task_obj:
        return {}

    payload = {
        "id": getattr(task_obj, "id", None),
        "vision_id": getattr(task_obj, "vision_id", None),
        "parent_task_id": getattr(task_obj, "parent_task_id", None),
        "title": getattr(task_obj, "title", None),
        "content": getattr(task_obj, "content", None),
        "notes_count": getattr(task_obj, "notes_count", None),
        "status": getattr(task_obj, "status", None),
        "priority": getattr(task_obj, "priority", None),
        "display_order": getattr(task_obj, "display_order", None),
        "estimated_effort": getattr(task_obj, "estimated_effort", None),
        "actual_effort_self": getattr(task_obj, "actual_effort_self", None),
        "actual_effort_total": getattr(task_obj, "actual_effort_total", None),
        "planning_cycle_type": getattr(task_obj, "planning_cycle_type", None),
        "planning_cycle_days": getattr(task_obj, "planning_cycle_days", None),
        "planning_cycle_start_date": getattr(
            task_obj, "planning_cycle_start_date", None
        ),
        "created_at": getattr(task_obj, "created_at", None),
        "updated_at": getattr(task_obj, "updated_at", None),
        "deleted_at": getattr(task_obj, "deleted_at", None),
    }
    serialized = core_serialize_task(
        payload,
        include_persons=False,
        include_subtasks=False,
    )
    return serialized or {}


class PlanningExportService(BaseExportService):
    """Export service for planning data."""

    def generate_export_text(self, params: ExportParams, data: Any) -> str:
        """
        Generate export text for planning data.

        Args:
            params: PlanningExportParams
            data: Dictionary containing planning groups, task time records, and vision map

        Returns:
            Formatted export text
        """
        if not isinstance(params, PlanningExportParams):
            raise ValueError("Expected PlanningExportParams")

        planning_groups = data.get("planning_groups", [])
        task_time_records = data.get("task_time_records", {})
        vision_map = data.get("vision_map", {})
        task_notes_map = data.get("task_notes_map", {})
        date_range_notes = data.get("date_range_notes", [])

        if not planning_groups:
            return self._create_empty_export(params)

        lines = []

        # Header
        header_title = self.t("export.planning.header")
        lines.extend(self.create_export_header(header_title))

        # Query conditions
        lines.extend(self._create_query_conditions_section(params))

        # Collect all tasks and calculate statistics
        all_tasks = self._collect_all_tasks(planning_groups)
        stats = self._calculate_planning_statistics(all_tasks, task_time_records)
        lines.extend(self._create_statistics_section(stats))

        # Task list (simplified, without group section)
        lines.extend(
            self._create_task_list_section(all_tasks, task_time_records, vision_map)
        )

        # Related notes section (if enabled and notes exist)
        if params.include_notes and (task_notes_map or date_range_notes):
            lines.extend(self._create_notes_section(task_notes_map, date_range_notes))

        return "\n".join(lines)

    def _create_empty_export(self, params: PlanningExportParams) -> str:
        """Create export for empty data."""
        view_label = self._get_view_label(params.view_type)
        title = self.t(
            "export.planning.empty.title",
            view_label=view_label,
            date=self.format_date(params.selected_date),
        )

        lines = [
            title,
            self.t("export.planning.empty.total"),
            "",
            self.t("export.planning.empty.list_title"),
            self.t("export.planning.empty.no_tasks"),
            "",
        ]
        return "\n".join(lines)

    def _get_view_label(self, view_type: str) -> str:
        """Resolve localized label for planning view type."""
        key = f"export.planning.view.{view_type}"
        return self.t(key, default=view_type)

    def _create_query_conditions_section(
        self, params: PlanningExportParams
    ) -> List[str]:
        """Create the query conditions section."""
        view_label = self._get_view_label(params.view_type)
        view_line = self.t(
            "export.planning.view_line",
            view_label=view_label,
            date=self.format_date(params.selected_date),
        )

        return [view_line]

    def _collect_all_tasks(self, planning_groups: List[Dict]) -> List[Dict]:
        """Collect all tasks from planning groups recursively."""
        all_tasks = []

        def collect_from_group(group):
            if "tasks" in group:
                all_tasks.extend(group["tasks"])
            if "children" in group:
                for child in group["children"]:
                    collect_from_group(child)

        for group in planning_groups:
            collect_from_group(group)

        return all_tasks

    def _calculate_planning_statistics(
        self, tasks: List[Dict], task_time_records: Dict
    ) -> ExportStatistics:
        """Calculate statistics for planning data."""
        total_duration_minutes = 0
        status_counts = {
            "todo": 0,
            "in_progress": 0,
            "done": 0,
            "paused": 0,
            "cancelled": 0,
        }

        for task in tasks:
            # Count status
            status = task.get("status", "todo")
            if status in status_counts:
                status_counts[status] += 1

            # Calculate time spent
            task_id = task.get("id")
            if task_id and task_id in task_time_records:
                time_records = task_time_records[task_id]
                for record in time_records:
                    if record.get("start_time") and record.get("end_time"):
                        start = datetime.fromisoformat(
                            record["start_time"].replace("Z", "+00:00")
                        )
                        end = datetime.fromisoformat(
                            record["end_time"].replace("Z", "+00:00")
                        )
                        duration_minutes = int((end - start).total_seconds() / 60)
                        total_duration_minutes += duration_minutes

        return ExportStatistics(
            total_records=len(tasks),
            total_duration_minutes=total_duration_minutes,
            status_distribution=status_counts,
        )

    def _create_statistics_section(self, stats: ExportStatistics) -> List[str]:
        """Create the statistics section with integrated status distribution."""
        lines = [self.t("export.common.statistics")]

        status_parts: List[str] = []
        if stats.status_distribution:
            for status, count in stats.status_distribution.items():
                if count > 0:
                    label = self.t(f"export.planning.status.{status}", default=status)
                    status_parts.append(f"{label}:{count}")

        if status_parts:
            details = ", ".join(status_parts)
            status_details = self.t(
                "export.planning.stats.status_detail", details=details
            )
        else:
            status_details = ""

        lines.append(
            self.t(
                "export.planning.stats.total",
                count=stats.total_records,
                status_details=status_details,
            )
        )

        if stats.total_duration_minutes:
            duration = self.format_duration(stats.total_duration_minutes)
            lines.append(
                self.t("export.common.stats.total_duration", duration=duration)
            )

        lines.append("")
        return lines

    def _create_task_list_section(
        self, tasks: List[Dict], task_time_records: Dict, vision_map: Dict
    ) -> List[str]:
        """Create a simplified task list section."""
        lines = [self.t("export.planning.task_list.title"), ""]

        if not tasks:
            lines.extend([self.t("export.planning.empty.no_tasks"), ""])
            return lines

        # Add table header
        lines.append(self.t("export.planning.task_list.header"))

        # Add tasks
        for i, task in enumerate(tasks, 1):
            lines.extend(
                self._format_simple_task_row(task, i, task_time_records, vision_map)
            )

        lines.append("")
        return lines

    def _format_simple_task_row(
        self, task: Dict, index: int, task_time_records: Dict, vision_map: Dict
    ) -> List[str]:
        """Format a single task row for the simplified task list."""
        # Status
        status = task.get("status", "todo")
        status_label = self.t(f"export.planning.status.{status}", default=status)

        # Vision name
        vision_id = task.get("vision_id")
        vision_name = self.t("export.planning.no_vision")
        if vision_id and vision_id in vision_map:
            vision_name = vision_map[vision_id].get(
                "name", self.t("export.planning.no_vision")
            )

        # Time spent
        task_id = task.get("id")
        time_spent = 0
        if task_id and task_id in task_time_records:
            time_records = task_time_records[task_id]
            for record in time_records:
                if record.get("start_time") and record.get("end_time"):
                    start = datetime.fromisoformat(
                        record["start_time"].replace("Z", "+00:00")
                    )
                    end = datetime.fromisoformat(
                        record["end_time"].replace("Z", "+00:00")
                    )
                    time_spent += int((end - start).total_seconds() / 60)
        time_str = self.format_duration(time_spent)

        # Content
        content = ExportFormatter.clean_text(task.get("content", ""))

        # Created time
        created_at = task.get("created_at", "")
        if isinstance(created_at, str):
            try:
                date_obj = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                created_str = self.format_datetime(date_obj)
            except Exception:
                created_str = created_at
        else:
            created_str = str(created_at)

        return [
            f"{index}\t{status_label}\t{vision_name}\t{time_str}\t{content}\t{created_str}"
        ]

    def _create_group_section(
        self,
        group: Dict,
        group_index: int,
        task_time_records: Dict,
        vision_map: Dict,
        params: PlanningExportParams,
        level: int = 0,
    ) -> List[str]:
        """Create a single group section."""
        lines = []
        indent = "  " * level

        # Group header
        group_label = group.get("label", f"Group {group_index}")
        group_date = group.get("date", "")
        if isinstance(group_date, str):
            try:
                date_obj = datetime.fromisoformat(group_date.replace("Z", "+00:00"))
                group_date = self.format_date(date_obj)
            except Exception:
                pass

        lines.append(
            f"{indent}" + self.t("export.planning.group.title", label=group_label)
        )
        lines.append(
            f"{indent}" + self.t("export.planning.group.date", date=group_date)
        )

        # Group tasks
        tasks = group.get("tasks", [])
        lines.append(
            f"{indent}" + self.t("export.planning.group.task_count", count=len(tasks))
        )

        # Calculate group time spent
        group_time = self._calculate_group_time_spent(tasks, task_time_records)
        lines.append(
            f"{indent}"
            + self.t(
                "export.planning.group.duration",
                duration=self.format_duration(group_time),
            )
        )
        lines.append(f"{indent}")

        # Task list
        if tasks:
            lines.append(f"{indent}" + self.t("export.planning.task_list.title"))
            lines.append(f"{indent}" + self.t("export.planning.group.task_list_header"))

            for task_index, task in enumerate(tasks):
                lines.extend(
                    self._format_task_row(
                        task,
                        group_index,
                        task_index + 1,
                        task_time_records,
                        vision_map,
                        indent,
                    )
                )

            lines.append(f"{indent}")

        # Process children groups recursively
        children = group.get("children", [])
        for child_index, child in enumerate(children):
            child_lines = self._create_group_section(
                child, group_index, task_time_records, vision_map, params, level + 1
            )
            lines.extend(child_lines)

        return lines

    def _calculate_group_time_spent(
        self, tasks: List[Dict], task_time_records: Dict
    ) -> int:
        """Calculate total time spent for a group of tasks."""
        total_minutes = 0

        for task in tasks:
            task_id = task.get("id")
            if task_id and task_id in task_time_records:
                time_records = task_time_records[task_id]
                for record in time_records:
                    if record.get("start_time") and record.get("end_time"):
                        start = datetime.fromisoformat(
                            record["start_time"].replace("Z", "+00:00")
                        )
                        end = datetime.fromisoformat(
                            record["end_time"].replace("Z", "+00:00")
                        )
                        duration_minutes = int((end - start).total_seconds() / 60)
                        total_minutes += duration_minutes

        return total_minutes

    def _format_task_row(
        self,
        task: Dict,
        group_index: int,
        task_index: int,
        task_time_records: Dict,
        vision_map: Dict,
        indent: str,
    ) -> List[str]:
        """Format a single task row."""
        # Task index
        index_str = f"{group_index}.{task_index}"

        # Status
        status = task.get("status", "todo")
        status_label = self.t(f"export.planning.status.{status}", default=status)

        # Vision name
        vision_id = task.get("vision_id")
        vision_name = self.t("export.planning.no_vision")
        if vision_id and vision_id in vision_map:
            vision_name = vision_map[vision_id].get(
                "name", self.t("export.planning.no_vision")
            )

        # Time spent
        task_id = task.get("id")
        time_spent = 0
        if task_id and task_id in task_time_records:
            time_records = task_time_records[task_id]
            for record in time_records:
                if record.get("start_time") and record.get("end_time"):
                    start = datetime.fromisoformat(
                        record["start_time"].replace("Z", "+00:00")
                    )
                    end = datetime.fromisoformat(
                        record["end_time"].replace("Z", "+00:00")
                    )
                    time_spent += int((end - start).total_seconds() / 60)
        time_str = self.format_duration(time_spent)

        # Content
        content = ExportFormatter.clean_text(task.get("content", ""))

        # Created time
        created_at = task.get("created_at", "")
        if isinstance(created_at, str):
            try:
                date_obj = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                created_str = self.format_datetime(date_obj)
            except Exception:
                created_str = created_at
        else:
            created_str = str(created_at)

        return [
            f"{indent}{index_str}\t{status_label}\t{vision_name}\t{time_str}\t{content}\t{created_str}"
        ]

    def _create_notes_section(
        self, task_notes_map: Dict, date_range_notes: List
    ) -> List[str]:
        """
        Create the related notes section with deduplication using NotesExportService formatting.

        Args:
            task_notes_map: Dictionary mapping task IDs to their related notes
            date_range_notes: List of notes created in the planning date range

        Returns:
            List of formatted lines for the notes section
        """
        lines = ["", self.t("export.planning.notes.title"), ""]

        # Deduplicate notes: collect all unique note IDs and create Note objects
        all_note_ids = set()
        unique_notes = []

        # Helper class to create Note-like objects from dict data
        class MockNote:
            def __init__(self, note_data):
                self.id = note_data["id"]
                self.content = note_data["content"]
                self.created_at = (
                    datetime.fromisoformat(
                        note_data["created_at"].replace("Z", "+00:00")
                    )
                    if note_data.get("created_at")
                    else None
                )
                self.updated_at = (
                    datetime.fromisoformat(
                        note_data["updated_at"].replace("Z", "+00:00")
                    )
                    if note_data.get("updated_at")
                    else None
                )
                self.persons = []  # We don't have persons data here
                self.tags = []  # We don't have tags data here
                self.task = note_data.get("task")

        # Add task-related notes
        if task_notes_map:
            for task_id, notes in task_notes_map.items():
                for note_dict in notes:
                    if note_dict["id"] not in all_note_ids:
                        all_note_ids.add(note_dict["id"])
                        unique_notes.append(MockNote(note_dict))

        # Add date range notes
        for note_dict in date_range_notes:
            if note_dict["id"] not in all_note_ids:
                all_note_ids.add(note_dict["id"])
                unique_notes.append(MockNote(note_dict))

        # Sort notes by creation date (newest first)
        unique_notes.sort(key=lambda x: x.created_at or datetime.min, reverse=True)

        if not unique_notes:
            lines.extend([self.t("export.planning.notes.none"), ""])
            return lines

        # Use NotesExportService to format notes
        lines.append(self.t("export.planning.notes.summary", count=len(unique_notes)))
        lines.append("")

        notes_export_service = NotesExportService(locale=self.locale)

        for i, note in enumerate(unique_notes):
            # Format note using NotesExportService's formatting
            note_lines = notes_export_service._format_note_content(note)

            # Add note number at the beginning
            if note_lines:
                note_lines[0] = f"{i+1}. " + note_lines[0].lstrip()

            lines.extend(note_lines)
            lines.append("")  # Add extra blank line between notes

        return lines


async def export_planning_data(
    db: AsyncSession, params: PlanningExportParams, user_id: str
) -> str:
    """
    Export planning data for a user.

    Args:
        db: Database session
        params: Export parameters
        user_id: User ID

    Returns:
        Formatted export text
    """
    # Convert user_id to UUID
    user_uuid = UUID(user_id)

    export_locale = await user_preferences_service.resolve_language_preference(
        db, user_id=user_uuid
    )
    service = PlanningExportService(locale=export_locale)

    # Get user timezone and convert date to user's timezone
    user_timezone = await user_preferences_service.get_user_timezone(
        db, user_id=user_uuid
    )

    user_zone = ZoneInfo(user_timezone)

    # Convert selected_date to user's timezone date
    if params.selected_date.tzinfo is None:
        # Treat naive datetime as already in user's local time
        selected_date_user_tz = params.selected_date.replace(tzinfo=user_zone)
    else:
        # If timezone-aware datetime, convert to user timezone
        selected_date_user_tz = params.selected_date.astimezone(user_zone)

    selected_date_str = selected_date_user_tz.strftime("%Y-%m-%d")

    # Reuse existing task service to query tasks
    tasks = await list_tasks(
        db,
        user_id=user_uuid,
        planning_cycle_type=params.view_type,
        planning_cycle_start_date=selected_date_str,
        limit=100,
    )

    # Query time records for these tasks
    task_ids = [task.id for task in tasks]
    time_records: List[ActualEvent] = []
    if task_ids:
        stmt = select(ActualEvent).where(
            ActualEvent.task_id.in_(task_ids),
            ActualEvent.deleted_at.is_(None),
            ActualEvent.start_time.isnot(None),
            ActualEvent.end_time.isnot(None),
        )
        time_records = (await db.execute(stmt)).scalars().all()

    # Group time records by task_id (use string keys to match task dict)
    task_time_records = {}
    for record in time_records:
        task_id_str = str(record.task_id)  # Convert UUID to string
        if task_id_str not in task_time_records:
            task_time_records[task_id_str] = []

        task_time_records[task_id_str].append(
            {
                "id": str(record.id),
                "start_time": record.start_time.isoformat(),
                "end_time": record.end_time.isoformat(),
                "title": record.title,
                "notes": record.notes,
            }
        )

    # Create vision map
    vision_ids = {task.vision_id for task in tasks if task.vision_id}
    vision_map = {}
    if vision_ids:
        stmt = select(Vision).where(
            Vision.id.in_(vision_ids),
            Vision.deleted_at.is_(None),
        )
        visions = (await db.execute(stmt)).scalars().all()

        # Create vision map with string keys to match task.vision_id strings
        vision_map = {
            str(vision.id): {
                "id": str(vision.id),
                "name": vision.name,
                "description": vision.description,
            }
            for vision in visions
        }

    # Query related notes for tasks and notes created in the planning date range
    task_notes_map: Dict[str, List[Dict]] = {}
    task_note_objects: Dict[str, List] = {}
    date_range_notes: List[Dict] = []

    include_notes_flag = bool(getattr(params, "include_notes", True))

    preference_task_notes = await user_preferences_service.get_preference_value(
        db,
        user_id=user_uuid,
        key="notes.export_planning.include_task_notes",
        default=True,
    )
    preference_cycle_notes = await user_preferences_service.get_preference_value(
        db,
        user_id=user_uuid,
        key="notes.export_planning.include_cycle_notes",
        default=False,
    )

    include_task_notes = _coerce_bool(
        getattr(params, "include_task_notes", None),
        _coerce_bool(preference_task_notes, True),
    )
    include_cycle_notes = _coerce_bool(
        getattr(params, "include_cycle_notes", None),
        _coerce_bool(preference_cycle_notes, False),
    )

    if not include_notes_flag:
        include_task_notes = False
        include_cycle_notes = False

    include_any_notes = include_notes_flag and (
        include_task_notes or include_cycle_notes
    )

    if include_any_notes:
        # Get user's calendar system preference
        calendar_system = await _get_user_calendar_system(db, user_uuid)

        # Use the same calendar system logic as tasks for date range calculation
        # Convert selected_date to date object in user timezone
        selected_date_local = selected_date_user_tz.date()
        notes_start_date, notes_end_date = _get_cycle_date_range(
            params.view_type, selected_date_local, calendar_system
        )

        all_notes_for_associations: List = []
        task_lookup = {str(task.id): task for task in tasks}

        if include_task_notes and tasks:
            for task in tasks:
                task_related_notes = await note_service.list_notes(
                    db, user_id=user_uuid, task_id=task.id, limit=None
                )

                if task_related_notes:
                    task_note_objects[str(task.id)] = task_related_notes
                    all_notes_for_associations.extend(task_related_notes)

        cycle_note_objects: List = []
        if include_cycle_notes:
            all_user_notes = await note_service.list_notes(
                db, user_id=user_uuid, limit=None
            )

            for note in all_user_notes:
                if note.created_at:
                    note_time_user_tz = note.created_at.astimezone(
                        ZoneInfo(user_timezone)
                    )
                    note_date_local = note_time_user_tz.date()

                    if notes_start_date <= note_date_local <= notes_end_date:
                        cycle_note_objects.append(note)

            if cycle_note_objects:
                all_notes_for_associations.extend(cycle_note_objects)

        associations_map = {}
        if all_notes_for_associations:
            associations_map = await note_service.get_notes_with_associations(
                db, user_id=user_uuid, notes=all_notes_for_associations
            )

        def _serialize_task_info(task_obj):
            if not task_obj:
                return None

            serialized = _serialize_task_for_export(task_obj)

            if not serialized:
                return None

            return {
                "id": serialized.get("id"),
                "content": serialized.get("content") or serialized.get("title"),
                "status": serialized.get("status"),
            }

        def _serialize_note(note_obj, fallback_task=None):
            assoc = associations_map.get(note_obj.id, {}) if associations_map else {}
            assoc_task = assoc.get("task") if assoc else None
            task_info = assoc_task or fallback_task
            core_note = core_serialize_note(note_obj)
            serialized = {
                "id": core_note.get("id"),
                "content": core_note.get("content"),
                "created_at": core_note.get("created_at"),
                "updated_at": core_note.get("updated_at"),
            }
            if task_info:
                serialized_task = _serialize_task_info(task_info)
                if serialized_task:
                    serialized["task"] = serialized_task
            return serialized

        if include_cycle_notes and cycle_note_objects:
            date_range_notes = [_serialize_note(note) for note in cycle_note_objects]

        if include_task_notes and task_note_objects:
            for task_id, notes in task_note_objects.items():
                fallback_task = task_lookup.get(task_id)
                task_notes_map[task_id] = [
                    _serialize_note(note, fallback_task) for note in notes
                ]

    # Build planning groups structure (group by planning_cycle_start_date)
    planning_groups = []
    if tasks:
        # All tasks have the same planning_cycle_start_date for a given view
        # Use the user timezone date for grouping
        start_date = selected_date_user_tz.date()

        # Generate group label based on view type
        start_datetime = datetime.combine(
            start_date, datetime.min.time(), tzinfo=user_zone
        )
        day_label = service.format_date(start_datetime)

        if params.view_type == "day":
            label = day_label
        elif params.view_type == "week":
            label = service.t("export.planning.group.label.week", date=day_label)
        elif params.view_type == "month":
            month_label = (
                start_datetime.strftime("%Y年%m月")
                if service.locale == "zh-CN"
                else start_datetime.strftime("%Y-%m")
            )
            label = service.t("export.planning.group.label.month", date=month_label)
        elif params.view_type == "year":
            label = service.t("export.planning.group.label.year", year=start_date.year)
        else:
            label = start_date.isoformat()

        # Build task hierarchy (include all tasks, not just root tasks)
        # This ensures we export all tasks found for the selected date

        def build_task_dict(task) -> Dict:
            serialized = _serialize_task_for_export(task)

            if not serialized:
                return {
                    "id": (
                        str(getattr(task, "id", None))
                        if getattr(task, "id", None)
                        else None
                    ),
                    "content": getattr(task, "content", None),
                    "subtasks": [],
                }

            return {
                "id": serialized.get("id"),
                "content": serialized.get("content") or serialized.get("title"),
                "notes": serialized.get("notes"),
                "status": serialized.get("status"),
                "priority": serialized.get("priority"),
                "display_order": serialized.get("display_order"),
                "estimated_effort": serialized.get("estimated_effort"),
                "actual_effort_self": serialized.get("actual_effort_self"),
                "actual_effort_total": serialized.get("actual_effort_total"),
                "vision_id": serialized.get("vision_id"),
                "parent_task_id": serialized.get("parent_task_id"),
                "planning_cycle_type": serialized.get("planning_cycle_type"),
                "planning_cycle_days": serialized.get("planning_cycle_days"),
                "planning_cycle_start_date": serialized.get(
                    "planning_cycle_start_date"
                ),
                "created_at": serialized.get("created_at"),
                "updated_at": serialized.get("updated_at"),
                "subtasks": [],
            }

        # Include ALL tasks, not just root tasks
        group_tasks = [build_task_dict(task) for task in tasks]

        planning_groups.append(
            {
                "id": f"group_{start_date.isoformat()}",
                "label": label,
                "date": start_date.isoformat(),
                "tasks": group_tasks,
                "children": [],  # No nested children for now
            }
        )

    # Prepare data for export
    data = {
        "planning_groups": planning_groups,
        "task_time_records": task_time_records,
        "vision_map": vision_map,
        "task_notes_map": task_notes_map,
        "date_range_notes": date_range_notes,
    }

    # Generate export text
    return service.generate_export_text(params, data)


async def estimate_planning_export(
    db: AsyncSession, params: PlanningExportParams, user_id: str
) -> tuple[int, int]:
    user_uuid = UUID(user_id)

    preference_task_notes = await user_preferences_service.get_preference_value(
        db,
        user_id=user_uuid,
        key="notes.export_planning.include_task_notes",
        default=True,
    )
    preference_cycle_notes = await user_preferences_service.get_preference_value(
        db,
        user_id=user_uuid,
        key="notes.export_planning.include_cycle_notes",
        default=False,
    )

    include_notes_flag = _coerce_bool(getattr(params, "include_notes", True), True)
    include_task_notes = _coerce_bool(
        getattr(params, "include_task_notes", None),
        _coerce_bool(preference_task_notes, True),
    )
    include_cycle_notes = _coerce_bool(
        getattr(params, "include_cycle_notes", None),
        _coerce_bool(preference_cycle_notes, False),
    )

    if not include_notes_flag:
        include_task_notes = False
        include_cycle_notes = False

    user_timezone = await user_preferences_service.get_user_timezone(
        db, user_id=user_uuid
    )
    user_zone = ZoneInfo(user_timezone)
    selected_date_user_tz = (
        params.selected_date.replace(tzinfo=user_zone)
        if params.selected_date.tzinfo is None
        else params.selected_date.astimezone(user_zone)
    )
    selected_date_str = selected_date_user_tz.strftime("%Y-%m-%d")
    tasks = await list_tasks(
        db,
        user_id=user_uuid,
        planning_cycle_type=params.view_type,
        planning_cycle_start_date=selected_date_str,
        limit=200,
    )
    count = len(tasks)
    estimated_size = count * 500

    if include_task_notes:
        estimated_size += count * 800
    if include_cycle_notes:
        estimated_size += max(count, 10) * 400
    return count, estimated_size
