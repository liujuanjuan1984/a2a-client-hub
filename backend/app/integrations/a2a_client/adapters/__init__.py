"""Protocol adapter implementations for A2A peers."""

from app.integrations.a2a_client.adapters import (
    base,
    sdk,
)

A2AAdapter = base.A2AAdapter
SDK_DIALECT = sdk.SDK_DIALECT
SDKA2AAdapter = sdk.SDKA2AAdapter
