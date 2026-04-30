"""Blueprint protection authority for BPFW MVP Catalog Mode."""

from pathlib import Path

from bpfw.catalog.paths import CANONICAL_BLUEPRINT_FILE
from bpfw.protection.os_lock import get_file_lock_state, lock_file, unlock_file


def lock_blueprint(project_root: Path) -> str:
    """Lock the canonical MVP blueprint resource."""

    return lock_file(project_root=project_root, relative_path=CANONICAL_BLUEPRINT_FILE)


def unlock_blueprint(project_root: Path) -> str:
    """Unlock the canonical MVP blueprint resource."""

    return unlock_file(project_root=project_root, relative_path=CANONICAL_BLUEPRINT_FILE)


def get_blueprint_lock_state(project_root: Path) -> str:
    """Return the lock state for the canonical MVP blueprint resource."""

    return get_file_lock_state(project_root=project_root, relative_path=CANONICAL_BLUEPRINT_FILE)
