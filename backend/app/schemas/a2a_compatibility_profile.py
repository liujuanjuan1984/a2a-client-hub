"""Schemas shared by compatibility-profile diagnostics and capability responses."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class A2ACompatibilityProfileEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    surface: str
    availability: str
    retention: str
    extension_uri: Optional[str] = Field(default=None, alias="extensionUri")
    toggle: Optional[str] = None
    implementation_scope: Optional[str] = Field(
        default=None, alias="implementationScope"
    )
    identity_scope: Optional[str] = Field(default=None, alias="identityScope")
    upstream_stability: Optional[str] = Field(default=None, alias="upstreamStability")


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
    extension_retention: Dict[str, A2ACompatibilityProfileEntry] = Field(
        default_factory=dict,
        alias="extensionRetention",
    )
    method_retention: Dict[str, A2ACompatibilityProfileEntry] = Field(
        default_factory=dict,
        alias="methodRetention",
    )
    service_behaviors: Dict[str, Any] = Field(
        default_factory=dict,
        alias="serviceBehaviors",
    )
    consumer_guidance: List[str] = Field(
        default_factory=list,
        alias="consumerGuidance",
    )
    error: Optional[str] = Field(
        default=None,
        description="Structured validation error when the contract is invalid",
    )
