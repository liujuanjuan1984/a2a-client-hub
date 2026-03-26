"""Personal A2A agent feature service and credential helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, cast
from uuid import UUID

from sqlalchemy import and_, case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.secret_vault import user_llm_secret_vault
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_agent_credential import A2AAgentCredential
from app.db.session import AsyncSessionLocal
from app.db.transaction import commit_safely
from app.features.agents_shared.card_validation import fetch_and_validate_agent_card
from app.features.agents_shared.common import (
    ALLOWED_AUTH_TYPES,
    AgentValidationMixin,
    delete_agent_credentials,
    get_agent_credential,
    upsert_agent_credential,
)
from app.features.personal_agents.runtime import (
    A2ARuntimeValidationError,
    a2a_runtime_builder,
)
from app.integrations.a2a_client import get_a2a_service
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
)
from app.utils.timezone_util import utc_now


class A2AAgentError(RuntimeError):
    """Base error for A2A agent management."""


class A2AAgentNotFoundError(A2AAgentError):
    """Raised when the requested agent cannot be located."""


class A2AAgentValidationError(A2AAgentError):
    """Raised when payload validation fails."""


@dataclass(frozen=True)
class A2AAgentRecord:
    id: UUID
    name: str
    card_url: str
    auth_type: str
    auth_header: str | None
    auth_scheme: str | None
    enabled: bool
    health_status: str
    consecutive_health_check_failures: int
    last_health_check_at: datetime | None
    last_successful_health_check_at: datetime | None
    last_health_check_error: str | None
    tags: list[str]
    extra_headers: dict[str, str]
    created_at: object
    updated_at: object
    token_last4: Optional[str]
    username_hint: Optional[str]


@dataclass(frozen=True)
class A2AAgentListCounts:
    healthy: int
    degraded: int
    unavailable: int
    unknown: int


@dataclass(frozen=True)
class A2AAgentHealthCheckItemRecord:
    agent_id: UUID
    health_status: str
    checked_at: datetime
    skipped_cooldown: bool
    error: str | None


@dataclass(frozen=True)
class A2AAgentHealthCheckSummaryRecord:
    requested: int
    checked: int
    skipped_cooldown: int
    healthy: int
    degraded: int
    unavailable: int
    unknown: int


@dataclass(frozen=True)
class _A2AAgentHealthSnapshot:
    agent_id: UUID
    name: str
    card_url: str
    auth_type: str
    auth_header: str | None
    auth_scheme: str | None
    enabled: bool
    extra_headers: dict[str, str]
    health_status: str
    consecutive_health_check_failures: int
    last_health_check_at: datetime | None
    credential: A2AAgentCredential | None


class A2AAgentService(AgentValidationMixin):
    """Business logic wrapper for A2A agent CRUD and credential handling."""

    _validation_error_cls = A2AAgentValidationError
    _allowed_auth_types = ALLOWED_AUTH_TYPES

    def __init__(self) -> None:
        self._vault = user_llm_secret_vault

    @staticmethod
    def _build_record(
        agent: A2AAgent,
        *,
        token_last4: Optional[str],
        username_hint: Optional[str],
    ) -> A2AAgentRecord:
        return A2AAgentRecord(
            id=cast(UUID, agent.id),
            name=cast(str, agent.name),
            card_url=cast(str, agent.card_url),
            auth_type=cast(str, agent.auth_type),
            auth_header=cast(str | None, agent.auth_header),
            auth_scheme=cast(str | None, agent.auth_scheme),
            enabled=bool(getattr(agent, "enabled", True)),
            health_status=cast(
                str,
                getattr(agent, "health_status", A2AAgent.HEALTH_UNKNOWN),
            ),
            consecutive_health_check_failures=int(
                getattr(agent, "consecutive_health_check_failures", 0) or 0
            ),
            last_health_check_at=cast(
                datetime | None,
                getattr(agent, "last_health_check_at", None),
            ),
            last_successful_health_check_at=cast(
                datetime | None,
                getattr(agent, "last_successful_health_check_at", None),
            ),
            last_health_check_error=cast(
                str | None,
                getattr(agent, "last_health_check_error", None),
            ),
            tags=cast(list[str], agent.tags or []),
            extra_headers=cast(dict[str, str], agent.extra_headers or {}),
            created_at=cast(object, agent.created_at),
            updated_at=cast(object, agent.updated_at),
            token_last4=token_last4,
            username_hint=username_hint,
        )

    async def list_agents(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        page: int,
        size: int,
        health_bucket: str = "all",
    ) -> tuple[list[A2AAgentRecord], int, A2AAgentListCounts]:
        filters = [
            A2AAgent.user_id == user_id,
            A2AAgent.agent_scope == A2AAgent.SCOPE_PERSONAL,
            A2AAgent.deleted_at.is_(None),
        ]
        filters.extend(self._health_bucket_filters(health_bucket))
        counts = await self._list_counts(db, user_id=user_id)
        total_stmt = select(func.count(A2AAgent.id)).where(and_(*filters))
        total = int((await db.execute(total_stmt)).scalar() or 0)
        offset = max(page - 1, 0) * size
        health_rank = case(
            (A2AAgent.health_status == A2AAgent.HEALTH_HEALTHY, 0),
            (A2AAgent.health_status == A2AAgent.HEALTH_DEGRADED, 1),
            (A2AAgent.health_status == A2AAgent.HEALTH_UNKNOWN, 2),
            else_=3,
        )
        stmt = (
            select(
                A2AAgent,
                A2AAgentCredential.token_last4,
                A2AAgentCredential.username_hint,
            )
            .outerjoin(
                A2AAgentCredential,
                A2AAgentCredential.agent_id == A2AAgent.id,
            )
            .where(and_(*filters))
            .order_by(
                health_rank.asc(),
                A2AAgent.created_at.desc(),
                A2AAgent.id.desc(),
            )
            .offset(offset)
            .limit(size)
        )
        result = await db.execute(stmt)
        rows = result.all()
        return (
            [
                self._build_record(
                    cast(A2AAgent, row[0]),
                    token_last4=cast(str | None, row[1]),
                    username_hint=cast(str | None, row[2]),
                )
                for row in rows
            ],
            total,
            counts,
        )

    async def list_all_agents(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
    ) -> list[A2AAgentRecord]:
        stmt = (
            select(
                A2AAgent,
                A2AAgentCredential.token_last4,
                A2AAgentCredential.username_hint,
            )
            .outerjoin(
                A2AAgentCredential,
                A2AAgentCredential.agent_id == A2AAgent.id,
            )
            .where(
                and_(
                    A2AAgent.user_id == user_id,
                    A2AAgent.agent_scope == A2AAgent.SCOPE_PERSONAL,
                    A2AAgent.deleted_at.is_(None),
                )
            )
            .order_by(A2AAgent.created_at.desc(), A2AAgent.id.desc())
        )
        result = await db.execute(stmt)
        rows = result.all()
        return [
            self._build_record(
                cast(A2AAgent, row[0]),
                token_last4=cast(str | None, row[1]),
                username_hint=cast(str | None, row[2]),
            )
            for row in rows
        ]

    async def check_agents_health(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        force: bool = False,
        agent_id: UUID | None = None,
    ) -> tuple[A2AAgentHealthCheckSummaryRecord, list[A2AAgentHealthCheckItemRecord]]:
        del db
        snapshots = await self._load_health_snapshots(
            user_id=user_id, agent_id=agent_id
        )
        if agent_id is not None and not snapshots:
            raise A2AAgentNotFoundError("A2A agent not found")

        cooldown_window = timedelta(
            seconds=settings.a2a_agent_health_check_cooldown_seconds
        )
        gateway = cast(Any, get_a2a_service()).gateway
        pending_updates: list[tuple[UUID, dict[str, Any]]] = []
        items: list[A2AAgentHealthCheckItemRecord] = []
        status_counts = {
            A2AAgent.HEALTH_HEALTHY: 0,
            A2AAgent.HEALTH_DEGRADED: 0,
            A2AAgent.HEALTH_UNAVAILABLE: 0,
            A2AAgent.HEALTH_UNKNOWN: 0,
        }
        checked = 0
        skipped_cooldown = 0

        for snapshot in snapshots:
            now = utc_now()
            if (
                not force
                and snapshot.last_health_check_at is not None
                and snapshot.last_health_check_at + cooldown_window > now
            ):
                skipped_cooldown += 1
                status = self._normalize_health_status(snapshot.health_status)
                status_counts[status] += 1
                items.append(
                    A2AAgentHealthCheckItemRecord(
                        agent_id=snapshot.agent_id,
                        health_status=status,
                        checked_at=snapshot.last_health_check_at,
                        skipped_cooldown=True,
                        error=None,
                    )
                )
                continue

            checked += 1
            try:
                resolved, _ = a2a_runtime_builder.resolve_prefetched(
                    name=snapshot.name,
                    card_url=snapshot.card_url,
                    extra_headers=snapshot.extra_headers,
                    auth_type=snapshot.auth_type,
                    auth_header=snapshot.auth_header,
                    auth_scheme=snapshot.auth_scheme,
                    credential=snapshot.credential,
                )
                validation = await fetch_and_validate_agent_card(
                    gateway=gateway,
                    resolved=resolved,
                )
                if validation.success:
                    next_status = A2AAgent.HEALTH_HEALTHY
                    pending_updates.append(
                        (
                            snapshot.agent_id,
                            {
                                "health_status": next_status,
                                "consecutive_health_check_failures": 0,
                                "last_health_check_at": now,
                                "last_successful_health_check_at": now,
                                "last_health_check_error": None,
                            },
                        )
                    )
                    status_counts[next_status] += 1
                    items.append(
                        A2AAgentHealthCheckItemRecord(
                            agent_id=snapshot.agent_id,
                            health_status=next_status,
                            checked_at=now,
                            skipped_cooldown=False,
                            error=None,
                        )
                    )
                    continue

                next_status, failure_count = self._resolve_failure_status(
                    snapshot.consecutive_health_check_failures
                )
                error_message = self._normalize_health_error(
                    self._extract_validation_error(validation)
                )
                pending_updates.append(
                    (
                        snapshot.agent_id,
                        {
                            "health_status": next_status,
                            "consecutive_health_check_failures": failure_count,
                            "last_health_check_at": now,
                            "last_health_check_error": error_message,
                        },
                    )
                )
                status_counts[next_status] += 1
                items.append(
                    A2AAgentHealthCheckItemRecord(
                        agent_id=snapshot.agent_id,
                        health_status=next_status,
                        checked_at=now,
                        skipped_cooldown=False,
                        error=error_message,
                    )
                )
            except (
                A2AAgentUnavailableError,
                A2AClientResetRequiredError,
                A2ARuntimeValidationError,
            ) as exc:
                next_status, failure_count = self._resolve_failure_status(
                    snapshot.consecutive_health_check_failures
                )
                error_message = self._normalize_health_error(str(exc))
                pending_updates.append(
                    (
                        snapshot.agent_id,
                        {
                            "health_status": next_status,
                            "consecutive_health_check_failures": failure_count,
                            "last_health_check_at": now,
                            "last_health_check_error": error_message,
                        },
                    )
                )
                status_counts[next_status] += 1
                items.append(
                    A2AAgentHealthCheckItemRecord(
                        agent_id=snapshot.agent_id,
                        health_status=next_status,
                        checked_at=now,
                        skipped_cooldown=False,
                        error=error_message,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                next_status, failure_count = self._resolve_failure_status(
                    snapshot.consecutive_health_check_failures
                )
                error_message = self._normalize_health_error(str(exc))
                pending_updates.append(
                    (
                        snapshot.agent_id,
                        {
                            "health_status": next_status,
                            "consecutive_health_check_failures": failure_count,
                            "last_health_check_at": now,
                            "last_health_check_error": error_message,
                        },
                    )
                )
                status_counts[next_status] += 1
                items.append(
                    A2AAgentHealthCheckItemRecord(
                        agent_id=snapshot.agent_id,
                        health_status=next_status,
                        checked_at=now,
                        skipped_cooldown=False,
                        error=error_message,
                    )
                )

        if pending_updates:
            await self._persist_health_updates(user_id=user_id, updates=pending_updates)

        summary = A2AAgentHealthCheckSummaryRecord(
            requested=len(snapshots),
            checked=checked,
            skipped_cooldown=skipped_cooldown,
            healthy=status_counts[A2AAgent.HEALTH_HEALTHY],
            degraded=status_counts[A2AAgent.HEALTH_DEGRADED],
            unavailable=status_counts[A2AAgent.HEALTH_UNAVAILABLE],
            unknown=status_counts[A2AAgent.HEALTH_UNKNOWN],
        )
        return summary, items

    async def get_agent(
        self, db: AsyncSession, *, user_id: UUID, agent_id: UUID
    ) -> A2AAgent:
        """Return a single agent owned by the user."""

        return await self._get_agent(db, user_id=user_id, agent_id=agent_id)

    async def create_agent(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        name: str,
        card_url: str,
        auth_type: str,
        auth_header: Optional[str] = None,
        auth_scheme: Optional[str] = None,
        enabled: bool = True,
        tags: Optional[Iterable[str]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        token: Optional[str] = None,
        basic_username: Optional[str] = None,
        basic_password: Optional[str] = None,
    ) -> A2AAgentRecord:
        normalized_name = self._normalize_name(name)
        normalized_url = self._normalize_card_url(card_url)
        await self._ensure_card_url_unique(db, user_id, normalized_url)

        normalized_auth_type = self._normalize_auth_type(auth_type)
        normalized_tags = self._normalize_tags(tags)
        normalized_headers = self._normalize_headers(extra_headers)

        auth_header_value, auth_scheme_value = self._resolve_auth_fields(
            normalized_auth_type, auth_header, auth_scheme, existing=None
        )

        agent = A2AAgent(
            user_id=user_id,
            name=normalized_name,
            card_url=normalized_url,
            agent_scope=A2AAgent.SCOPE_PERSONAL,
            availability_policy="public",
            auth_type=normalized_auth_type,
            auth_header=auth_header_value,
            auth_scheme=auth_scheme_value,
            enabled=enabled,
            tags=normalized_tags or None,
            extra_headers=normalized_headers or None,
        )
        db.add(agent)
        await db.flush()

        token_last4: Optional[str] = None
        username_hint: Optional[str] = None
        if normalized_auth_type == "none" and (
            token is not None
            or basic_username is not None
            or basic_password is not None
        ):
            raise A2AAgentValidationError("Credential provided for auth_type=none")
        if normalized_auth_type in {"bearer", "basic"}:
            preview = await self._upsert_credential(
                db,
                user_id=user_id,
                agent_id=cast(UUID, agent.id),
                auth_type=normalized_auth_type,
                token=token,
                basic_username=basic_username,
                basic_password=basic_password,
            )
            if normalized_auth_type == "basic":
                username_hint = (basic_username or "").strip() or None
            else:
                token_last4 = preview

        await commit_safely(db)
        await db.refresh(agent)
        return self._build_record(
            agent,
            token_last4=token_last4,
            username_hint=username_hint,
        )

    async def update_agent(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
        name: Optional[str] = None,
        card_url: Optional[str] = None,
        auth_type: Optional[str] = None,
        auth_header: Optional[str] = None,
        auth_scheme: Optional[str] = None,
        enabled: Optional[bool] = None,
        tags: Optional[Iterable[str]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        token: Optional[str] = None,
        basic_username: Optional[str] = None,
        basic_password: Optional[str] = None,
    ) -> A2AAgentRecord:
        agent = await self._get_agent(db, user_id=user_id, agent_id=agent_id)
        previous_auth_type = cast(str, agent.auth_type)

        if name is not None:
            setattr(agent, "name", self._normalize_name(name))
        if card_url is not None:
            normalized_url = self._normalize_card_url(card_url)
            await self._ensure_card_url_unique(
                db, user_id, normalized_url, exclude_id=cast(UUID | None, agent.id)
            )
            setattr(agent, "card_url", normalized_url)

        if enabled is not None:
            setattr(agent, "enabled", enabled)

        if tags is not None:
            normalized_tags = self._normalize_tags(tags)
            setattr(agent, "tags", normalized_tags or None)

        if extra_headers is not None:
            normalized_headers = self._normalize_headers(extra_headers)
            setattr(agent, "extra_headers", normalized_headers or None)

        if auth_type is not None:
            setattr(agent, "auth_type", self._normalize_auth_type(auth_type))

        auth_header_value, auth_scheme_value = self._resolve_auth_fields(
            cast(str, agent.auth_type),
            auth_header,
            auth_scheme,
            existing=agent,
        )
        setattr(agent, "auth_header", auth_header_value)
        setattr(agent, "auth_scheme", auth_scheme_value)

        if cast(str, agent.auth_type) == "none" and (
            token is not None
            or basic_username is not None
            or basic_password is not None
        ):
            raise A2AAgentValidationError("Credential provided for auth_type=none")

        token_last4, username_hint = await self._sync_credentials(
            db,
            user_id=user_id,
            agent=agent,
            previous_auth_type=previous_auth_type,
            token=token,
            basic_username=basic_username,
            basic_password=basic_password,
        )

        await commit_safely(db)
        await db.refresh(agent)
        return self._build_record(
            agent,
            token_last4=token_last4,
            username_hint=username_hint,
        )

    async def delete_agent(
        self, db: AsyncSession, *, user_id: UUID, agent_id: UUID
    ) -> None:
        agent = await self._get_agent(db, user_id=user_id, agent_id=agent_id)
        agent.soft_delete()
        await delete_agent_credentials(db, agent_id=cast(UUID, agent.id))
        await commit_safely(db)

    # ----------------------
    # Internal helpers
    # ----------------------
    async def _get_agent(
        self, db: AsyncSession, *, user_id: UUID, agent_id: UUID
    ) -> A2AAgent:
        stmt = select(A2AAgent).where(
            and_(
                A2AAgent.id == agent_id,
                A2AAgent.user_id == user_id,
                A2AAgent.agent_scope == A2AAgent.SCOPE_PERSONAL,
                A2AAgent.deleted_at.is_(None),
            )
        )
        agent = cast(A2AAgent | None, await db.scalar(stmt))
        if agent is None:
            raise A2AAgentNotFoundError("A2A agent not found")
        return agent

    async def _ensure_card_url_unique(
        self,
        db: AsyncSession,
        user_id: UUID,
        card_url: str,
        exclude_id: Optional[UUID] = None,
    ) -> None:
        stmt = select(A2AAgent.id).where(
            and_(
                A2AAgent.user_id == user_id,
                A2AAgent.agent_scope == A2AAgent.SCOPE_PERSONAL,
                A2AAgent.card_url == card_url,
                A2AAgent.deleted_at.is_(None),
            )
        )
        if exclude_id:
            stmt = stmt.where(A2AAgent.id != exclude_id)
        existing = await db.scalar(stmt)
        if existing is not None:
            raise A2AAgentValidationError("Agent card URL already exists")

    async def _sync_credentials(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent: A2AAgent,
        previous_auth_type: Optional[str] = None,
        token: Optional[str],
        basic_username: Optional[str],
        basic_password: Optional[str],
    ) -> tuple[Optional[str], Optional[str]]:
        auth_type = cast(str, agent.auth_type)
        agent_id = cast(UUID, agent.id)
        if auth_type == "none":
            await delete_agent_credentials(db, agent_id=agent_id)
            return None, None

        if auth_type not in {"bearer", "basic"}:
            raise A2AAgentValidationError("Unsupported auth_type")

        credential = await get_agent_credential(db, agent_id=agent_id)
        if token is None and basic_username is None and basic_password is None:
            if credential is None:
                if auth_type == "bearer":
                    raise A2AAgentValidationError("Bearer token is required")
                raise A2AAgentValidationError("Basic credentials are required")
            if previous_auth_type is not None and previous_auth_type != auth_type:
                raise A2AAgentValidationError(
                    "New credentials are required when changing auth_type"
                )
            return (
                cast(str | None, credential.token_last4),
                cast(str | None, credential.username_hint),
            )

        preview = await self._upsert_credential(
            db,
            user_id=user_id,
            agent_id=agent_id,
            auth_type=auth_type,
            token=token,
            basic_username=basic_username,
            basic_password=basic_password,
        )
        if auth_type == "basic":
            return None, (basic_username or "").strip() or None
        return preview, None

    async def _upsert_credential(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
        auth_type: str,
        token: Optional[str],
        basic_username: Optional[str] = None,
        basic_password: Optional[str] = None,
    ) -> Optional[str]:
        value = await upsert_agent_credential(
            db,
            vault=self._vault,
            auth_type=auth_type,
            agent_id=agent_id,
            user_id=user_id,
            token=token,
            basic_username=basic_username,
            basic_password=basic_password,
            validation_error_cls=A2AAgentValidationError,
        )
        return value or None

    async def _list_counts(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
    ) -> A2AAgentListCounts:
        stmt = select(
            func.coalesce(
                func.sum(
                    case(
                        (A2AAgent.health_status == A2AAgent.HEALTH_HEALTHY, 1),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (A2AAgent.health_status == A2AAgent.HEALTH_DEGRADED, 1),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (A2AAgent.health_status == A2AAgent.HEALTH_UNAVAILABLE, 1),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (A2AAgent.health_status == A2AAgent.HEALTH_UNKNOWN, 1),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(
            and_(
                A2AAgent.user_id == user_id,
                A2AAgent.agent_scope == A2AAgent.SCOPE_PERSONAL,
                A2AAgent.deleted_at.is_(None),
            )
        )
        row = (await db.execute(stmt)).one()
        return A2AAgentListCounts(
            healthy=int(row[0] or 0),
            degraded=int(row[1] or 0),
            unavailable=int(row[2] or 0),
            unknown=int(row[3] or 0),
        )

    def _health_bucket_filters(self, health_bucket: str) -> list[Any]:
        if health_bucket == "all":
            return []
        if health_bucket == "healthy":
            return [A2AAgent.health_status == A2AAgent.HEALTH_HEALTHY]
        if health_bucket == "attention":
            return [
                A2AAgent.health_status.in_(
                    [
                        A2AAgent.HEALTH_DEGRADED,
                        A2AAgent.HEALTH_UNAVAILABLE,
                        A2AAgent.HEALTH_UNKNOWN,
                    ]
                )
            ]
        raise A2AAgentValidationError("Unsupported health_bucket")

    async def _load_health_snapshots(
        self,
        *,
        user_id: UUID,
        agent_id: UUID | None,
    ) -> list[_A2AAgentHealthSnapshot]:
        async with AsyncSessionLocal() as read_db:
            filters = [
                A2AAgent.user_id == user_id,
                A2AAgent.agent_scope == A2AAgent.SCOPE_PERSONAL,
                A2AAgent.deleted_at.is_(None),
            ]
            if agent_id is None:
                filters.append(A2AAgent.enabled.is_(True))
            else:
                filters.append(A2AAgent.id == agent_id)

            stmt = (
                select(A2AAgent, A2AAgentCredential)
                .outerjoin(
                    A2AAgentCredential,
                    A2AAgentCredential.agent_id == A2AAgent.id,
                )
                .where(and_(*filters))
                .order_by(A2AAgent.created_at.desc(), A2AAgent.id.desc())
            )
            rows = (await read_db.execute(stmt)).all()
            return [
                _A2AAgentHealthSnapshot(
                    agent_id=cast(UUID, agent.id),
                    name=cast(str, agent.name),
                    card_url=cast(str, agent.card_url),
                    auth_type=cast(str, agent.auth_type),
                    auth_header=cast(str | None, agent.auth_header),
                    auth_scheme=cast(str | None, agent.auth_scheme),
                    enabled=bool(getattr(agent, "enabled", True)),
                    extra_headers=cast(dict[str, str], agent.extra_headers or {}),
                    health_status=cast(
                        str,
                        getattr(agent, "health_status", A2AAgent.HEALTH_UNKNOWN),
                    ),
                    consecutive_health_check_failures=int(
                        getattr(agent, "consecutive_health_check_failures", 0) or 0
                    ),
                    last_health_check_at=cast(
                        datetime | None,
                        getattr(agent, "last_health_check_at", None),
                    ),
                    credential=cast(A2AAgentCredential | None, credential),
                )
                for agent, credential in rows
            ]

    async def _persist_health_updates(
        self,
        *,
        user_id: UUID,
        updates: list[tuple[UUID, dict[str, Any]]],
    ) -> None:
        async with AsyncSessionLocal() as write_db:
            for agent_id, values in updates:
                stmt = (
                    update(A2AAgent)
                    .where(
                        and_(
                            A2AAgent.id == agent_id,
                            A2AAgent.user_id == user_id,
                            A2AAgent.agent_scope == A2AAgent.SCOPE_PERSONAL,
                            A2AAgent.deleted_at.is_(None),
                        )
                    )
                    .values(**values)
                )
                await write_db.execute(stmt)
            await commit_safely(write_db)

    def _resolve_failure_status(self, failures: int) -> tuple[str, int]:
        next_failures = failures + 1
        if next_failures >= settings.a2a_agent_health_unavailable_threshold:
            return A2AAgent.HEALTH_UNAVAILABLE, next_failures
        return A2AAgent.HEALTH_DEGRADED, next_failures

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
    def _normalize_health_error(value: str | None) -> str:
        message = (value or "").strip()
        if not message:
            return "Agent health check failed"
        if len(message) > 500:
            return f"{message[:497]}..."
        return message

    def _normalize_tags(self, tags: Optional[Iterable[str]]) -> List[str]:
        if tags is None:
            return []
        normalized: List[str] = []
        for tag in tags:
            value = str(tag).strip()
            if value:
                normalized.append(value)
        return normalized

    def _normalize_headers(self, headers: Optional[Dict[str, str]]) -> Dict[str, str]:
        if headers is None:
            return {}
        if not isinstance(headers, dict):
            raise A2AAgentValidationError("extra_headers must be a dictionary")
        normalized: Dict[str, str] = {}
        for key, value in headers.items():
            header_key = str(key).strip()
            if not header_key:
                raise A2AAgentValidationError("extra_headers contains empty key")
            header_value = "" if value is None else str(value).strip()
            normalized[header_key] = header_value
        return normalized


a2a_agent_service = A2AAgentService()

__all__ = [
    "A2AAgentError",
    "A2AAgentNotFoundError",
    "A2AAgentRecord",
    "A2AAgentService",
    "A2AAgentValidationError",
    "a2a_agent_service",
]
