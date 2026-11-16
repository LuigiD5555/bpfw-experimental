"""Pydantic domain models for BPFW blueprint authority."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_LIFECYCLES = {"active", "experimental", "legacy", "deprecated"}
DEFAULT_COMPONENT_KIND = "code"


class ResponsibilityLocation(BaseModel):
    """Represent legacy/source location metadata for one responsibility."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    path: str = ""
    symbol: str = ""
    symbol_type: str = Field(default="", alias="kind")


class Artifact(BaseModel):
    """Physical evidence implementing, governing, or verifying a logical component.

    Alpha.13 makes artifacts first-class and addressable.  Human-maintained fields
    identify the artifact semantically; volatile source spans and hashes live in
    BPFW history/state and are derived by ArtifactResolver.
    """

    model_config = ConfigDict(extra="allow")

    uid: str | None = None
    identifier: str | None = Field(default=None, alias="id")
    profile: str | None = None
    type: str = "code"
    path: str = ""
    language: str | None = None
    format: str | None = None
    symbol: str | None = None
    kind: str | None = None
    role: str | None = None
    primary: bool = False
    required: bool = True
    selector: dict[str, Any] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)


class Intent(BaseModel):
    """Persistent semantic intention for a component."""

    model_config = ConfigDict(extra="allow")

    summary: str | None = None
    guarantees: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class Invariant(BaseModel):
    """Machine-verifiable property that should remain true."""

    model_config = ConfigDict(extra="allow")

    uid: str | None = None
    identifier: str = Field(default="", alias="id")
    description: str = ""
    severity: str = "warning"
    type: str = "custom_evidence"
    subject: str | None = None
    assertion: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class DetectedMetadata(BaseModel):
    """Represent detected metadata from scanner-derived evidence."""

    model_config = ConfigDict(extra="allow")

    docstring: str | None = None
    signature: str | None = None
    called_symbols: list[str] = Field(default_factory=list)


class Connection(BaseModel):
    """Represent a typed system relation entry with provenance."""

    model_config = ConfigDict(extra="allow")

    uid: str | None = None
    target: str = ""
    meaning: str | None = None
    relationship: str = "depends_on"
    provenance: str = "declared"
    properties: dict[str, Any] = Field(default_factory=dict)


class Policy(BaseModel):
    """Represent policy section used by planner/verify."""

    model_config = ConfigDict(extra="allow")

    allowed_statuses: list[str] = Field(
        default_factory=lambda: ["active", "experimental", "legacy", "deprecated"]
    )
    one_active_block_per_purpose: bool | None = None
    duplicate_detection: dict[str, Any] = Field(default_factory=lambda: {"block_active_duplicate_profiles": True})
    max_retry_amplification: int | None = None


class Responsibility(BaseModel):
    """Represent one logical blueprint component."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    uid: str | None = None
    identifier: str = Field(default="", alias="id")
    kind: str = DEFAULT_COMPONENT_KIND
    purpose: str | None = None
    domain: str | None = None
    name: str | None = None
    intent: Intent | None = None
    invariants: list[Invariant] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    failure_behavior: dict[str, Any] = Field(default_factory=dict)
    analysis: dict[str, Any] = Field(default_factory=dict)
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

    @field_validator("kind", mode="before")
    @classmethod
    def _normalize_kind(cls, value: Any) -> str:
        if not isinstance(value, str):
            return DEFAULT_COMPONENT_KIND
        return value.strip().lower() or DEFAULT_COMPONENT_KIND

    @field_validator("lifecycle", mode="before")
    @classmethod
    def _normalize_lifecycle(cls, value: Any) -> str:
        if not isinstance(value, str):
            return "active"
        return " ".join(value.strip().lower().split()) or "active"

    @property
    def is_valid_lifecycle(self) -> bool:
        return self.lifecycle in ALLOWED_LIFECYCLES

    def all_artifacts(self) -> list[Artifact]:
        """Return v2 artifacts plus a synthetic artifact for legacy code metadata."""
        values = list(self.artifacts)
        legacy_is_physical = self.kind == "code" or self.location.symbol_type not in {"concept", "subsystem", "flow", "logical"}
        if self.location.path and legacy_is_physical:
            legacy = Artifact(
                identifier="legacy_code",
                type="code",
                path=self.location.path,
                language=getattr(self.location, "language", None),
                symbol=self.location.symbol or None,
                kind=self.location.symbol_type or None,
                role="legacy_code_location",
                primary=not bool(values),
            )
            if not any(a.type == legacy.type and a.path == legacy.path and a.symbol == legacy.symbol for a in values):
                values.insert(0, legacy)
        return values


class BlueprintDocument(BaseModel):
    """Represent complete authority document consumed by integrations."""

    model_config = ConfigDict(extra="allow")

    version: int | None = None
    project: dict[str, Any] = Field(default_factory=dict)
    policy: Policy = Field(default_factory=Policy)
    authority: dict[str, Any] = Field(default_factory=dict)
    includes: list[str] = Field(default_factory=list)
    blocks: list[Responsibility] = Field(default_factory=list)
    scenarios: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "ALLOWED_LIFECYCLES",
    "Artifact",
    "BlueprintDocument",
    "Connection",
    "DetectedMetadata",
    "Intent",
    "Invariant",
    "Policy",
    "Responsibility",
    "ResponsibilityLocation",
]
