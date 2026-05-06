from __future__ import annotations

import asyncio
import importlib
import os
import sys
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from a2a.types import AgentCard
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

REPO_ROOT = os.path.dirname(PROJECT_ROOT)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.support.env_bootstrap import apply_test_environment

apply_test_environment()


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers to silence PytestUnknownMarkWarning."""

    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests",
    )


SCRIPT_ROOT = os.path.join(PROJECT_ROOT, "scripts")
if SCRIPT_ROOT not in sys.path:
    sys.path.insert(0, SCRIPT_ROOT)

from setup_db_schema import create_schema, drop_schema

from app.core.config import settings
from app.db.models.base import Base
from app.integrations.a2a_client.protobuf import (
    parse_agent_card,
    to_protojson_object,
)
from app.integrations.a2a_client.validators import validate_agent_card
from app.runtime.a2a_proxy_service import A2AProxyService

# Import the minimal set of models required for tests to ensure SQLAlchemy
# metadata is populated before schema setup runs.
for module_path in [
    "app.db.models.a2a_agent",
    "app.db.models.a2a_agent_credential",
    "app.db.models.a2a_proxy_allowlist",
    "app.db.models.hub_a2a_agent_allowlist",
    "app.db.models.hub_a2a_user_credential",
    "app.db.models.external_session_directory_cache",
    "app.db.models.a2a_schedule_task",
    "app.db.models.a2a_schedule_execution",
    "app.db.models.agent_message",
    "app.db.models.agent_message_block",
    "app.db.models.auth_audit_event",
    "app.db.models.auth_legacy_refresh_revocation",
    "app.db.models.auth_refresh_session",
    "app.db.models.user",
    "app.db.models.invitation",
    "app.db.models.ws_ticket",
    "app.db.models.shortcut",
]:
    importlib.import_module(module_path)

TEST_SCHEMA = settings.schema_name


def _agent_card_model_validate(
    cls: type[AgentCard],
    payload: dict[str, object],
) -> AgentCard:
    result = validate_agent_card(dict(payload))
    if result.errors:
        raise ValueError("; ".join(result.errors))
    return parse_agent_card(dict(payload), ignore_unknown_fields=False)


def _agent_card_model_dump(self: AgentCard, **_kwargs) -> dict[str, object]:
    return to_protojson_object(self) or {}


if not hasattr(AgentCard, "model_validate"):
    AgentCard.model_validate = classmethod(_agent_card_model_validate)

if not hasattr(AgentCard, "model_dump"):
    AgentCard.model_dump = _agent_card_model_dump


def _collect_truncate_targets() -> list[str]:
    table_names: list[str] = []
    for table in Base.metadata.sorted_tables:
        schema = table.schema or TEST_SCHEMA
        table_names.append(f'{schema}."{table.name}"')
    return table_names


def _build_truncate_statement() -> str | None:
    table_names = _collect_truncate_targets()
    if not table_names:
        return None
    return "TRUNCATE TABLE {} RESTART IDENTITY CASCADE".format(", ".join(table_names))


async def _truncate_all_tables(async_engine: AsyncEngine) -> None:
    """TRUNCATE helper for cleaning up between AsyncSession tests."""

    statement = _build_truncate_statement()
    if not statement:
        return

    async with async_engine.begin() as connection:
        await connection.execute(text(statement))


@pytest.fixture(scope="session")
def engine() -> Generator:
    """Session-wide PostgreSQL engine bound to the test schema."""

    drop_schema(force=True)
    create_schema()

    engine = create_engine(
        settings.database_url,
        poolclass=NullPool,
        future=True,
        connect_args={"options": f"-csearch_path={TEST_SCHEMA},public"},
    )

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        drop_schema(force=True)


@pytest.fixture(scope="session")
def async_engine(engine) -> AsyncEngine:
    """Session-wide async engine shared by async dependencies and test cases.

    This fixture depends on the sync ``engine`` fixture to initialize the schema,
    ensuring async-only tests can run against a ready-to-use test schema.
    """

    async_engine = create_async_engine(
        settings.async_database_url,
        poolclass=NullPool,
        echo=settings.database_echo,
        connect_args={
            "server_settings": {
                "search_path": f"{TEST_SCHEMA},public",
            }
        },
    )
    # The sync engine fixture manages schema lifecycle; we only return async engine.
    yield async_engine
    asyncio.run(async_engine.dispose())


@pytest.fixture(scope="session")
def async_session_maker(
    async_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Shared async sessionmaker for tests and dependency injection."""

    return async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest_asyncio.fixture()
async def async_db_session(
    async_session_maker: async_sessionmaker[AsyncSession],
    async_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Async test DB session sharing the same schema with sync tests."""

    async with async_session_maker() as session:
        try:
            yield session
        finally:
            try:
                await session.rollback()
            except Exception:
                pass
            await session.close()
            await _truncate_all_tables(async_engine)


@pytest.fixture(autouse=True)
def reset_a2a_proxy_service_state() -> None:
    """Reset process-local proxy allowlist cache between tests."""

    A2AProxyService._cached_allowed_hosts = []
    A2AProxyService._last_refresh = 0
    A2AProxyService._ttl = 60
    A2AProxyService._is_initialized = False
    A2AProxyService._refresh_lock = None
    A2AProxyService._refresh_lock_loop = None
