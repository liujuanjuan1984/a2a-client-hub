"""Compatibility shim for the personal A2A agent router module."""

import sys

from app.features.personal_agents import router as _router_module

sys.modules[__name__] = _router_module
