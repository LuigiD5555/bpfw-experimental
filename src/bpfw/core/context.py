"""Execution context models for BPFW pipelines."""

from dataclasses import dataclass, field
from pathlib import Path

from bpfw.core.catalog.paths import CANONICAL_BLUEPRINT_FILE


@dataclass(slots=True)
class EngineCommand:
    """User command clean for stable engine execution."""

    command_name: str
    project_root: Path
    arguments: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ProjectContext:
    """Runtime context shared across pipeline steps."""

    project_root: Path
    blueprint_file: Path
    command_arguments: dict[str, str] = field(default_factory=dict)
    runtime_cache: dict[str, object] = field(default_factory=dict)


def build_project_context(project_root: Path, command_arguments: dict[str, str] | None = None) -> ProjectContext:
    """Build a minimal project context used by engine pipelines."""

    return ProjectContext(
        project_root=project_root,
        blueprint_file=project_root / CANONICAL_BLUEPRINT_FILE,
        command_arguments=command_arguments or {},
    )
