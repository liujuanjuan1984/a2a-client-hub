"""Compatibility shim for the shortcut router module."""

import sys

from app.features.shortcuts import router as _router_module

sys.modules[__name__] = _router_module
