"""Execution context models for BPFW pipelines."""

from dataclasses import dataclass, field
from pathlib import Path

from bpfw.blueprint.schema import CANONICAL_BLUEPRINT_FILE


@dataclass(slots=True)
class EngineCommand:
    """User command normalized for deterministic engine execution."""

    command_name: str
    project_root: Path
    arguments: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ProjectContext:
    """Runtime context shared across pipeline steps."""

    project_root: Path
    blueprint_file: Path
    architecture_file: Path
    lifecycle_file: Path
    command_arguments: dict[str, str] = field(default_factory=dict)


def build_project_context(project_root: Path, command_arguments: dict[str, str] | None = None) -> ProjectContext:
    """Build a minimal project context used by engine pipelines."""

    return ProjectContext(
        project_root=project_root,
        blueprint_file=project_root / CANONICAL_BLUEPRINT_FILE,
        architecture_file=project_root / "architecture.yaml",
        lifecycle_file=project_root / "lifecycle.yaml",
        command_arguments=command_arguments or {},
    )
