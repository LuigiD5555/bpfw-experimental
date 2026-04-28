"""Contracts for Blueprint Mode opt-in validation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class BlueprintModeSideEffects:
    """Declared side-effect constraints for an operation."""

    allowed: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BlueprintModeOperation:
    """One declared operation contract in blueprint_mode."""

    operation_id: str
    callable: str
    input_contract: dict[str, str] = field(default_factory=dict)
    output_contract: dict[str, str] = field(default_factory=dict)
    allowed_errors: list[str] = field(default_factory=list)
    side_effects: BlueprintModeSideEffects = field(default_factory=BlueprintModeSideEffects)


@dataclass(slots=True)
class BlueprintModeConfig:
    """Blueprint mode section parsed from blueprint YAML."""

    enabled: bool = False
    operations: list[BlueprintModeOperation] = field(default_factory=list)


@dataclass(slots=True)
class BlueprintModeIssue:
    """Validation issue for blueprint mode declarations."""

    severity: str
    code: str
    message: str
    file_path: str
    recommendation: str


@dataclass(slots=True)
class BlueprintModeValidationResult:
    """Validation output for blueprint mode structure and contracts."""

    config: BlueprintModeConfig = field(default_factory=BlueprintModeConfig)
    issues: list[BlueprintModeIssue] = field(default_factory=list)
