"""Path resolution utilities for BPFW blueprint.yaml."""

from pathlib import Path
from typing import Optional


def resolve_project_root(explicit_project_root: Optional[Path] = None) -> Path:
    """Resolve the project root directory.
    
    Args:
        explicit_project_root: If provided, return it resolved. Otherwise, return Path.cwd().
    
    Returns:
        Resolved project root path.
    """
    if explicit_project_root is not None:
        return explicit_project_root.resolve()
    return Path.cwd().resolve()


def resolve_blueprint_path(project_root: Path) -> Path:
    """Resolve the path to bpfw/blueprint.yaml.
    
    Args:
        project_root: The project root directory.
    
    Returns:
        Path to bpfw/blueprint.yaml relative to project root.
    """
    return project_root / "bpfw" / "blueprint.yaml"