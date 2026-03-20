"""Compatibility shim for the authentication router module."""

import sys

from app.features.auth import router as _router_module

sys.modules[__name__] = _router_module
