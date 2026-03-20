"""Compatibility shim for the invitation router module."""

import sys

from app.features.invitations import router as _router_module

sys.modules[__name__] = _router_module
