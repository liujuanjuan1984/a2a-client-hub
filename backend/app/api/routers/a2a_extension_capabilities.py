"""Compatibility shim for the personal extension capabilities router module."""

import sys

from app.features.extension_capabilities import personal_router as _router_module

sys.modules[__name__] = _router_module
