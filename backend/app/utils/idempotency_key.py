"""Idempotency key normalization helpers."""

from __future__ import annotations

import hashlib

from app.utils.session_identity import normalize_non_empty_text

IDEMPOTENCY_KEY_MAX_LENGTH = 160
_IDEMPOTENCY_HASH_SEPARATOR = ":h:"


def normalize_idempotency_key(value: object) -> str | None:
    normalized = normalize_non_empty_text(value)
    if normalized is None:
        return None
    if len(normalized) <= IDEMPOTENCY_KEY_MAX_LENGTH:
        return normalized
    digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()
    prefix_length = (
        IDEMPOTENCY_KEY_MAX_LENGTH - len(_IDEMPOTENCY_HASH_SEPARATOR) - len(digest)
    )
    prefix = normalized[: max(prefix_length, 0)]
    return f"{prefix}{_IDEMPOTENCY_HASH_SEPARATOR}{digest}"


__all__ = ["IDEMPOTENCY_KEY_MAX_LENGTH", "normalize_idempotency_key"]
