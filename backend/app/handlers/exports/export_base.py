"""Base export service functionality."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, List

from app.core.i18n import get_translator, normalize_locale
from app.schemas.export import ExportParams
from app.utils.timezone_util import utc_now


class BaseExportService(ABC):
    """
    Base class for export services.

    Provides common functionality for formatting export data,
    handling different locales, and standardizing export results.
    """

    def __init__(self, locale: str = "zh-CN"):
        self.locale = normalize_locale(locale)
        self._translator = get_translator(self.locale)

    def t(self, key: str, default: str | None = None, **kwargs) -> str:
        """Get translated text with optional formatting."""
        return self._translator.gettext(key, default=default, **kwargs)

    def format_date(self, date: datetime) -> str:
        """Format date according to locale."""
        if self.locale == "zh-CN":
            return date.strftime("%Y年%m月%d日")
        return date.strftime("%Y-%m-%d")

    def format_datetime(self, datetime_obj: datetime) -> str:
        """Format datetime according to locale."""
        if self.locale == "zh-CN":
            return datetime_obj.strftime("%Y年%m月%d日 %H:%M:%S")
        return datetime_obj.strftime("%Y-%m-%d %H:%M:%S")

    def format_duration(self, minutes: int) -> str:
        """Format duration according to locale."""
        hours = minutes // 60
        mins = minutes % 60

        hour_label = self.t("export.common.duration.hour")
        minute_label = self.t("export.common.duration.minute")

        if self.locale == "zh-CN":
            if hours > 0:
                return f"{hours}{hour_label}{mins}{minute_label}"
            return f"{mins}{minute_label}"

        if hours > 0 and mins > 0:
            return f"{hours}{hour_label} {mins}{minute_label}"
        if hours > 0:
            return f"{hours}{hour_label}"
        return f"{mins}{minute_label}"

    def create_export_header(self, title: str) -> List[str]:
        """Create standard export header."""
        lines = [f"=== {title} ===", ""]
        return lines

    @abstractmethod
    def generate_export_text(self, params: ExportParams, data: Any) -> str:
        """
        Generate export text for the specific data type.

        Args:
            params: Export parameters
            data: Data to export

        Returns:
            Formatted export text
        """

    def _generate_filename(self, params: ExportParams) -> str:
        """Generate filename for export."""
        timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
        service_name = self.__class__.__name__.replace("ExportService", "").lower()
        return f"{service_name}_export_{timestamp}.txt"


class ExportFormatter:
    """Utility class for common export formatting operations."""

    @staticmethod
    def clean_text(text: str) -> str:
        """Clean text for export by removing problematic characters."""
        return text.replace("\n", " ").replace("\t", " ").strip()

    @staticmethod
    def format_table_row(columns: List[str]) -> str:
        """Format a table row with tab-separated columns."""
        return "\t".join(str(col) for col in columns)

    @staticmethod
    def create_table_header(headers: List[str]) -> str:
        """Create a table header."""
        return ExportFormatter.format_table_row(headers)
