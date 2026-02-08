"""Core constants for the A2A client backend cut.

The original Common Compass backend defines a large amount of preference
defaults for many modules. This repository intentionally keeps only the
defaults required by the A2A client mobile surface.
"""

from __future__ import annotations

from typing import Any, Dict

# When a user requests a preference that doesn't exist, the backend will
# auto-create it only if there is an entry here.
USER_PREFERENCE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "system.timezone": {
        "value": "UTC",
        "module": "system",
        "description": "Preferred timezone in IANA format (e.g. 'America/Los_Angeles')",
        "allowed_values": None,
        "validator": "timezone_validator",
    },
}
