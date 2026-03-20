"""Compatibility shim for the legacy shortcut service path."""

import sys

from app.features.shortcuts import service as _service_module

sys.modules[__name__] = _service_module
