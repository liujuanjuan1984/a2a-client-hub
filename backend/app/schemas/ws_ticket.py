"""Schemas for WebSocket ticket issuance."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WsTicketResponse(BaseModel):
    token: str = Field(..., description="One-time WS ticket")
    expires_at: datetime = Field(..., description="Ticket expiration timestamp (UTC)")
    expires_in: int = Field(..., description="Seconds until ticket expiration")

    model_config = {
        "json_schema_extra": {
            "example": {
                "token": "ws_ticket_example",
                "expires_at": "2026-02-01T00:00:00Z",
                "expires_in": 90,
            }
        }
    }


__all__ = ["WsTicketResponse"]
