"""Path resolution utilities for BPFW blueprint.yaml."""

from pathlib import Path
from typing import Optional

CANONICAL_BLUEPRINT_FILE = "bpfw/blueprint.yaml"
CANONICAL_BLOCKS_DIR = "bpfw/blocks"
DEFAULT_CORE_SHARD = "bpfw/blocks/core.yaml"


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
    return project_root / CANONICAL_BLUEPRINT_FILE


def resolve_blocks_directory(project_root: Path) -> Path:
    """Resolve the path to bpfw/blocks directory.

    Args:
        project_root: The project root directory.

    Returns:
        Path to bpfw/blocks directory relative to project root.
    """
    return project_root / CANONICAL_BLOCKS_DIR


def resolve_shard_path(project_root: Path, shard_name: str) -> Path:
    """Resolve the path to a specific shard file.

    Args:
        project_root: The project root directory.
        shard_name: Name of the shard file (e.g., "core.yaml").

    Returns:
        Path to the shard file relative to project root.
    """
    return project_root / CANONICAL_BLOCKS_DIR / shard_name