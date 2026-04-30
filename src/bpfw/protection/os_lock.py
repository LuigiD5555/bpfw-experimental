"""Logical file lock backend for BPFW MVP Catalog Mode."""

from pathlib import Path

LOCKED = "locked"
UNLOCKED = "unlocked"
UNKNOWN = "unknown"
UNSUPPORTED = "unsupported"


def _lock_path(project_root: Path) -> Path:
    return project_root / "bpfw" / ".lock"


def _lock_content(relative_path: str) -> str:
    return f"locked: true\nresource: {relative_path}\n"


def lock_file(project_root: Path, relative_path: str) -> str:
    """Create a logical lock marker for a project-relative file."""

    target_path = project_root / relative_path
    if not target_path.exists():
        return UNKNOWN

    lock_path = _lock_path(project_root=project_root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(_lock_content(relative_path=relative_path), encoding="utf-8")
    return LOCKED


def unlock_file(project_root: Path, relative_path: str) -> str:
    """Remove the logical lock marker for a project-relative file."""

    target_path = project_root / relative_path
    if not target_path.exists():
        return UNKNOWN

    lock_path = _lock_path(project_root=project_root)
    if lock_path.exists():
        lock_path.unlink()
    return UNLOCKED


def get_file_lock_state(project_root: Path, relative_path: str) -> str:
    """Read the logical lock state for a project-relative file."""

    target_path = project_root / relative_path
    if not target_path.exists():
        return UNKNOWN

    lock_path = _lock_path(project_root=project_root)
    if not lock_path.exists():
        return UNLOCKED

    content = lock_path.read_text(encoding="utf-8")
    expected_resource_line = f"resource: {relative_path}"
    if "locked: true" in content and expected_resource_line in content:
        return LOCKED
    return UNLOCKED
