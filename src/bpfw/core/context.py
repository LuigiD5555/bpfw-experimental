"""Execution context models for BPFW pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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



def build_project_context(project_root: Path) -> ProjectContext:
    """Build a minimal project context used by Prompt 0 skeleton pipelines."""

    return ProjectContext(
        project_root=project_root,
        blueprint_file=project_root / "blueprint.yaml",
        architecture_file=project_root / "architecture.yaml",
        lifecycle_file=project_root / "lifecycle.yaml",
    )
