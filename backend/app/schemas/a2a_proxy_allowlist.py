from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class A2AProxyAllowlistBase(BaseModel):
    host_pattern: str = Field(
        ..., description="The host pattern allowed (e.g., example.com, *.openai.com)"
    )
    is_enabled: bool = Field(True, description="Whether this allowlist entry is active")
    remark: Optional[str] = Field(
        None, description="Remark or reason for this allowlist entry"
    )


class A2AProxyAllowlistCreate(A2AProxyAllowlistBase):
    pass


class A2AProxyAllowlistUpdate(BaseModel):
    host_pattern: Optional[str] = None
    is_enabled: Optional[bool] = None
    remark: Optional[str] = None


class A2AProxyAllowlistResponse(A2AProxyAllowlistBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
