"""
Notes export service
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.note import Note
from app.handlers import user_preferences as user_preferences_service
from app.handlers.exports.export_base import BaseExportService
from app.handlers.notes import (
    advanced_search_notes,
    get_notes_with_associations,
    list_notes,
)
from app.schemas.export import ExportParams, ExportStatistics, NotesExportParams
from app.schemas.note import NoteAdvancedSearchRequest
from app.serialization.entities import build_task_summary


class NotesExportService(BaseExportService):
    """Export service for notes data."""

    def generate_export_text(self, params: ExportParams, data: Any) -> str:
        """
        Generate export text for notes data.

        Args:
            params: NotesExportParams
            data: List of Note objects

        Returns:
            Formatted export text
        """
        if not isinstance(params, NotesExportParams):
            raise ValueError("Expected NotesExportParams")

        notes = data
        if not notes:
            return self._create_empty_export(params)

        lines = []

        # Header
        header_title = self.t("export.notes.header")
        lines.extend(self.create_export_header(header_title))

        # Query conditions
        lines.extend(self._create_query_conditions_section(params))

        # Statistics
        stats = ExportStatistics(total_records=len(notes))
        lines.extend(self._create_statistics_section(stats))

        # Data table
        lines.extend(self._create_data_table(notes))

        return "\n".join(lines)

    def _create_empty_export(self, params: NotesExportParams) -> str:
        """Create export for empty data."""
        lines = [
            self.t("export.notes.empty.title"),
            "",
            self.t("export.notes.search_conditions"),
            self.t("export.notes.empty.no_match"),
            "",
            self.t("export.common.statistics"),
            self.t("export.common.stats.total_records", count=0),
            "",
            self.t("export.common.data_list"),
            self.t("export.common.no_data"),
        ]
        return "\n".join(lines)

    def _create_query_conditions_section(self, params: NotesExportParams) -> List[str]:
        """Create the query conditions section."""
        lines = [self.t("export.notes.search_conditions")]

        if params.filter_summary and len(params.filter_summary) > 0:
            lines.extend(params.filter_summary)
        else:
            # Tag filters
            if params.selected_filter_tags:
                tag_names = [
                    tag.get("name", "")
                    for tag in params.selected_filter_tags
                    if tag.get("name")
                ]
                if tag_names:
                    tag_str = ", ".join(f"#{name}" for name in tag_names)
                    lines.append(self.t("export.notes.filter.tags", tags=tag_str))

            # Person filters
            if params.selected_filter_persons:
                person_names = [
                    person.get("display_name", "")
                    for person in params.selected_filter_persons
                    if person.get("display_name")
                ]
                if person_names:
                    person_str = ", ".join(f"@{name}" for name in person_names)
                    lines.append(
                        self.t("export.notes.filter.persons", persons=person_str)
                    )

            # Keyword search
            if params.search_keyword.strip():
                lines.append(
                    self.t(
                        "export.notes.filter.keyword",
                        keyword=params.search_keyword.strip(),
                    )
                )

            # No filters
            if (
                not params.selected_filter_tags
                and not params.selected_filter_persons
                and not params.search_keyword.strip()
            ):
                lines.append(self.t("export.notes.filter.none"))

        lines.append("")
        return lines

    def _create_statistics_section(self, stats: ExportStatistics) -> List[str]:
        """Create the statistics section."""
        lines = [
            self.t("export.common.statistics"),
            self.t("export.common.stats.total_records", count=stats.total_records),
            "",
        ]
        return lines

    def _create_data_table(self, notes: List[Note]) -> List[str]:
        """Create the data section with natural note formatting."""
        lines = [self.t("export.common.data_list")]

        for i, note in enumerate(notes):
            # Add note content
            note_content = self._format_note_content(note)
            lines.extend(note_content)
        return lines

    def _format_note_content(self, note: Note) -> List[str]:
        """Format a single note with natural formatting."""
        lines = []

        # Created date
        if note.created_at:
            date_str = self.format_datetime(note.created_at)
            lines.append(self.t("export.notes.note.created_at", datetime=date_str))

        # Content - preserve original line breaks and formatting
        if note.content and note.content.strip():
            # Add a blank line between date and content
            if lines:
                lines.append("")

            # Add content with original formatting preserved
            content_lines = note.content.split("\n")
            lines.extend(content_lines)

        # Related persons
        if hasattr(note, "persons") and note.persons:
            person_names = [
                p.display_name or p.primary_nickname for p in note.persons if p
            ]
            if person_names:
                if lines:
                    lines.append("")  # Add blank line before persons
                persons_str = ", ".join(f"@{name}" for name in person_names)
                lines.append(
                    self.t("export.notes.note.related_persons", persons=persons_str)
                )

        # Tags
        if hasattr(note, "tags") and note.tags:
            tag_names = [t.name for t in note.tags if t and t.name]
            if tag_names:
                if lines:
                    lines.append("")  # Add blank line before tags
                tags_str = " ".join(f"#{name}" for name in tag_names)
                lines.append(self.t("export.notes.note.tags", tags=tags_str))

        # Related task
        if hasattr(note, "task") and note.task:
            task_obj = note.task
            task_summary: Optional[Dict[str, Any]] = None

            if isinstance(task_obj, dict):
                task_summary = task_obj
            elif hasattr(task_obj, "model_dump"):
                try:
                    task_summary = task_obj.model_dump(mode="json", exclude_none=True)
                except Exception:
                    task_summary = task_obj.model_dump()
            else:
                summary_model = build_task_summary(
                    task_obj, include_parent_summary=False
                )
                if summary_model is not None:
                    task_summary = summary_model.model_dump(
                        mode="json",
                        exclude_none=True,
                    )

            task_title = ""
            task_status = None
            if task_summary:
                task_title = (
                    task_summary.get("content") or task_summary.get("title") or ""
                )
                task_status = task_summary.get("status")

            if task_title:
                if lines:
                    lines.append("")
                if task_status:
                    status_label = self.t(
                        f"export.planning.status.{task_status}",
                        default=task_status,
                    )
                    lines.append(
                        self.t(
                            "export.notes.note.related_task_with_status",
                            task=task_title,
                            status=status_label,
                        )
                    )
                else:
                    lines.append(
                        self.t("export.notes.note.related_task", task=task_title)
                    )

        return lines


async def export_notes_data(
    db: AsyncSession, params: NotesExportParams, user_id: str
) -> str:
    """
    Export notes data for a user.

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
    service = NotesExportService(locale=export_locale)

    notes: List[Note] = []

    tag_ids = [UUID(tag["id"]) for tag in params.selected_filter_tags if tag.get("id")]
    person_ids = [
        UUID(person["id"])
        for person in params.selected_filter_persons
        if person.get("id")
    ]
    keyword = params.search_keyword.strip() if params.search_keyword else None

    use_advanced_search = bool(tag_ids or person_ids)

    if use_advanced_search:
        search_request = NoteAdvancedSearchRequest(
            tag_ids=tag_ids or None,
            person_ids=person_ids or None,
            keyword=keyword,
        )

        advanced_results = await advanced_search_notes(
            db, user_id=user_uuid, request=search_request
        )

        for note, persons, task in advanced_results:
            setattr(note, "persons", persons)
            if task:
                setattr(note, "task", task)
            notes.append(note)

    elif keyword:
        notes = await list_notes(db, user_id=user_uuid, keyword=keyword, limit=10000)
    else:
        notes = await list_notes(db, user_id=user_uuid, limit=10000)

    # Load associations for regular note exports
    if not use_advanced_search and notes:
        associations = await get_notes_with_associations(
            db, user_id=user_uuid, notes=notes
        )
        for note in notes:
            assoc = associations.get(note.id, {})
            persons = assoc.get("persons")
            task = assoc.get("task")
            if persons:
                setattr(note, "persons", persons)
            if task:
                setattr(note, "task", task)

    # Generate export text
    return service.generate_export_text(params, notes)


async def estimate_notes_export(
    db: AsyncSession, params: NotesExportParams, user_id: str
) -> tuple[int, int]:
    """Estimate notes export size (count, size in bytes)."""
    user_uuid = UUID(user_id)
    tag_ids = [UUID(tag["id"]) for tag in params.selected_filter_tags if tag.get("id")]
    person_ids = [
        UUID(person["id"])
        for person in params.selected_filter_persons
        if person.get("id")
    ]
    keyword = params.search_keyword.strip() if params.search_keyword else None

    use_advanced_search = bool(tag_ids or person_ids)

    if use_advanced_search:
        search_request = NoteAdvancedSearchRequest(
            tag_ids=tag_ids or None,
            person_ids=person_ids or None,
            keyword=keyword,
        )
        results = await advanced_search_notes(
            db, user_id=user_uuid, request=search_request
        )
        count = len(results)
    elif keyword:
        notes = await list_notes(db, user_id=user_uuid, keyword=keyword, limit=10000)
        count = len(notes)
    else:
        notes = await list_notes(db, user_id=user_uuid, limit=10000)
        count = len(notes)

    # average 300 bytes per note text
    estimated_size = count * 300
    return count, estimated_size
