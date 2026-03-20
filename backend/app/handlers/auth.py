"""Compatibility shim for the legacy authentication handler path."""

import sys

from app.features.auth import service as _service_module

sys.modules[__name__] = _service_module
