"""Compatibility alias for the legacy A2A stream payload helpers path."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.features.invoke.stream_payloads import *  # noqa: F403
else:
    import sys

    from app.features.invoke import stream_payloads as _module

    sys.modules[__name__] = _module
