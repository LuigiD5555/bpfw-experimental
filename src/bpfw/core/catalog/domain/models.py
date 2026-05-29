"""Pydantic domain models for blueprint authority."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_LIFECYCLES = {"active", "experimental", "legacy", "deprecated"}


class ResponsibilityLocation(BaseModel):
    """Represent source location metadata for one responsibility."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    path: str = ""
    symbol: str = ""
    symbol_type: str = Field(default="", alias="kind")


class DetectedMetadata(BaseModel):
    """Represent detected metadata from scanner-derived evidence."""

    model_config = ConfigDict(extra="allow")

    docstring: str | None = None
    signature: str | None = None
    called_symbols: list[str] = Field(default_factory=list)


class Connection(BaseModel):
    """Represent a responsibility relation entry."""

    model_config = ConfigDict(extra="allow")

    target: str = ""
    meaning: str | None = None


class Policy(BaseModel):
    """Represent policy section used by planner/verify."""

    model_config = ConfigDict(extra="allow")

    allowed_statuses: list[str] = Field(
        default_factory=lambda: ["active", "experimental", "legacy", "deprecated"]
    )
    one_active_block_per_purpose: bool = True


class Responsibility(BaseModel):
    """Represent one blueprint responsibility block."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    identifier: str = Field(default="", alias="id")
    purpose: str | None = None
    domain: str | None = None
    name: str | None = None
    lifecycle: str = Field(default="active", alias="status")
    location: ResponsibilityLocation = Field(default_factory=ResponsibilityLocation, alias="code")
    detected: DetectedMetadata | None = None
    uniqueness: dict[str, Any] = Field(default_factory=dict)
    connections: list[Connection] = Field(default_factory=list)

    @field_validator("purpose", mode="before")
    @classmethod
    def _normalize_purpose(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = " ".join(value.strip().lower().split())
            return normalized or None
        return value

    @field_validator("domain", mode="before")
    @classmethod
    def _normalize_domain(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = " ".join(value.strip().lower().split())
            return normalized or None
        return value

    @field_validator("lifecycle", mode="before")
    @classmethod
    def _normalize_lifecycle(cls, value: Any) -> str:
        if not isinstance(value, str):
            return "active"
        normalized = " ".join(value.strip().lower().split()) or "active"
        return normalized

    @property
    def is_valid_lifecycle(self) -> bool:
        return self.lifecycle in ALLOWED_LIFECYCLES


class BlueprintDocument(BaseModel):
    """Represent complete authority document consumed by integrations."""

    model_config = ConfigDict(extra="allow")

    version: int | None = None
    project: dict[str, Any] = Field(default_factory=dict)
    policy: Policy = Field(default_factory=Policy)
    authority: dict[str, Any] = Field(default_factory=dict)
    includes: list[str] = Field(default_factory=list)
    blocks: list[Responsibility] = Field(default_factory=list)


__all__ = [
    "ALLOWED_LIFECYCLES",
    "BlueprintDocument",
    "Connection",
    "DetectedMetadata",
    "Policy",
    "Responsibility",
    "ResponsibilityLocation",
]
