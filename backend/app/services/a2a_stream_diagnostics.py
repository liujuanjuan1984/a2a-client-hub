"""Compatibility alias for the legacy A2A stream diagnostics path."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.features.invoke.stream_diagnostics import *  # noqa: F403
else:
    import sys

    from app.features.invoke import stream_diagnostics as _module

    sys.modules[__name__] = _module
