"""Compatibility shim for the legacy shortcut schema path."""

import sys

from app.features.shortcuts import schemas as _schemas_module

sys.modules[__name__] = _schemas_module
