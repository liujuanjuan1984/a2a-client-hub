"""Compatibility alias for the legacy invoke session binding path."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.features.invoke.session_binding import *  # noqa: F403
else:
    import sys

    from app.features.invoke import session_binding as _module

    sys.modules[__name__] = _module
