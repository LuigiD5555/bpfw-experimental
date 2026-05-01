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

_FALLBACK_LOCK_PATH = "bpfw/.lock"


def _existing_authority_files(project_root: Path) -> tuple[str, ...]:
    return tuple(
        relative_path
        for relative_path in CRITICAL_AUTHORITY_FILES
        if (project_root / relative_path).exists()
    )


def _write_fallback_lock(project_root: Path) -> None:
    """Write a logical-only lock marker when OS enforcement is unavailable."""
    lock_path = project_root / _FALLBACK_LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        f"locked: true\nresource: {CANONICAL_BLUEPRINT_FILE}\n",
        encoding="utf-8",
    )


def _remove_fallback_lock(project_root: Path) -> None:
    """Remove the logical-only lock marker if it exists."""
    lock_path = project_root / _FALLBACK_LOCK_PATH
    if lock_path.exists():
        lock_path.unlink()


def _is_fallback_locked(project_root: Path) -> bool:
    """Check whether the fallback logical lock marker is present."""
    lock_path = project_root / _FALLBACK_LOCK_PATH
    if not lock_path.exists():
        return False
    content = lock_path.read_text(encoding="utf-8")
    return "locked: true" in content and CANONICAL_BLUEPRINT_FILE in content


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
    """Lock the canonical MVP blueprint resource.

    Attempts OS-level enforcement only. When the OS lock cannot be
    enforced (for example on a filesystem that does not support chmod
    or chattr), the command reports ``unsupported`` instead of claiming
    that the blueprint is protected.
    """

    if not (project_root / CANONICAL_BLUEPRINT_FILE).exists():
        return "unknown"

    result = lock_file(project_root=project_root, relative_path=CANONICAL_BLUEPRINT_FILE)
    if result != "locked":
        _remove_fallback_lock(project_root=project_root)
        return result
    return "locked"


def unlock_blueprint(project_root: Path) -> str:
    """Unlock the canonical MVP blueprint resource."""

    if not (project_root / CANONICAL_BLUEPRINT_FILE).exists():
        return "unknown"

    result = unlock_file(project_root=project_root, relative_path=CANONICAL_BLUEPRINT_FILE)
    _remove_fallback_lock(project_root=project_root)
    return result


def get_blueprint_lock_state(project_root: Path) -> str:
    """Return the lock state for the canonical MVP blueprint resource."""

    if not (project_root / CANONICAL_BLUEPRINT_FILE).exists():
        return "unknown"

    result = get_file_lock_state(project_root=project_root, relative_path=CANONICAL_BLUEPRINT_FILE)
    if result == "locked":
        return "locked"

    _remove_fallback_lock(project_root=project_root)
    return "unlocked"
