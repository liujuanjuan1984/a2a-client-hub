"""Protocol adapter implementations for A2A peers."""

from app.integrations.a2a_client.adapters import (
    base,
    jsonrpc_pascal,
    jsonrpc_slash,
    sdk,
)

A2AAdapter = base.A2AAdapter
JSONRPC_PASCAL_DIALECT = jsonrpc_pascal.JSONRPC_PASCAL_DIALECT
JsonRpcPascalAdapter = jsonrpc_pascal.JsonRpcPascalAdapter
JSONRPC_SLASH_DIALECT = jsonrpc_slash.JSONRPC_SLASH_DIALECT
JsonRpcSlashAdapter = jsonrpc_slash.JsonRpcSlashAdapter
SDK_DIALECT = sdk.SDK_DIALECT
SDKA2AAdapter = sdk.SDKA2AAdapter
