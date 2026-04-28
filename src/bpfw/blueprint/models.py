"""Domain models for executable Blueprint authority."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class BlueprintImplementation:
    """Implementation option declared for one responsibility."""

    implementation_id: str
    class_name: str
    file: str
    lifecycle_state: str
    replacement_id: str | None = None
    disabled_reason: str | None = None
    removal_plan: str | None = None


@dataclass(slots=True)
class BlueprintResponsibility:
    """Responsibility contract declared in blueprint.yaml."""

    responsibility_id: str
    canonical_name: str
    owner_layer: str
    lifecycle_state: str
    allowed_files: list[str]
    allowed_symbols: list[str] = field(default_factory=list)
    allowed_implementations: list[BlueprintImplementation] = field(default_factory=list)
    active_implementation: str = ""
    forbidden_duplicates: list[str] = field(default_factory=list)
    mutability: str = "editable"
    owner: str = ""


@dataclass(slots=True)
class LockedResource:
    """Immutable/controlled resource declared in blueprint."""

    resource_id: str
    path: str
    mutability: str
    owner: str


@dataclass(slots=True)
class BlueprintModel:
    """Typed blueprint root model."""

    version: int
    responsibilities: list[BlueprintResponsibility]
    locked_resources: list[LockedResource] = field(default_factory=list)
    source_path: Path | None = None


@dataclass(slots=True)
class BlueprintValidationError:
    """Single deterministic validation error with evidence."""

    code: str
    message: str
    file_path: str
    recommendation: str


@dataclass(slots=True)
class BlueprintValidationResult:
    """Validation output consumed by engine steps."""

    is_valid: bool
    errors: list[BlueprintValidationError] = field(default_factory=list)
    blueprint: BlueprintModel | None = None
