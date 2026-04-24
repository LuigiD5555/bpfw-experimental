"""Strong filesystem lock helpers for catalog YAML files."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Literal

CatalogLockBackend = Literal["linux_immutable"]


class CatalogLockEnforcementError(RuntimeError):
    """Raised when a strong filesystem lock cannot be guaranteed."""


def _require_linux_immutable_support() -> None:
    if os.name != "posix":
        raise CatalogLockEnforcementError("linux_immutable backend requires a POSIX/Linux runtime.")
    chattr_path = shutil.which("chattr")
    if not chattr_path:
        raise CatalogLockEnforcementError("chattr is not available; cannot enforce immutable lock.")
    if os.geteuid() != 0:
        raise CatalogLockEnforcementError(
            "linux_immutable backend requires root privileges. Run 'bpfw lock' with sudo."
        )


def _run_chattr(flag: str, path: Path) -> None:
    command = ["chattr", flag, str(path)]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise CatalogLockEnforcementError(
            f"chattr {flag} failed for '{path}': {stderr or 'unknown error'}"
        )


def _can_open_for_write(path: Path) -> bool:
    try:
        with path.open("r+b"):
            return True
    except (PermissionError, OSError):
        return False


def verify_write_block(paths: list[Path]) -> bool:
    """Return True when every catalog file rejects direct write opening."""
    if not paths:
        return False
    for path in paths:
        if not path.exists() or not path.is_file():
            return False
        if _can_open_for_write(path):
            return False
    return True


def apply_strong_lock(paths: list[Path]) -> CatalogLockBackend:
    """Apply strong lock and verify mutation is blocked at filesystem level."""
    if not paths:
        raise CatalogLockEnforcementError("No catalog files available to lock.")
    _require_linux_immutable_support()

    locked_paths: list[Path] = []
    try:
        for path in paths:
            if not path.exists() or not path.is_file():
                raise CatalogLockEnforcementError(f"Catalog file not found: {path}")
            _run_chattr("+i", path)
            locked_paths.append(path)
    except Exception:
        for locked_path in reversed(locked_paths):
            try:
                _run_chattr("-i", locked_path)
            except CatalogLockEnforcementError:
                pass
        raise

    if not verify_write_block(paths):
        raise CatalogLockEnforcementError(
            "Filesystem did not enforce write blocking after immutable lock."
        )

    return "linux_immutable"


def release_strong_lock(paths: list[Path], lock_backend: CatalogLockBackend) -> None:
    """Release a strong lock previously applied with *lock_backend*."""
    if lock_backend != "linux_immutable":
        raise CatalogLockEnforcementError(f"Unsupported lock backend: {lock_backend}")
    if not paths:
        raise CatalogLockEnforcementError("No catalog files available to unlock.")
    _require_linux_immutable_support()

    for path in paths:
        if not path.exists() or not path.is_file():
            raise CatalogLockEnforcementError(f"Catalog file not found: {path}")
        _run_chattr("-i", path)

    blocked_after_unlock = verify_write_block(paths)
    if blocked_after_unlock:
        raise CatalogLockEnforcementError(
            "Filesystem still blocks writes after immutable unlock."
        )

