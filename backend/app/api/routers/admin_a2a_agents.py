"""Compatibility shim for the hub A2A agent admin router module."""

import sys

from app.features.hub_agents import admin_router as _router_module

sys.modules[__name__] = _router_module
