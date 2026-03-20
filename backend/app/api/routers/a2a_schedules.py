"""Compatibility shim for the A2A schedule router module."""

import sys

from app.features.schedules import router as _router_module

sys.modules[__name__] = _router_module
