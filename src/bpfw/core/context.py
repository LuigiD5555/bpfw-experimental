"""PURPOSE execution context models for BPFW pipelines
DOMAIN  framework core
"""

from dataclasses import dataclass, field
from pathlib import Path

from bpfw.core.catalog.paths import CANONICAL_BLUEPRINT_FILE


@dataclass(slots=True)
class EngineCommand:
    """PURPOSE user command clean for stable engine execution
    DOMAIN  framework core
    """

    command_name: str
    project_root: Path
    arguments: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ProjectContext:
    """PURPOSE runtime context shared across pipeline steps
    DOMAIN  framework core
    """

    project_root: Path
    blueprint_file: Path
    command_arguments: dict[str, str] = field(default_factory=dict)
    runtime_cache: dict[str, object] = field(default_factory=dict)


def build_project_context(project_root: Path, command_arguments: dict[str, str] | None = None) -> ProjectContext:
    """PURPOSE build a minimal project context used by engine pipelines
    DOMAIN  framework core
    """

    return ProjectContext(
        project_root=project_root,
        blueprint_file=project_root / CANONICAL_BLUEPRINT_FILE,
        command_arguments=command_arguments or {},
    )
