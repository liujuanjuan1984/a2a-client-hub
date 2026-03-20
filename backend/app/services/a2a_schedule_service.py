"""Compatibility shim for the legacy A2A schedule service path."""

import sys

from app.features.schedules import service as _service_module

sys.modules[__name__] = _service_module
