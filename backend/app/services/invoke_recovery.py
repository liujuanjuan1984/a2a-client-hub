"""Compatibility alias for the legacy invoke recovery path."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.features.invoke.recovery import *  # noqa: F403
else:
    import sys

    from app.features.invoke import recovery as _module

    sys.modules[__name__] = _module
