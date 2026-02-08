"""Input validation and telemetry helpers for the A2A integration."""

from __future__ import annotations

import hashlib
from typing import Any, Dict


def summarize_query(query: str, *, hash_prefix_len: int = 8) -> Dict[str, Any]:
    """Return a redacted representation of the user query for logging."""

    text = query or ""
    summary: Dict[str, Any] = {"length": len(text)}
    normalized = text.strip()
    if normalized:
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        summary["sha256_prefix"] = digest[:hash_prefix_len]
    return summary
