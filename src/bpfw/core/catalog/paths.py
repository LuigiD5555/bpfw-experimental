"""Path resolution utilities for BPFW blueprint authority files."""

from pathlib import Path
from typing import Optional

AUTHORITY_DIRECTORY_NAME = ".bpfw"
CANONICAL_BLUEPRINT_FILE = ".bpfw/blueprint.yaml"
CANONICAL_BLOCKS_DIR = ".bpfw/blocks"
CANONICAL_CACHE_DIR = ".bpfw/cache"
CANONICAL_LOCKS_DIR = ".bpfw/locks"
DEFAULT_CORE_SHARD = ".bpfw/blocks/core.yaml"


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
    """Resolve the path to the canonical blueprint authority file.

    Args:
        project_root: The project root directory.

    Returns:
        Path to the canonical blueprint authority file relative to project root.
    """
    return project_root / CANONICAL_BLUEPRINT_FILE


def resolve_blocks_directory(project_root: Path) -> Path:
    """Resolve the path to the canonical authority blocks directory.

    Args:
        project_root: The project root directory.

    Returns:
        Path to the canonical authority blocks directory relative to project root.
    """
    return project_root / CANONICAL_BLOCKS_DIR


def resolve_shard_path(project_root: Path, shard_name: str) -> Path:
    """Resolve the path to a specific canonical shard file.

    Args:
        project_root: The project root directory.
        shard_name: Name of the shard file (e.g., "core.yaml").

    Returns:
        Path to the shard file relative to project root.
    """
    return project_root / CANONICAL_BLOCKS_DIR / shard_name
