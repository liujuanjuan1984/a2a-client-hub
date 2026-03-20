"""Compatibility shim for the legacy authentication schema path."""

import sys

from app.features.auth import schemas as _schemas_module

sys.modules[__name__] = _schemas_module
