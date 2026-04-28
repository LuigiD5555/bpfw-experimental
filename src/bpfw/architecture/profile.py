"""Architecture profile models and loading helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(slots=True)
class LayerProfile:
    """One architecture layer with import permissions."""

    name: str
    path: str
    may_import: list[str]


@dataclass(slots=True)
class ArchitectureProfile:
    """Declared architecture profile loaded from architecture.yaml."""

    profile_id: str
    layers: list[LayerProfile]
    composition_roots: list[str] = field(default_factory=list)
    source_path: Path | None = None


class ArchitectureLoadError(RuntimeError):
    """Raised when architecture file cannot be loaded or parsed."""



def load_architecture_data(project_root: Path) -> tuple[Path, dict]:
    """Load raw architecture.yaml payload from repository root."""

    architecture_path = project_root / "architecture.yaml"
    if not architecture_path.exists():
        raise ArchitectureLoadError("architecture.yaml does not exist")

    try:
        raw_content = yaml.safe_load(architecture_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ArchitectureLoadError(f"Invalid YAML in architecture.yaml: {error}") from error

    if raw_content is None:
        return architecture_path, {}
    if not isinstance(raw_content, dict):
        raise ArchitectureLoadError("architecture.yaml root must be a mapping")

    return architecture_path, raw_content
