"""Compatibility shim for the OpenCode session directory router module."""

import sys

from app.features.opencode_sessions import router as _router_module

sys.modules[__name__] = _router_module
