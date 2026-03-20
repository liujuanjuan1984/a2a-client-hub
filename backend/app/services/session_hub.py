"""Compatibility shim for the legacy session hub service path."""

import sys

from app.features.sessions import service as _service_module

sys.modules[__name__] = _service_module
