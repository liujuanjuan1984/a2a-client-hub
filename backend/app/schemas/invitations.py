"""Compatibility shim for the legacy invitation schema path."""

import sys

from app.features.invitations import schemas as _schemas_module

sys.modules[__name__] = _schemas_module
