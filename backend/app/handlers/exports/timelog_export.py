"""
Timelog export service
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.actual_event import ActualEvent
from app.db.models.dimension import Dimension
from app.handlers import user_preferences as user_preferences_service
from app.handlers.actual_events import search_actual_events
from app.handlers.exports.export_base import BaseExportService, ExportFormatter
from app.schemas.cardbox import (
    ActualEventSnapshotDimensionStat,
    ActualEventSnapshotQuery,
    ActualEventSnapshotSummary,
    SnapshotDateRange,
)
from app.schemas.export import ExportParams, ExportStatistics, TimeLogExportParams
from app.utils.timezone_util import resolve_timezone


class ActualEventExportService(BaseExportService):
    """Export service for actual event (time log) data."""

    def __init__(
        self,
        locale: str = "en",
        db: Optional[Any] = None,
        user_id: Optional[UUID] = None,
        user_timezone: Optional[str] = None,
    ):
        super().__init__(locale)
        self.db = db
        self.user_id = user_id
        timezone_value = (user_timezone or "UTC").strip() or "UTC"
        self.user_timezone = timezone_value
        self._timezone_info = resolve_timezone(timezone_value, default="UTC")
        self._dimension_cache: Dict[str, str] = {}
        self._dimension_lookup = None

        if db is not None and user_id is not None:
            try:
                from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
            except ImportError:
                _AsyncSession = None

            if _AsyncSession is None or not isinstance(db, _AsyncSession):

                def _lookup(dimension_id: UUID) -> Optional[str]:
                    from app.handlers.dimensions import get_dimension

                    dimension = get_dimension(
                        db, user_id=user_id, dimension_id=dimension_id
                    )
                    return dimension.name if dimension else None

                self._dimension_lookup = _lookup

    def set_dimension_names(self, mapping: Dict[str, str]) -> None:
        """Inject preloaded dimension name mapping for async handlers."""
        self._dimension_cache.update(mapping)

    @staticmethod
    def _format_time_value(time_value: Union[datetime, str, None]) -> str:
        """Format time value (HH:MM format)."""
        if not time_value:
            return "--"
        try:
            if isinstance(time_value, str):
                dt = datetime.fromisoformat(time_value.replace("Z", "+00:00"))
            else:
                dt = time_value
            return dt.strftime("%H:%M")
        except Exception:
            return str(time_value)[:5]

    def _get_dimension_name(self, dimension_id: Union[str, UUID]) -> str:
        """Get dimension name by ID, with caching."""
        unknown_label = self.t("export.timelog.dimension.unknown")

        if not dimension_id:
            return unknown_label

        # Convert to string for cache key
        dimension_id_str = str(dimension_id)

        if dimension_id_str in self._dimension_cache:
            return self._dimension_cache[dimension_id_str]

        if self._dimension_lookup:
            try:
                dimension_uuid = UUID(dimension_id_str)
            except Exception:
                return dimension_id_str or unknown_label

            name = self._dimension_lookup(dimension_uuid)
            if name:
                self._dimension_cache[dimension_id_str] = name
                return name

        return dimension_id_str or unknown_label

    def _convert_to_user_timezone(
        self, value: Union[datetime, str, None]
    ) -> Optional[datetime]:
        """Normalize datetime/string values into the user's timezone."""
        if not value:
            return None

        parsed: Optional[datetime]
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        try:
            return parsed.astimezone(self._timezone_info)
        except Exception:
            return parsed

    def generate_export_text(self, params: ExportParams, data: Any) -> str:
        """
        Generate export text for timelog data.

        Args:
            params: TimeLogExportParams
            data: List of ActualEvent objects

        Returns:
            Formatted export text
        """
        if not isinstance(params, TimeLogExportParams):
            raise ValueError("Expected TimeLogExportParams")

        events = data
        if not events:
            return self._create_empty_export(params)

        lines = []

        # Header
        header_title = self.t("export.timelog.header")
        lines.extend(self.create_export_header(header_title))

        # Query conditions
        lines.extend(self._create_query_conditions_section(params))

        # Statistics
        stats = self._calculate_statistics(events, params.dimension_id)
        lines.extend(self._create_statistics_section(stats))

        # Per-dimension statistics
        if stats.dimension_stats:
            lines.extend(
                self._create_dimension_stats_section(
                    stats.dimension_stats, stats.total_duration_minutes
                )
            )

        # Data table
        lines.extend(self._create_data_table(events, params.dimension_id))

        return "\n".join(lines)

    def _create_empty_export(self, params: TimeLogExportParams) -> str:
        """Create export for empty data."""
        lines = [
            self.t("export.timelog.empty.title"),
            "",
            self.t("export.common.query_conditions"),
            f"{self.t('export.common.start_date')}{self.format_date(params.start_date)}",
            f"{self.t('export.common.end_date')}{self.format_date(params.end_date)}",
            "",
            self.t("export.common.statistics"),
            self.t("export.common.stats.total_records", count=0),
            "",
            self.t("export.common.data_list"),
            self.t("export.common.no_data"),
        ]
        return "\n".join(lines)

    def _create_query_conditions_section(
        self, params: TimeLogExportParams
    ) -> List[str]:
        """Create the query conditions section."""
        lines = [
            self.t("export.common.query_conditions"),
            f"{self.t('export.common.start_date')}{self.format_date(params.start_date)}",
            f"{self.t('export.common.end_date')}{self.format_date(params.end_date)}",
        ]

        if params.dimension_id:
            # Get dimension name from database
            dimension_name = self._get_dimension_name(params.dimension_id)
            lines.append(f"{self.t('export.common.dimension_filter')}{dimension_name}")

        if params.description_keyword:
            lines.append(
                f"{self.t('export.common.keyword')}{params.description_keyword}"
            )

        lines.append("")
        return lines

    def _calculate_statistics(
        self, events: List[ActualEvent], dimension_id: Optional[str]
    ) -> ExportStatistics:
        """Calculate statistics for the events."""
        total_duration_ms = 0
        dimension_stats = {}

        for event in events:
            if event.start_time and event.end_time:
                # Handle both datetime objects and ISO string formats
                if isinstance(event.start_time, str):
                    start = datetime.fromisoformat(
                        event.start_time.replace("Z", "+00:00")
                    )
                else:
                    start = event.start_time

                if isinstance(event.end_time, str):
                    end = datetime.fromisoformat(event.end_time.replace("Z", "+00:00"))
                else:
                    end = event.end_time

                duration_ms = (end - start).total_seconds() * 1000
                total_duration_ms += duration_ms

                # Per-dimension aggregation
                dim_key = str(event.dimension_id) if event.dimension_id else "unknown"
                if dim_key not in dimension_stats:
                    dimension_stats[dim_key] = {"count": 0, "duration_ms": 0}

                dimension_stats[dim_key]["count"] += 1
                dimension_stats[dim_key]["duration_ms"] += duration_ms

        total_minutes = int(total_duration_ms / (1000 * 60))

        return ExportStatistics(
            total_records=len(events),
            total_duration_minutes=total_minutes,
            dimension_stats=dimension_stats,
        )

    def build_snapshot_summary(
        self,
        *,
        events: List[ActualEvent],
        stats: ExportStatistics,
        start_dt: datetime,
        end_dt: datetime,
    ) -> ActualEventSnapshotSummary:
        """Build metadata summary payload for Cardbox snapshots."""

        dimension_summary: List[ActualEventSnapshotDimensionStat] = []
        raw_dimension_stats = stats.dimension_stats or {}
        for dim_key, raw in raw_dimension_stats.items():
            count_value = raw.get("count", 0) if isinstance(raw, dict) else 0
            duration_raw = raw.get("duration_ms") if isinstance(raw, dict) else None
            duration_minutes = None
            if isinstance(duration_raw, (int, float)):
                duration_minutes = int(duration_raw / (1000 * 60))

            dimension_summary.append(
                ActualEventSnapshotDimensionStat(
                    dimension_id=str(dim_key) if dim_key is not None else None,
                    count=(
                        int(count_value) if isinstance(count_value, (int, float)) else 0
                    ),
                    duration_minutes=duration_minutes,
                )
            )

        entry_ids = [
            str(getattr(event, "id"))
            for event in events
            if getattr(event, "id", None) is not None
        ]

        return ActualEventSnapshotSummary(
            total_records=stats.total_records,
            total_duration_minutes=stats.total_duration_minutes,
            date_range=SnapshotDateRange(start=start_dt, end=end_dt),
            dimension_stats=dimension_summary,
            entry_ids=entry_ids,
        )

    @staticmethod
    def build_snapshot_query(filters: Dict[str, Any]) -> ActualEventSnapshotQuery:
        """Normalise filter values into a structured query payload."""

        limit_value = filters.get("limit")
        limit: Optional[int]
        if isinstance(limit_value, int):
            limit = limit_value
        elif isinstance(limit_value, str):
            try:
                limit = int(limit_value)
            except ValueError:
                limit = None
        else:
            limit = None

        return ActualEventSnapshotQuery(
            dimension_name=filters.get("dimension_name"),
            keyword=filters.get("keyword"),
            description_keyword=filters.get("description_keyword"),
            tracking_method=filters.get("tracking_method"),
            limit=limit,
        )

    def _create_statistics_section(self, stats: ExportStatistics) -> List[str]:
        """Create the statistics section."""
        lines = [
            self.t("export.common.statistics"),
            self.t("export.common.stats.total_records", count=stats.total_records),
        ]

        if stats.total_duration_minutes:
            duration = self.format_duration(stats.total_duration_minutes)
            lines.append(
                self.t("export.common.stats.total_duration", duration=duration)
            )

        lines.append("")
        return lines

    def _create_dimension_stats_section(
        self, dimension_stats: Dict, total_duration_minutes: float
    ) -> List[str]:
        """Create per-dimension statistics section."""
        lines = [
            self.t("export.common.dimension_stats.title"),
            self.t("export.common.dimension_stats.header"),
        ]

        # Sort by duration descending (convert from ms to minutes for sorting)
        sorted_dims = sorted(
            dimension_stats.items(),
            key=lambda x: x[1]["duration_ms"] / (1000 * 60),
            reverse=True,
        )

        # Calculate percentages for each dimension using minutes precision
        percentages = []
        for dim_key, stats in sorted_dims:
            count = stats["count"]
            duration_ms = stats["duration_ms"]
            duration_minutes = int(duration_ms / (1000 * 60))
            duration_text = self.format_duration(duration_minutes)

            # Calculate percentage using minutes for better precision
            percent = (
                round((duration_minutes / total_duration_minutes) * 100, 1)
                if total_duration_minutes > 0
                else 0
            )
            percentages.append(percent)

            # Get dimension name instead of ID
            dimension_name = self._get_dimension_name(dim_key)
            lines.append(f"{dimension_name}\t{count}\t{duration_text}\t{percent}%")

        # Add total percentage for verification (should be close to 100%)
        if percentages:
            total_percentage = round(sum(percentages), 1)
            total_records = sum(stats["count"] for stats in dimension_stats.values())
            lines.append(
                self.t(
                    "export.common.dimension_stats.total",
                    count=total_records,
                    duration=self.format_duration(int(total_duration_minutes)),
                    percentage=total_percentage,
                )
            )

        lines.append("")
        return lines

    def _create_data_table(
        self, events: List[ActualEvent], dimension_id: Optional[str]
    ) -> List[str]:
        """Create the data table section."""
        lines = [
            self.t("export.common.data_list"),
            self.t("export.timelog.table.header"),
        ]

        for event in events:
            row_data = self._format_event_row(event)
            lines.append(ExportFormatter.format_table_row(row_data))

        return lines

    def _build_task_column_value(self, event: ActualEvent) -> str:
        """Compose the related task column value with vision and status details."""
        task_summary = getattr(event, "export_task_summary", None)
        task_obj = getattr(event, "task", None)

        if not task_summary and not task_obj:
            return ""

        base_content = ""
        vision_name: Optional[str] = None
        status_value: Optional[str] = None

        if task_summary:
            base_content = ExportFormatter.clean_text(
                str(task_summary.get("content") or "")
            )
            vision_summary = task_summary.get("vision_summary") or {}
            raw_vision_name = vision_summary.get("name") or ""
            if raw_vision_name:
                vision_name = ExportFormatter.clean_text(str(raw_vision_name))
            status_value = task_summary.get("status")

        if task_obj:
            if not base_content:
                base_content = ExportFormatter.clean_text(
                    getattr(task_obj, "content", "") or ""
                )
            if vision_name is None:
                vision_obj = getattr(task_obj, "vision", None)
                raw_vision_name = getattr(vision_obj, "name", "") if vision_obj else ""
                if raw_vision_name:
                    vision_name = ExportFormatter.clean_text(str(raw_vision_name))
            if status_value is None:
                status_value = getattr(task_obj, "status", None)

        if not vision_name:
            vision_name = ExportFormatter.clean_text(
                self.t("export.timelog.task.vision_unknown")
            )

        status_text = self._get_localized_task_status(status_value)

        vision_label = self.t("export.timelog.task.vision_label")
        status_label = self.t("export.timelog.task.status_label")
        separator = "；" if self.locale == "zh" else "; "
        details = [
            f"{status_label}{status_text}",
            f"{vision_label}{vision_name}",
        ]

        parts: List[str] = []
        if base_content:
            parts.append(base_content)
        parts.append(f"({separator.join(details)})")
        return ExportFormatter.clean_text(" ".join(parts))

    def _get_localized_task_status(self, status: Optional[str]) -> str:
        """Return a localized task status label."""
        if not status:
            return ExportFormatter.clean_text(
                self.t("export.timelog.task.status_unknown")
            )

        normalized = str(status).lower()
        translated = self.t(
            f"export.planning.status.{normalized}",
            default=str(status),
        )
        return ExportFormatter.clean_text(translated)

    def _format_event_row(self, event: ActualEvent) -> List[str]:
        """Format a single event as a table row."""
        date_str = ""
        start_time_str = ""
        end_time_str = "--"
        duration_str = ""

        event_start = getattr(event, "start_time", None)
        start_dt = self._convert_to_user_timezone(event_start)
        if start_dt:
            date_str = self.format_date(start_dt)
            start_time_str = start_dt.strftime("%H:%M")
        elif event_start:
            start_time_str = str(event_start)[:5]

        event_end = getattr(event, "end_time", None)
        end_dt = self._convert_to_user_timezone(event_end)
        if end_dt:
            end_time_str = self._format_time_value(end_dt)
            duration_str = self._calculate_duration_str(start_dt or event_start, end_dt)
        elif event_end:
            end_time_str = self._format_time_value(event_end)
            duration_str = self._calculate_duration_str(event_start, event_end)

        # Get dimension name from database
        dimension_name = (
            self._get_dimension_name(str(event.dimension_id))
            if event.dimension_id
            else "unknown"
        )

        task_content = self._build_task_column_value(event)

        # Get related persons
        persons_str = ""
        if hasattr(event, "export_person_summaries"):
            person_summaries = getattr(event, "export_person_summaries") or []
            person_names = []
            for summary in person_summaries:
                if summary:
                    if isinstance(summary, dict):
                        name = (
                            summary.get("display_name")
                            or summary.get("primary_nickname")
                            or summary.get("name")
                        )
                    else:
                        name = (
                            getattr(summary, "display_name", None)
                            or getattr(summary, "primary_nickname", None)
                            or getattr(summary, "name", None)
                        )
                    if name:
                        person_names.append(name)
            persons_str = ", ".join(person_names)
        elif hasattr(event, "persons") and event.persons:
            person_names = [
                p.display_name or p.primary_nickname for p in event.persons if p
            ]
            persons_str = ", ".join(person_names)

        title = ExportFormatter.clean_text(event.title or "")

        return [
            date_str,
            start_time_str,
            end_time_str,
            duration_str,
            dimension_name,
            title,
            task_content,
            persons_str,
        ]

    def _calculate_duration_str(self, start_time, end_time) -> str:
        """Calculate duration string from start and end times."""
        try:
            # Handle both datetime objects and ISO string formats
            if isinstance(start_time, str):
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            else:
                start_dt = start_time

            if isinstance(end_time, str):
                end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            else:
                end_dt = end_time

            duration_minutes = int((end_dt - start_dt).total_seconds() / 60)
            return self.format_duration(duration_minutes)
        except Exception:
            return ""


def _sanitize_keyword(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    value = raw.strip()
    return value or None


async def _load_dimension_name_map(
    db: AsyncSession,
    *,
    user_id: UUID,
    dimension_ids: List[UUID],
) -> Dict[str, str]:
    if not dimension_ids:
        return {}
    stmt = (
        select(Dimension.id, Dimension.name)
        .where(
            Dimension.user_id == user_id,
            Dimension.id.in_(dimension_ids),
            Dimension.is_active.is_(True),
        )
        .order_by(Dimension.name.asc())
    )
    rows = (await db.execute(stmt)).all()
    return {str(row[0]): row[1] or str(row[0]) for row in rows}


async def _resolve_dimension_name_by_id(
    db: AsyncSession, *, user_id: UUID, dimension_id: UUID
) -> Optional[str]:
    stmt = (
        select(Dimension.name)
        .where(
            Dimension.user_id == user_id,
            Dimension.id == dimension_id,
        )
        .limit(1)
    )
    return (await db.scalar(stmt)) or None


async def _search_events_for_export(
    db: AsyncSession,
    *,
    user_id: UUID,
    start_dt: datetime,
    end_dt: datetime,
    dimension_id: Optional[UUID],
    description_keyword: Optional[str],
    fetch_events: bool = True,
) -> Tuple[List[ActualEvent], Dict[str, Any]]:
    metadata: Dict[str, Any] = {}
    limit_value = settings.actual_events_search_limit
    max_results = limit_value if fetch_events else 0

    dimension_name_filter: Optional[str] = None
    if dimension_id:
        dimension_name_filter = await _resolve_dimension_name_by_id(
            db, user_id=user_id, dimension_id=dimension_id
        )
        if not dimension_name_filter:
            return [], {
                "limit": limit_value,
                "total_count": 0,
                "returned_count": 0,
                "truncated": False,
            }

    events_with_relations = await search_actual_events(
        db,
        user_id=user_id,
        start_date=start_dt,
        end_date=end_dt,
        dimension_name=dimension_name_filter,
        description_keyword=description_keyword,
        include_notes=False,
        max_results=max_results,
        max_range_days=None,
        allow_result_truncation=True,
        result_metadata=metadata,
    )

    events: List[ActualEvent] = []
    if fetch_events:
        for event, person_summaries, task_summary in events_with_relations:
            setattr(event, "export_person_summaries", person_summaries or [])
            if task_summary:
                setattr(event, "export_task_summary", task_summary)
            events.append(event)
    if not metadata:
        metadata = {
            "limit": limit_value,
            "total_count": len(events),
            "returned_count": len(events),
            "truncated": len(events) > limit_value if fetch_events else False,
        }
    else:
        # When fetch_events is False the query runs with max_results=0, so override limit info
        if not fetch_events:
            total_count = metadata.get("total_count", 0)
            metadata.update(
                {
                    "limit": limit_value,
                    "returned_count": min(total_count, limit_value),
                    "truncated": total_count > limit_value,
                }
            )
    return events, metadata


async def export_timelog_data(
    db: AsyncSession,
    params: TimeLogExportParams,
    user_id: str,
) -> Tuple[str, Dict[str, Any]]:
    """
    Export actual event (time log) data for a user.

    Args:
        db: Database session
        params: Export parameters
        user_id: User ID

    Returns:
        Formatted export text
    """
    # Convert user_id to UUID
    user_uuid = UUID(user_id)

    # Create service with user preference locale for dimension lookups
    export_locale = await user_preferences_service.resolve_language_preference(
        db, user_id=user_uuid
    )
    user_timezone = await user_preferences_service.get_user_timezone(
        db, user_id=user_uuid
    )
    service = ActualEventExportService(
        locale=export_locale,
        user_timezone=user_timezone,
    )

    # Convert date range to timezone-aware datetime objects using user preference service
    (
        start_date_tz,
        end_date_tz,
    ) = await user_preferences_service.convert_date_range_to_timezone(
        db,
        user_id=user_uuid,
        start_date=params.start_date,
        end_date=params.end_date,
    )

    keyword = _sanitize_keyword(params.description_keyword)
    events, metadata = await _search_events_for_export(
        db,
        user_id=user_uuid,
        start_dt=start_date_tz,
        end_dt=end_date_tz,
        dimension_id=params.dimension_id,
        description_keyword=keyword,
        fetch_events=True,
    )

    dimension_ids = list(
        {event.dimension_id for event in events if getattr(event, "dimension_id", None)}
    )
    dimension_map = await _load_dimension_name_map(
        db, user_id=user_uuid, dimension_ids=dimension_ids
    )
    service.set_dimension_names(dimension_map)

    # Generate export text and propagate metadata so API callers can inform users
    export_text = service.generate_export_text(params, events)
    return export_text, metadata


async def estimate_timelog_export(
    db: AsyncSession,
    params: TimeLogExportParams,
    user_id: str,
) -> tuple[int, int]:
    """Estimate timelog export size (count, bytes)."""

    user_uuid = UUID(user_id)
    (
        start_date_tz,
        end_date_tz,
    ) = await user_preferences_service.convert_date_range_to_timezone(
        db,
        user_id=user_uuid,
        start_date=params.start_date,
        end_date=params.end_date,
    )

    keyword = _sanitize_keyword(params.description_keyword)
    _, metadata = await _search_events_for_export(
        db,
        user_id=user_uuid,
        start_dt=start_date_tz,
        end_dt=end_date_tz,
        dimension_id=params.dimension_id,
        description_keyword=keyword,
        fetch_events=False,
    )
    count = metadata.get("total_count", 0)
    estimated_size = count * 400  # avg bytes per event
    return count, estimated_size


# Public alias for clarity in other modules.
TimelogExportService = ActualEventExportService
