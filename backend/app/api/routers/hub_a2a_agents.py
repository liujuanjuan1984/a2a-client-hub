"""Compatibility shim for the hub A2A agent user router module."""

import sys

from app.features.hub_agents import router as _router_module

sys.modules[__name__] = _router_module
