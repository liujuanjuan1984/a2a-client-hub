"""Compatibility shim for the unified session router module."""

import sys

from app.features.sessions import router as _router_module

sys.modules[__name__] = _router_module
