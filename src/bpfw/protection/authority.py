"""Blueprint protection authority for BPFW MVP Catalog Mode."""

from pathlib import Path

from bpfw.catalog.paths import CANONICAL_BLUEPRINT_FILE
from bpfw.protection.os_lock import get_file_lock_state, lock_file, unlock_file

CRITICAL_AUTHORITY_FILES = (
    "src/bpfw/protection/os_lock.py",
    "src/bpfw/protection/authority.py",
    "src/bpfw/protection/setup.py",
    "src/bpfw/catalog/access_control.py",
    CANONICAL_BLUEPRINT_FILE,
)


def _existing_authority_files(project_root: Path) -> tuple[str, ...]:
    return tuple(
        relative_path
        for relative_path in CRITICAL_AUTHORITY_FILES
        if (project_root / relative_path).exists()
    )


def setup_blueprint_protection(project_root: Path) -> str:
    """Prepare strong protection for authority resources."""

    if not (project_root / CANONICAL_BLUEPRINT_FILE).exists():
        return "unknown"

    locked_paths: list[str] = []
    for relative_path in _existing_authority_files(project_root=project_root):
        state = lock_file(project_root=project_root, relative_path=relative_path)
        if state == "locked":
            locked_paths.append(relative_path)
            continue
        for locked_path in reversed(locked_paths):
            unlock_file(project_root=project_root, relative_path=locked_path)
        return state

    if locked_paths:
        return "locked"
    return "unsupported"


def lock_blueprint(project_root: Path) -> str:
    """Lock MVP authority resources."""

    return setup_blueprint_protection(project_root=project_root)


def unlock_blueprint(project_root: Path) -> str:
    """Unlock MVP authority resources."""

    if not (project_root / CANONICAL_BLUEPRINT_FILE).exists():
        return "unknown"

    states = [
        unlock_file(project_root=project_root, relative_path=relative_path)
        for relative_path in reversed(_existing_authority_files(project_root=project_root))
    ]
    if all(state == "unlocked" for state in states):
        return "unlocked"
    return "unsupported"


def get_blueprint_lock_state(project_root: Path) -> str:
    """Return the lock state for the canonical MVP blueprint resource."""

    return get_file_lock_state(project_root=project_root, relative_path=CANONICAL_BLUEPRINT_FILE)
