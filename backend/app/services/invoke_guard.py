"""Compatibility alias for the legacy invoke guard path."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.features.invoke.guard import *  # noqa: F403
else:
    import sys

    from app.features.invoke import guard as _module

    sys.modules[__name__] = _module
