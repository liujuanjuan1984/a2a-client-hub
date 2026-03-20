"""Compatibility alias for the legacy A2A invoke service path."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.features.invoke.service import *  # noqa: F403
else:
    import sys

    from app.features.invoke import service as _module

    sys.modules[__name__] = _module
