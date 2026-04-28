"""Composition root resolution from architecture profile."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bpfw.architecture.profile import ArchitectureLoadError, load_architecture_data


@dataclass(slots=True)
class CompositionRoots:
    """Resolved composition root files and bootstrap base path."""

    root_files: set[Path]
    bootstrap_root: Path


class CompositionRootError(RuntimeError):
    """Raised when composition roots cannot be resolved."""



def _is_repo_safe_path(value: str) -> bool:
    candidate = Path(value)
    if candidate.is_absolute():
        return False
    for part in candidate.parts:
        if part == "..":
            return False
    return True



def resolve_composition_roots(project_root: Path) -> CompositionRoots:
    """Resolve configured composition roots declared in architecture.yaml."""

    try:
        _, payload = load_architecture_data(project_root=project_root)
    except ArchitectureLoadError as error:
        raise CompositionRootError(str(error)) from error

    roots_value = payload.get("composition_roots")
    architecture_profile = payload.get("architecture_profile")
    if roots_value is None and isinstance(architecture_profile, dict):
        roots_value = architecture_profile.get("composition_roots")

    if not isinstance(roots_value, list) or not roots_value:
        raise CompositionRootError("composition_roots must be a non-empty list in architecture.yaml")

    resolved_roots: set[Path] = set()
    for root_value in roots_value:
        root_text = str(root_value).strip()
        if not _is_repo_safe_path(root_text):
            raise CompositionRootError(f"Invalid composition root path: {root_text}")
        resolved_roots.add((project_root / root_text).resolve())

    return CompositionRoots(root_files=resolved_roots, bootstrap_root=(project_root / "src/bootstrap").resolve())



def is_authorized_composition_file(file_path: Path, composition_roots: CompositionRoots) -> bool:
    """Return whether file is authorized to perform concrete wiring."""

    candidate_path = file_path.resolve()
    if candidate_path in composition_roots.root_files:
        return True
    try:
        candidate_path.relative_to(composition_roots.bootstrap_root)
        return True
    except ValueError:
        return False
