"""Patch-target exports for session history internals."""

from __future__ import annotations

from app.features.sessions import block_store, message_store

_PATCH_TARGETS = (block_store, message_store)
