"""Compatibility shim for the hub extension capabilities router module."""

import sys

from app.features.extension_capabilities import hub_router as _router_module

sys.modules[__name__] = _router_module
