"""Unified current-user agent catalog helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.a2a_agent import A2AAgent
from app.db.models.user_agent_availability_snapshot import (
    UserAgentAvailabilitySnapshot,
)
from app.db.transaction import commit_safely
from app.features.agents_shared.card_validation import fetch_and_validate_agent_card
from app.features.health_check_helpers import (
    build_health_check_item_fields,
    build_health_snapshot_update,
)
from app.features.hub_agents.runtime import (
    HubA2ARuntimeNotFoundError,
    HubA2ARuntimeValidationError,
    HubA2AUserCredentialRequiredError,
    hub_a2a_runtime_builder,
)
from app.features.hub_agents.service import hub_a2a_agent_service
from app.features.personal_agents.service import a2a_agent_service
from app.features.self_management_agent.service import (
    self_management_built_in_agent_service,
)
from app.integrations.a2a_client import get_a2a_service
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
)
from app.utils.timezone_util import utc_now


@dataclass(frozen=True)
class UnifiedAgentHealthCheckItemRecord:
    agent_id: str
    agent_source: str
    health_status: str
    checked_at: datetime
    skipped_cooldown: bool
    error: str | None
    reason_code: str | None


@dataclass(frozen=True)
class UnifiedAgentHealthCheckSummaryRecord:
    requested: int
    checked: int
    skipped_cooldown: int
    healthy: int
    degraded: int
    unavailable: int
    unknown: int


@dataclass(frozen=True)
class _AvailabilitySnapshotRecord:
    agent_source: str
    agent_id: str
    health_status: str
    consecutive_health_check_failures: int
    last_health_check_at: datetime | None
    last_successful_health_check_at: datetime | None
    last_health_check_error: str | None
    last_health_check_reason_code: str | None


class UnifiedAgentCatalogService:
    """Current-user catalog aggregation across personal/shared/built-in agents."""

    _non_personal_sources = ("shared", "builtin")
    _reason_card_validation_failed = "card_validation_failed"
    _reason_runtime_validation_failed = "runtime_validation_failed"
    _reason_agent_unavailable = "agent_unavailable"
    _reason_client_reset_required = "client_reset_required"
    _reason_credential_required = "credential_required"
    _reason_unexpected_error = "unexpected_error"

    @staticmethod
    def _extract_validation_error(validation: Any) -> str:
        raw_errors = getattr(validation, "validation_errors", None)
        if isinstance(raw_errors, list) and raw_errors:
            first_error = raw_errors[0]
            if isinstance(first_error, str) and first_error.strip():
                return first_error.strip()
        message = getattr(validation, "message", None)
        if isinstance(message, str) and message.strip():
            return message.strip()
        return "Agent card validation issues detected"

    @staticmethod
    def _normalize_health_error(value: str | None) -> str:
        message = (value or "").strip()
        if not message:
            return "Agent health check failed"
        if len(message) > 500:
            return f"{message[:497]}..."
        return message

    @staticmethod
    def _normalize_health_status(value: str | None) -> str:
        if value in {
            A2AAgent.HEALTH_HEALTHY,
            A2AAgent.HEALTH_DEGRADED,
            A2AAgent.HEALTH_UNAVAILABLE,
            A2AAgent.HEALTH_UNKNOWN,
        }:
            return value
        return A2AAgent.HEALTH_UNKNOWN

    @staticmethod
    def _resolve_failure_status(failures: int) -> tuple[str, int]:
        next_failures = failures + 1
        if next_failures >= settings.a2a_agent_health_unavailable_threshold:
            return A2AAgent.HEALTH_UNAVAILABLE, next_failures
        return A2AAgent.HEALTH_DEGRADED, next_failures

    async def _list_all_visible_shared_agents(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        page_size: int = 200,
    ) -> list[Any]:
        page = 1
        items: list[Any] = []
        total = None

        while total is None or len(items) < total:
            page_items, page_total = (
                await hub_a2a_agent_service.list_visible_agents_for_user(
                    db,
                    user_id=user_id,
                    page=page,
                    size=page_size,
                )
            )
            if not page_items:
                break
            items.extend(page_items)
            total = page_total
            page += 1

        return items

    async def _load_availability_snapshots(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        keys: set[tuple[str, str]],
    ) -> dict[tuple[str, str], _AvailabilitySnapshotRecord]:
        if not keys:
            return {}

        rows = (
            await db.scalars(
                select(UserAgentAvailabilitySnapshot).where(
                    UserAgentAvailabilitySnapshot.user_id == user_id,
                    tuple_(
                        UserAgentAvailabilitySnapshot.agent_source,
                        UserAgentAvailabilitySnapshot.agent_id,
                    ).in_(sorted(keys)),
                )
            )
        ).all()

        snapshots: dict[tuple[str, str], _AvailabilitySnapshotRecord] = {}
        for row in rows:
            key = (str(row.agent_source), str(row.agent_id))
            snapshots[key] = _AvailabilitySnapshotRecord(
                agent_source=str(row.agent_source),
                agent_id=str(row.agent_id),
                health_status=self._normalize_health_status(
                    cast(str | None, row.health_status)
                ),
                consecutive_health_check_failures=int(
                    cast(int | None, row.consecutive_health_check_failures) or 0
                ),
                last_health_check_at=cast(datetime | None, row.last_health_check_at),
                last_successful_health_check_at=cast(
                    datetime | None, row.last_successful_health_check_at
                ),
                last_health_check_error=cast(str | None, row.last_health_check_error),
                last_health_check_reason_code=cast(
                    str | None, row.last_health_check_reason_code
                ),
            )
        return snapshots

    async def _persist_availability_updates(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        updates: list[tuple[str, str, dict[str, Any]]],
    ) -> None:
        if not updates:
            return

        keys = {(source, agent_id) for source, agent_id, _ in updates}
        existing_rows = (
            await db.scalars(
                select(UserAgentAvailabilitySnapshot).where(
                    UserAgentAvailabilitySnapshot.user_id == user_id,
                    tuple_(
                        UserAgentAvailabilitySnapshot.agent_source,
                        UserAgentAvailabilitySnapshot.agent_id,
                    ).in_(sorted(keys)),
                )
            )
        ).all()
        existing_by_key = {
            (str(row.agent_source), str(row.agent_id)): row for row in existing_rows
        }

        for source, agent_id, payload in updates:
            row = existing_by_key.get((source, agent_id))
            if row is None:
                row = UserAgentAvailabilitySnapshot(
                    user_id=user_id,
                    agent_source=source,
                    agent_id=agent_id,
                )
                db.add(row)
                existing_by_key[(source, agent_id)] = row

            for field, value in payload.items():
                setattr(row, field, value)

        await commit_safely(db)

    async def list_catalog(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
    ) -> list[dict[str, Any]]:
        personal_records = await a2a_agent_service.list_all_agents(db, user_id=user_id)
        shared_records = await self._list_all_visible_shared_agents(db, user_id=user_id)
        built_in_profile = self_management_built_in_agent_service.get_profile()
        keys = {("shared", str(record.id)) for record in shared_records}
        if built_in_profile.configured:
            keys.add(("builtin", built_in_profile.agent_id))
        snapshots = await self._load_availability_snapshots(
            db,
            user_id=user_id,
            keys=keys,
        )

        items: list[dict[str, Any]] = []
        if built_in_profile.configured:
            built_in_snapshot = snapshots.get(("builtin", built_in_profile.agent_id))
            items.append(
                {
                    "id": built_in_profile.agent_id,
                    "source": "builtin",
                    "name": built_in_profile.name,
                    "card_url": "builtin://self-management-assistant",
                    "auth_type": "none",
                    "enabled": True,
                    "health_status": (
                        built_in_snapshot.health_status
                        if built_in_snapshot is not None
                        else A2AAgent.HEALTH_UNKNOWN
                    ),
                    "last_health_check_at": (
                        built_in_snapshot.last_health_check_at
                        if built_in_snapshot is not None
                        else None
                    ),
                    "last_health_check_error": (
                        built_in_snapshot.last_health_check_error
                        if built_in_snapshot is not None
                        else None
                    ),
                    "last_health_check_reason_code": (
                        built_in_snapshot.last_health_check_reason_code
                        if built_in_snapshot is not None
                        else None
                    ),
                    "description": built_in_profile.description,
                    "runtime": built_in_profile.runtime,
                    "resources": list(built_in_profile.resources),
                    "extra_headers": {},
                    "invoke_metadata_defaults": {},
                }
            )

        items.extend(
            {
                "id": str(record.id),
                "source": "personal",
                "name": record.name,
                "card_url": record.card_url,
                "auth_type": record.auth_type,
                "enabled": record.enabled,
                "health_status": record.health_status,
                "last_health_check_at": record.last_health_check_at,
                "last_health_check_error": record.last_health_check_error,
                "last_health_check_reason_code": record.last_health_check_reason_code,
                "extra_headers": dict(record.extra_headers),
                "invoke_metadata_defaults": dict(record.invoke_metadata_defaults),
            }
            for record in personal_records
        )
        items.extend(
            {
                "id": str(record.id),
                "source": "shared",
                "name": record.name,
                "card_url": record.card_url,
                "auth_type": record.auth_type,
                "enabled": True,
                "health_status": (
                    snapshots[("shared", str(record.id))].health_status
                    if ("shared", str(record.id)) in snapshots
                    else A2AAgent.HEALTH_UNKNOWN
                ),
                "last_health_check_at": (
                    snapshots[("shared", str(record.id))].last_health_check_at
                    if ("shared", str(record.id)) in snapshots
                    else None
                ),
                "last_health_check_error": (
                    snapshots[("shared", str(record.id))].last_health_check_error
                    if ("shared", str(record.id)) in snapshots
                    else None
                ),
                "last_health_check_reason_code": (
                    snapshots[("shared", str(record.id))].last_health_check_reason_code
                    if ("shared", str(record.id)) in snapshots
                    else None
                ),
                "credential_mode": record.credential_mode,
                "credential_configured": record.credential_configured,
                "credential_display_hint": record.credential_display_hint,
                "extra_headers": {},
                "invoke_metadata_defaults": {},
            }
            for record in shared_records
        )
        return items

    async def check_catalog_health(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        force: bool = False,
    ) -> tuple[
        UnifiedAgentHealthCheckSummaryRecord,
        list[UnifiedAgentHealthCheckItemRecord],
    ]:
        personal_summary, personal_items = await a2a_agent_service.check_agents_health(
            user_id=user_id,
            force=force,
        )

        items: list[UnifiedAgentHealthCheckItemRecord] = [
            UnifiedAgentHealthCheckItemRecord(
                agent_id=str(item.agent_id),
                agent_source="personal",
                health_status=item.health_status,
                checked_at=item.checked_at,
                skipped_cooldown=item.skipped_cooldown,
                error=item.error,
                reason_code=item.reason_code,
            )
            for item in personal_items
        ]
        requested = personal_summary.requested
        checked = personal_summary.checked
        skipped_cooldown = personal_summary.skipped_cooldown
        status_counts = {
            A2AAgent.HEALTH_HEALTHY: personal_summary.healthy,
            A2AAgent.HEALTH_DEGRADED: personal_summary.degraded,
            A2AAgent.HEALTH_UNAVAILABLE: personal_summary.unavailable,
            A2AAgent.HEALTH_UNKNOWN: personal_summary.unknown,
        }

        shared_records = await self._list_all_visible_shared_agents(db, user_id=user_id)
        built_in_profile = self_management_built_in_agent_service.get_profile()
        keys = {("shared", str(record.id)) for record in shared_records}
        if built_in_profile.configured:
            keys.add(("builtin", built_in_profile.agent_id))
        snapshots = await self._load_availability_snapshots(
            db,
            user_id=user_id,
            keys=keys,
        )
        cooldown_window = timedelta(
            seconds=settings.a2a_agent_health_check_cooldown_seconds
        )
        gateway = cast(Any, get_a2a_service()).gateway
        pending_updates: list[tuple[str, str, dict[str, Any]]] = []

        def _append_item(
            *,
            agent_id: str,
            agent_source: str,
            health_status: str,
            checked_at: datetime,
            skipped: bool,
            error: str | None,
            reason_code: str | None,
        ) -> None:
            status_counts[health_status] += 1
            items.append(
                UnifiedAgentHealthCheckItemRecord(
                    agent_id=agent_id,
                    agent_source=agent_source,
                    **build_health_check_item_fields(
                        health_status=health_status,
                        checked_at=checked_at,
                        skipped_cooldown=skipped,
                        error=error,
                        reason_code=reason_code,
                    ),
                )
            )

        for record in shared_records:
            snapshot = snapshots.get(("shared", str(record.id)))
            now = utc_now()
            requested += 1
            if (
                not force
                and snapshot is not None
                and snapshot.last_health_check_at is not None
                and snapshot.last_health_check_at + cooldown_window > now
            ):
                skipped_cooldown += 1
                _append_item(
                    agent_id=str(record.id),
                    agent_source="shared",
                    health_status=snapshot.health_status,
                    checked_at=snapshot.last_health_check_at,
                    skipped=True,
                    error=snapshot.last_health_check_error,
                    reason_code=snapshot.last_health_check_reason_code,
                )
                continue

            checked += 1
            health_status = A2AAgent.HEALTH_HEALTHY
            error_message: str | None = None
            reason_code: str | None = None
            consecutive_failures = 0
            try:
                runtime = await hub_a2a_runtime_builder.build(
                    db,
                    user_id=user_id,
                    agent_id=record.id,
                )
                validation = await fetch_and_validate_agent_card(
                    gateway=gateway,
                    resolved=runtime.resolved,
                )
                if not validation.success:
                    health_status, consecutive_failures = self._resolve_failure_status(
                        snapshot.consecutive_health_check_failures
                        if snapshot is not None
                        else 0
                    )
                    reason_code = self._reason_card_validation_failed
                    error_message = self._normalize_health_error(
                        self._extract_validation_error(validation)
                    )
            except HubA2AUserCredentialRequiredError as exc:
                health_status = A2AAgent.HEALTH_UNAVAILABLE
                reason_code = self._reason_credential_required
                error_message = self._normalize_health_error(str(exc))
            except HubA2ARuntimeValidationError as exc:
                health_status, consecutive_failures = self._resolve_failure_status(
                    snapshot.consecutive_health_check_failures
                    if snapshot is not None
                    else 0
                )
                reason_code = self._reason_runtime_validation_failed
                error_message = self._normalize_health_error(str(exc))
            except HubA2ARuntimeNotFoundError as exc:
                health_status, consecutive_failures = self._resolve_failure_status(
                    snapshot.consecutive_health_check_failures
                    if snapshot is not None
                    else 0
                )
                reason_code = self._reason_agent_unavailable
                error_message = self._normalize_health_error(str(exc))
            except A2AAgentUnavailableError as exc:
                health_status, consecutive_failures = self._resolve_failure_status(
                    snapshot.consecutive_health_check_failures
                    if snapshot is not None
                    else 0
                )
                reason_code = self._reason_agent_unavailable
                error_message = self._normalize_health_error(str(exc))
            except A2AClientResetRequiredError as exc:
                health_status, consecutive_failures = self._resolve_failure_status(
                    snapshot.consecutive_health_check_failures
                    if snapshot is not None
                    else 0
                )
                reason_code = self._reason_client_reset_required
                error_message = self._normalize_health_error(str(exc))
            except Exception as exc:  # noqa: BLE001
                health_status, consecutive_failures = self._resolve_failure_status(
                    snapshot.consecutive_health_check_failures
                    if snapshot is not None
                    else 0
                )
                reason_code = self._reason_unexpected_error
                error_message = self._normalize_health_error(str(exc))

            pending_updates.append(
                (
                    "shared",
                    str(record.id),
                    build_health_snapshot_update(
                        health_status=health_status,
                        healthy_status=A2AAgent.HEALTH_HEALTHY,
                        checked_at=now,
                        consecutive_failures=consecutive_failures,
                        previous_last_successful_at=(
                            snapshot.last_successful_health_check_at
                            if snapshot is not None
                            else None
                        ),
                        error_message=error_message,
                        reason_code=reason_code,
                    ),
                )
            )
            _append_item(
                agent_id=str(record.id),
                agent_source="shared",
                health_status=health_status,
                checked_at=now,
                skipped=False,
                error=error_message,
                reason_code=reason_code,
            )

        if built_in_profile.configured:
            snapshot = snapshots.get(("builtin", built_in_profile.agent_id))
            now = utc_now()
            requested += 1
            if (
                not force
                and snapshot is not None
                and snapshot.last_health_check_at is not None
                and snapshot.last_health_check_at + cooldown_window > now
            ):
                skipped_cooldown += 1
                _append_item(
                    agent_id=built_in_profile.agent_id,
                    agent_source="builtin",
                    health_status=snapshot.health_status,
                    checked_at=snapshot.last_health_check_at,
                    skipped=True,
                    error=snapshot.last_health_check_error,
                    reason_code=snapshot.last_health_check_reason_code,
                )
            else:
                checked += 1
                health_status = (
                    A2AAgent.HEALTH_HEALTHY
                    if built_in_profile.configured
                    else A2AAgent.HEALTH_UNAVAILABLE
                )
                error_message = (
                    None
                    if built_in_profile.configured
                    else "Built-in self-management runtime is not configured"
                )
                pending_updates.append(
                    (
                        "builtin",
                        built_in_profile.agent_id,
                        build_health_snapshot_update(
                            health_status=health_status,
                            healthy_status=A2AAgent.HEALTH_HEALTHY,
                            checked_at=now,
                            consecutive_failures=(
                                0
                                if health_status == A2AAgent.HEALTH_HEALTHY
                                else (
                                    snapshot.consecutive_health_check_failures + 1
                                    if snapshot is not None
                                    else 1
                                )
                            ),
                            previous_last_successful_at=(
                                snapshot.last_successful_health_check_at
                                if snapshot is not None
                                else None
                            ),
                            error_message=error_message,
                            reason_code=None,
                        ),
                    )
                )
                _append_item(
                    agent_id=built_in_profile.agent_id,
                    agent_source="builtin",
                    health_status=health_status,
                    checked_at=now,
                    skipped=False,
                    error=error_message,
                    reason_code=None,
                )

        if pending_updates:
            await self._persist_availability_updates(
                db,
                user_id=user_id,
                updates=pending_updates,
            )

        return (
            UnifiedAgentHealthCheckSummaryRecord(
                requested=requested,
                checked=checked,
                skipped_cooldown=skipped_cooldown,
                healthy=status_counts[A2AAgent.HEALTH_HEALTHY],
                degraded=status_counts[A2AAgent.HEALTH_DEGRADED],
                unavailable=status_counts[A2AAgent.HEALTH_UNAVAILABLE],
                unknown=status_counts[A2AAgent.HEALTH_UNKNOWN],
            ),
            items,
        )


unified_agent_catalog_service = UnifiedAgentCatalogService()


__all__ = [
    "UnifiedAgentCatalogService",
    "UnifiedAgentHealthCheckItemRecord",
    "UnifiedAgentHealthCheckSummaryRecord",
    "unified_agent_catalog_service",
]
