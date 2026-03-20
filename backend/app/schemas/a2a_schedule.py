"""Compatibility shim for the legacy A2A schedule schema path."""

import sys

from app.features.schedules import schemas as _schemas_module

sys.modules[__name__] = _schemas_module
