"""Compatibility alias for the legacy OpenCode session directory service path."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.features.opencode_sessions.service import *  # noqa: F403
else:
    import sys

    from app.features.opencode_sessions import service as _module

    sys.modules[__name__] = _module
