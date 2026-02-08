"""Utilities and helpers for embedding Cardbox inside the Compass backend."""

from app.cardbox.data_sync import CardBoxDataSyncService, cardbox_data_sync_service
from app.cardbox.engine_factory import create_engine
from app.cardbox.init_duckdb_schema import (
    ensure_schema_exists,
    initialize_schema,
    initialize_schema_for_all_existing_users,
    initialize_schema_for_multiple_users,
)
from app.cardbox.service import CardBoxService, cardbox_service

__all__ = [
    "create_engine",
    "CardBoxService",
    "cardbox_service",
    "CardBoxDataSyncService",
    "cardbox_data_sync_service",
    "initialize_schema",
    "ensure_schema_exists",
    "initialize_schema_for_multiple_users",
    "initialize_schema_for_all_existing_users",
]
