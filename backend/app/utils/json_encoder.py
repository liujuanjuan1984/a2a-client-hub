"""
Custom JSON encoder for handling non-serializable objects.

This module provides a custom JSON encoder that automatically handles
UUID objects, datetime objects, and other common non-serializable types.
"""

import json
import logging
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from google.protobuf.message import Message as ProtoMessage

from app.integrations.a2a_client.protobuf import to_protojson_like

logger = logging.getLogger(__name__)


class CompassJSONEncoder(json.JSONEncoder):
    """
    Custom JSON encoder that handles common non-serializable objects.

    Automatically converts:
    - UUID objects to strings
    - datetime objects to ISO format strings
    - date objects to ISO format strings
    - time objects to ISO format strings
    - Decimal objects to floats
    """

    def default(self, obj: Any) -> Any:
        """Convert non-serializable objects to serializable ones."""
        if isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, date):
            return obj.isoformat()
        elif isinstance(obj, time):
            return obj.isoformat()
        elif isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, ProtoMessage):
            return to_protojson_like(obj)

        normalized = to_protojson_like(obj)
        if normalized is not obj:
            return normalized

        # Fall back to the default behavior
        return super().default(obj)


def json_dumps(obj: Any, **kwargs: Any) -> str:
    """
    Convenience function for JSON serialization with custom encoder.

    Args:
        obj: Object to serialize
        **kwargs: Additional arguments passed to json.dumps

    Returns:
        JSON string
    """
    # Set default encoder if not specified
    if "cls" not in kwargs:
        kwargs["cls"] = CompassJSONEncoder

    return json.dumps(obj, **kwargs)
