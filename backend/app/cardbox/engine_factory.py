"""Factories for creating configured Cardbox engines."""

from functools import lru_cache
from typing import Optional
from uuid import uuid4

from card_box_core.adapters import (
    DuckDBStorageAdapter,
    LocalFileStorageAdapter,
    StorageAdapter,
)
from card_box_core.config import DuckDBStorageAdapterSettings
from card_box_core.engine import ContextEngine

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=8)
def _get_storage_adapter(config_hash: str) -> StorageAdapter:
    """Return a storage adapter instance for a specific configuration.

    The instance is cached per config_hash to ensure that:
    - We use the configured persistent database when a path is provided
    - Changing the configuration (e.g. via CLI --db-path) yields a new adapter

    Note: DuckDBStorageAdapter uses the path from card_box_core.config.configure()
    """

    logger.info(f"Creating DuckDBStorageAdapter with config_hash: {config_hash}")

    # Create DuckDBStorageAdapterSettings with the configured path
    db_path = settings.card_box_duckdb_path
    config = DuckDBStorageAdapterSettings(path=db_path)
    logger.info(f"DuckDBStorageAdapter config: path={config.path}")
    return DuckDBStorageAdapter(config=config)


def create_engine(tenant_id: str, trace_id: Optional[str] = None) -> ContextEngine:
    """Create a ``ContextEngine`` configured for the given tenant.

    Parameters
    ----------
    tenant_id:
        Logical grouping identifier. In Compass we typically derive this from
        the user id so every user owns an isolated Cardbox namespace.
    trace_id:
        Optional correlation id used when running transformations. If omitted a
        random UUID will be generated, ensuring every engine invocation remains
        traceable.
    """

    db_path = settings.card_box_duckdb_path
    logger.info(
        f"Creating ContextEngine for tenant={tenant_id}, trace_id={trace_id or 'auto'}"
    )

    # Create a config hash to ensure adapter cache respects configuration changes
    config_hash = (
        f"{db_path}_{settings.card_box_history_level}_{settings.card_box_verbose_logs}"
    )
    storage = _get_storage_adapter(config_hash)
    engine_trace_id = trace_id or str(uuid4())

    return ContextEngine(
        trace_id=engine_trace_id,
        tenant_id=tenant_id,
        storage_adapter=storage,
        history_level=settings.card_box_history_level,
        fs_adapter=LocalFileStorageAdapter(),
    )


__all__ = ["create_engine"]
