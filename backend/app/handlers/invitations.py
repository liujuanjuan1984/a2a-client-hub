"""Compatibility shim for the legacy invitation handler path."""

import sys

from app.features.invitations import service as _service_module

sys.modules[__name__] = _service_module
