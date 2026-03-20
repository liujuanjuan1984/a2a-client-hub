"""Compatibility alias for shared extension capability router helpers."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.features.extension_capabilities.common_router import *  # noqa: F403
else:
    import sys

    from app.features.extension_capabilities import common_router as _module

    sys.modules[__name__] = _module
