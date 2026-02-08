from __future__ import annotations

import asyncio
import importlib
import os
import sys
import types
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Generator
from uuid import uuid4

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
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


def _ensure_card_box_core_stub() -> None:
    """Install lightweight card_box_core modules when dependency is absent."""

    if "card_box_core" in sys.modules:
        return

    card_box_core = types.ModuleType("card_box_core")

    structures = types.ModuleType("card_box_core.structures")

    class Card:
        def __init__(self, content: Any = None, metadata: dict | None = None) -> None:
            self.card_id = str(uuid4())
            self.content = content
            self.metadata = metadata or {}

    class TextContent:
        def __init__(self, text: str = "") -> None:
            self.text = text

    class CardBox:
        def __init__(self) -> None:
            self.card_ids: list[str] = []

        def add(self, card_id: str) -> None:
            self.card_ids.append(card_id)

    structures.Card = Card
    structures.TextContent = TextContent
    structures.CardBox = CardBox

    adapters = types.ModuleType("card_box_core.adapters")

    class StorageAdapter:
        def load_card_box(self, name: str, tenant_id: str) -> CardBox | None:
            return getattr(self, "_boxes", {}).get((tenant_id, name))

        def save_card_box(self, box: CardBox, *, name: str, tenant_id: str) -> None:
            self._boxes.setdefault((tenant_id, name), box)

    @dataclass
    class DuckDBStorageAdapterSettings:
        path: str

    class DuckDBStorageAdapter(StorageAdapter):
        def __init__(self, *, config: DuckDBStorageAdapterSettings) -> None:
            self.config = config
            self._boxes: dict[tuple[str, str], CardBox] = {}

    class LocalFileStorageAdapter:
        pass

    adapters.StorageAdapter = StorageAdapter
    adapters.DuckDBStorageAdapter = DuckDBStorageAdapter
    adapters.LocalFileStorageAdapter = LocalFileStorageAdapter

    config_mod = types.ModuleType("card_box_core.config")

    def configure(config_dict: dict[str, Any]) -> None:
        config_mod._last_config = config_dict

    config_mod.DuckDBStorageAdapterSettings = DuckDBStorageAdapterSettings
    config_mod.configure = configure

    engine_mod = types.ModuleType("card_box_core.engine")

    class _CardStore:
        def __init__(self) -> None:
            self._cards: dict[str, Card] = {}

        def add(self, card: Card) -> None:
            self._cards[card.card_id] = card

        def get(self, card_id: str) -> Card | None:
            return self._cards.get(card_id)

    class ContextEngine:
        def __init__(
            self,
            *,
            trace_id: str,
            tenant_id: str,
            storage_adapter: StorageAdapter,
            history_level: str,
            fs_adapter: Any,
        ) -> None:
            self.trace_id = trace_id
            self.tenant_id = tenant_id
            self.storage_adapter = storage_adapter
            self.history_level = history_level
            self.fs_adapter = fs_adapter
            self.card_store = _CardStore()

    engine_mod.ContextEngine = ContextEngine

    card_box_core.structures = structures
    card_box_core.adapters = adapters
    card_box_core.config = config_mod
    card_box_core.engine = engine_mod

    sys.modules["card_box_core"] = card_box_core
    sys.modules["card_box_core.structures"] = structures
    sys.modules["card_box_core.adapters"] = adapters
    sys.modules["card_box_core.config"] = config_mod
    sys.modules["card_box_core.engine"] = engine_mod


_ensure_card_box_core_stub()

TEST_SCHEMA_NAME = os.getenv("TEST_SCHEMA_NAME", "test_common_compass_schema")
os.environ["SCHEMA_NAME"] = TEST_SCHEMA_NAME

# Ensure JWT RS256 configuration is available for tests.
if "JWT_PRIVATE_KEY_PEM" not in os.environ or "JWT_PUBLIC_KEY_PEM" not in os.environ:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    os.environ.setdefault("JWT_ALGORITHM", "RS256")
    os.environ["JWT_PRIVATE_KEY_PEM"] = private_pem
    os.environ["JWT_PUBLIC_KEY_PEM"] = public_pem
    os.environ.setdefault("JWT_ISSUER", "common-compass-test")
    os.environ.setdefault("JWT_ACCESS_TOKEN_TTL_SECONDS", "1800")
    os.environ.setdefault("JWT_REFRESH_TOKEN_TTL_SECONDS", "1209600")
    os.environ.setdefault("AUTH_REFRESH_COOKIE_SECURE", "false")


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers to silence PytestUnknownMarkWarning."""

    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests",
    )


SCRIPT_ROOT = os.path.join(os.path.dirname(PROJECT_ROOT), "scripts")
if SCRIPT_ROOT not in sys.path:
    sys.path.insert(0, SCRIPT_ROOT)

from setup_db_schema import create_schema, drop_schema

from app.core.config import settings
from app.db.models.base import Base

# Import the minimal set of models required for tests. Importing user_preferences
# pulls preference validators which depend on other models, so we import them up
# front to ensure metadata is populated before running schema setup.
for module_path in [
    "app.db.models.agent_session",
    "app.db.models.agent_audit_log",
    "app.db.models.a2a_agent",
    "app.db.models.a2a_schedule_task",
    "app.db.models.a2a_schedule_execution",
    "app.db.models.user",
    "app.db.models.user_preference",
    "app.db.models.dimension",
    "app.db.models.vision",
    "app.db.models.task",
    "app.db.models.invitation",
    "app.db.models.finance_trading",
    "app.db.models.ws_ticket",
]:
    importlib.import_module(module_path)

TEST_SCHEMA = settings.schema_name


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
