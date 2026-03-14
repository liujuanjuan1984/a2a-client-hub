"""Protocol adapter implementations for A2A peers."""

from app.integrations.a2a_client.adapters.base import A2AAdapter
from app.integrations.a2a_client.adapters.jsonrpc_pascal import (
    JSONRPC_PASCAL_DIALECT,
    JsonRpcPascalAdapter,
)
from app.integrations.a2a_client.adapters.jsonrpc_slash import (
    JSONRPC_SLASH_DIALECT,
    JsonRpcSlashAdapter,
)
from app.integrations.a2a_client.adapters.sdk import (
    SDK_DIALECT,
    SDKA2AAdapter,
)

__all__ = [
    "A2AAdapter",
    "JSONRPC_PASCAL_DIALECT",
    "JSONRPC_SLASH_DIALECT",
    "JsonRpcPascalAdapter",
    "JsonRpcSlashAdapter",
    "SDKA2AAdapter",
    "SDK_DIALECT",
]
