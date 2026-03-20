"""Compatibility alias for the legacy invoke stream persistence path."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.features.invoke.stream_persistence import *  # noqa: F403
else:
    import sys

    from app.features.invoke import stream_persistence as _module

    sys.modules[__name__] = _module
