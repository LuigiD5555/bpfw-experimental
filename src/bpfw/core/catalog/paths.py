"""PURPOSE path resolution utilities for BPFW blueprint.yaml
DOMAIN  blueprint checks
"""

from pathlib import Path
from typing import Optional

CANONICAL_BLUEPRINT_FILE = "bpfw/blueprint.yaml"
CANONICAL_BLOCKS_DIR = "bpfw/blocks"
DEFAULT_CORE_SHARD = "bpfw/blocks/core.yaml"


def resolve_project_root(explicit_project_root: Optional[Path] = None) -> Path:
    """PURPOSE find the project root directory
    DOMAIN  blueprint checks
    """
    if explicit_project_root is not None:
        return explicit_project_root.resolve()
    return Path.cwd().resolve()


def resolve_blueprint_path(project_root: Path) -> Path:
    """PURPOSE find the path to bpfw/blueprint.yaml
    DOMAIN  blueprint checks
    """
    return project_root / CANONICAL_BLUEPRINT_FILE


def resolve_blocks_directory(project_root: Path) -> Path:
    """PURPOSE find the path to bpfw/blocks directory
    DOMAIN  blueprint checks
    """
    return project_root / CANONICAL_BLOCKS_DIR


def resolve_shard_path(project_root: Path, shard_name: str) -> Path:
    """PURPOSE find the path to a specific shard file
    DOMAIN  blueprint checks
    """
    return project_root / CANONICAL_BLOCKS_DIR / shard_name