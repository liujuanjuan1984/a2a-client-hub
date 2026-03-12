"""Canonical shared A2A extension contract constants."""

from __future__ import annotations

SHARED_SESSION_BINDING_URI = "urn:shared-a2a:session-binding:v1"
SHARED_SESSION_QUERY_URI = "urn:shared-a2a:session-query:v1"
SHARED_INTERRUPT_CALLBACK_URI = "urn:shared-a2a:interrupt-callback:v1"

CANONICAL_PROVIDER_KEY = "provider"
CANONICAL_EXTERNAL_SESSION_ID_KEY = "externalSessionId"
CANONICAL_INTERRUPT_KEY = "interrupt"

__all__ = [
    "CANONICAL_EXTERNAL_SESSION_ID_KEY",
    "CANONICAL_INTERRUPT_KEY",
    "CANONICAL_PROVIDER_KEY",
    "SHARED_INTERRUPT_CALLBACK_URI",
    "SHARED_SESSION_BINDING_URI",
    "SHARED_SESSION_QUERY_URI",
]
