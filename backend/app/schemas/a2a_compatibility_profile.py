"""Schemas shared by compatibility-profile diagnostics and capability responses."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class A2ACompatibilityProfileDiagnostic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    declared: bool = Field(
        ...,
        description="Whether the card declares a compatibility-profile extension",
    )
    status: Literal["supported", "unsupported", "invalid"] = Field(
        ...,
        description="Hub compatibility classification for the declared profile",
    )
    uri: Optional[str] = None
    advisory_only: bool = Field(
        default=True,
        alias="advisoryOnly",
        description="Compatibility-profile is treated as advisory metadata only.",
    )
    used_for: List[str] = Field(
        default_factory=lambda: ["diagnostics", "retention_hints"],
        alias="usedFor",
        description="How the Hub currently uses the declared advisory profile.",
    )
    extension_retention_count: int = Field(
        default=0,
        alias="extensionRetentionCount",
        description="Number of declared extension retention hints.",
    )
    method_retention_count: int = Field(
        default=0,
        alias="methodRetentionCount",
        description="Number of declared method retention hints.",
    )
    service_behavior_keys: List[str] = Field(
        default_factory=list,
        alias="serviceBehaviorKeys",
        description="Top-level advisory service-behavior keys declared upstream.",
    )
    consumer_guidance: List[str] = Field(
        default_factory=list,
        alias="consumerGuidance",
    )
    error: Optional[str] = Field(
        default=None,
        description="Structured validation error when the contract is invalid",
    )
