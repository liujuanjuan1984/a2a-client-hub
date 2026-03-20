"""Compatibility shim for the legacy session domain schema path."""

import sys

from app.features.sessions import schemas as _schemas_module

sys.modules[__name__] = _schemas_module
