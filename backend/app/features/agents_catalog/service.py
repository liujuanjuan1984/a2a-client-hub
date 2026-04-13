"""Unified current-user agent catalog helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.a2a_agent import A2AAgent
from app.features.agents_shared.card_validation import fetch_and_validate_agent_card
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


@dataclass(frozen=True)
class UnifiedAgentHealthCheckSummaryRecord:
    requested: int
    checked: int
    skipped_cooldown: int
    healthy: int
    degraded: int
    unavailable: int
    unknown: int


class UnifiedAgentCatalogService:
    """Current-user catalog aggregation across personal/shared/built-in agents."""

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

    async def list_catalog(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
    ) -> list[dict[str, Any]]:
        personal_records = await a2a_agent_service.list_all_agents(db, user_id=user_id)
        shared_records, _ = await hub_a2a_agent_service.list_visible_agents_for_user(
            db,
            user_id=user_id,
            page=1,
            size=1000,
        )
        built_in_profile = self_management_built_in_agent_service.get_profile()

        items: list[dict[str, Any]] = []
        if built_in_profile.configured:
            items.append(
                {
                    "id": built_in_profile.agent_id,
                    "source": "builtin",
                    "name": built_in_profile.name,
                    "card_url": "builtin://self-management-assistant",
                    "auth_type": "none",
                    "enabled": True,
                    "health_status": A2AAgent.HEALTH_HEALTHY,
                    "last_health_check_at": None,
                    "last_health_check_error": None,
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
                "health_status": A2AAgent.HEALTH_UNKNOWN,
                "last_health_check_at": None,
                "last_health_check_error": None,
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

        shared_records, _ = await hub_a2a_agent_service.list_visible_agents_for_user(
            db,
            user_id=user_id,
            page=1,
            size=1000,
        )
        gateway = cast(Any, get_a2a_service()).gateway
        for record in shared_records:
            now = utc_now()
            requested += 1
            checked += 1
            health_status = A2AAgent.HEALTH_HEALTHY
            error_message: str | None = None
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
                    health_status = A2AAgent.HEALTH_DEGRADED
                    error_message = self._normalize_health_error(
                        self._extract_validation_error(validation)
                    )
            except HubA2AUserCredentialRequiredError as exc:
                health_status = A2AAgent.HEALTH_UNKNOWN
                error_message = self._normalize_health_error(str(exc))
            except HubA2ARuntimeValidationError as exc:
                health_status = A2AAgent.HEALTH_DEGRADED
                error_message = self._normalize_health_error(str(exc))
            except (
                HubA2ARuntimeNotFoundError,
                A2AAgentUnavailableError,
                A2AClientResetRequiredError,
            ) as exc:
                health_status = A2AAgent.HEALTH_UNAVAILABLE
                error_message = self._normalize_health_error(str(exc))
            except Exception as exc:  # noqa: BLE001
                health_status = A2AAgent.HEALTH_UNAVAILABLE
                error_message = self._normalize_health_error(str(exc))

            status_counts[health_status] += 1
            items.append(
                UnifiedAgentHealthCheckItemRecord(
                    agent_id=str(record.id),
                    agent_source="shared",
                    health_status=health_status,
                    checked_at=now,
                    skipped_cooldown=False,
                    error=error_message,
                )
            )

        built_in_profile = self_management_built_in_agent_service.get_profile()
        if built_in_profile.configured:
            now = utc_now()
            requested += 1
            checked += 1
            status_counts[A2AAgent.HEALTH_HEALTHY] += 1
            items.append(
                UnifiedAgentHealthCheckItemRecord(
                    agent_id=built_in_profile.agent_id,
                    agent_source="builtin",
                    health_status=A2AAgent.HEALTH_HEALTHY,
                    checked_at=now,
                    skipped_cooldown=False,
                    error=None,
                )
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
