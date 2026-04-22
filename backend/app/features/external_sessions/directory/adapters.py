"""Provider adapters for external session directory aggregation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Protocol, cast


def _as_record(value: Any) -> dict[str, Any] | None:
    if value and isinstance(value, dict):
        return cast(dict[str, Any], value)
    return None


def _pick_str(obj: Mapping[str, Any] | None, keys: Iterable[str]) -> str | None:
    if not obj:
        return None
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _pick_ms(obj: Mapping[str, Any] | None, keys: Iterable[str]) -> int | None:
    if not obj:
        return None
    for key in keys:
        value = obj.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


def _to_iso_from_ms(value: int | None) -> str | None:
    if value is None:
        return None
    try:
        dt = datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.isoformat()


def _read_int_env(name: str, *, default: int, maximum: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    if value > maximum:
        raise ValueError(f"{name} must not exceed {maximum}")
    return value


@dataclass(frozen=True)
class OpenCodeSessionDirectorySettings:
    cache_ttl_seconds: int = 90
    per_agent_size: int = 50
    refresh_concurrency: int = 4

    @classmethod
    def from_env(cls) -> "OpenCodeSessionDirectorySettings":
        return cls(
            cache_ttl_seconds=_read_int_env(
                "EXTERNAL_SESSION_DIRECTORY_OPENCODE_CACHE_TTL_SECONDS",
                default=90,
                maximum=3600,
            ),
            per_agent_size=_read_int_env(
                "EXTERNAL_SESSION_DIRECTORY_OPENCODE_PER_AGENT_SIZE",
                default=50,
                maximum=200,
            ),
            refresh_concurrency=_read_int_env(
                "EXTERNAL_SESSION_DIRECTORY_OPENCODE_REFRESH_CONCURRENCY",
                default=4,
                maximum=20,
            ),
        )


@dataclass(frozen=True)
class NormalizedExternalSession:
    session_id: str
    title: str
    last_active_at: str | None


class ExternalSessionDirectoryAdapter(Protocol):
    provider_key: str

    @property
    def cache_ttl_seconds(self) -> int:
        """Return cache TTL for this provider."""

    @property
    def per_agent_size(self) -> int:
        """Return upstream session query size for one agent."""

    @property
    def refresh_concurrency(self) -> int:
        """Return maximum concurrent upstream refreshes."""

    def normalize_task(self, task: Any) -> NormalizedExternalSession | None:
        """Normalize one upstream task/session payload for directory listing."""

    def prune_task_for_cache(self, task: Any) -> dict[str, Any] | None:
        """Return a sanitized payload suitable for the DB-backed cache."""


class OpenCodeSessionDirectoryAdapter:
    provider_key = "opencode"

    @property
    def cache_ttl_seconds(self) -> int:
        return OpenCodeSessionDirectorySettings.from_env().cache_ttl_seconds

    @property
    def per_agent_size(self) -> int:
        return OpenCodeSessionDirectorySettings.from_env().per_agent_size

    @property
    def refresh_concurrency(self) -> int:
        return OpenCodeSessionDirectorySettings.from_env().refresh_concurrency

    def normalize_task(self, task: Any) -> NormalizedExternalSession | None:
        session_id = self._extract_session_id(task)
        if not session_id:
            return None
        return NormalizedExternalSession(
            session_id=session_id,
            title=self._extract_title(task),
            last_active_at=self._extract_last_active_at(task),
        )

    def prune_task_for_cache(self, task: Any) -> dict[str, Any] | None:
        obj = _as_record(task)
        if not obj:
            return None
        normalized = self.normalize_task(obj)
        if normalized is None:
            return None

        metadata = _as_record(obj.get("metadata")) or {}
        opencode = _as_record(metadata.get("opencode")) or {}

        return {
            "id": obj.get("id"),
            "contextId": (
                obj.get("contextId") or obj.get("context_id") or normalized.session_id
            ),
            "last_active_at": normalized.last_active_at,
            "metadata": {
                "opencode": {
                    "session_id": normalized.session_id,
                    "title": opencode.get("title"),
                }
            },
        }

    @staticmethod
    def _extract_session_id(task: Any) -> str | None:
        obj = _as_record(task)
        metadata = _as_record(obj.get("metadata")) if obj else {}
        opencode = _as_record((metadata or {}).get("opencode")) or {}
        return _pick_str(
            opencode,
            ["session_id", "sessionId"],
        ) or _pick_str(obj, ["id", "session_id", "sessionId"])

    def _extract_title(self, task: Any) -> str:
        obj = _as_record(task) or {}
        metadata = _as_record(obj.get("metadata")) or {}
        opencode = _as_record(metadata.get("opencode")) or {}
        title = _pick_str(opencode, ["title"])
        if title:
            return title
        return (
            _pick_str(obj, ["title", "name", "label"])
            or self._extract_session_id(obj)
            or "Session"
        )

    @staticmethod
    def _extract_last_active_at(task: Any) -> str | None:
        obj = _as_record(task) or {}
        direct = _pick_str(
            obj, ["last_active_at", "updated_at", "created_at", "timestamp", "ts"]
        )
        if direct:
            return direct
        direct_ms = _pick_ms(obj, ["updated", "created", "timestamp", "ts"])
        if direct_ms is not None:
            return _to_iso_from_ms(direct_ms)

        metadata = _as_record(obj.get("metadata")) or {}
        opencode = _as_record(metadata.get("opencode")) or {}
        opencode_direct = _pick_str(
            opencode,
            ["last_active_at", "updated_at", "created_at", "timestamp", "ts"],
        )
        if opencode_direct:
            return opencode_direct
        opencode_ms = _pick_ms(opencode, ["updated", "created", "timestamp", "ts"])
        return _to_iso_from_ms(opencode_ms)


opencode_session_directory_adapter = OpenCodeSessionDirectoryAdapter()
