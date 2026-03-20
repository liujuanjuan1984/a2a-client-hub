"""Compatibility alias for the legacy invoke route runner path."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.features.invoke.route_runner import *  # noqa: F403
else:
    import sys

    from app.features.invoke import route_runner as _module

    sys.modules[__name__] = _module
