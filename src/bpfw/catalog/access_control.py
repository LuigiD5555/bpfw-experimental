"""Catalog access control helpers for write-mutability enforcement.

Lock status is enforced as an anti-mutability guard:
- Reads/validation are allowed when the catalog is locked.
- Write-like operations (updates, generation, auto-refresh) must fail fast.

On filesystems without Unix permission enforcement (e.g. NTFS via FUSE),
the guard state file is the primary protection mechanism.
"""

import os
from pathlib import Path

from bpfw.catalog.catalog_paths import (
    CatalogDirectoryNotFoundError,
    CatalogFilesNotFoundError,
    list_catalog_yaml_files,
)
from bpfw.catalog.file_permissions import verify_write_block
from bpfw.catalog.state_file import (
    CatalogGuardStateFileNotFoundError,
    read_state_file,
)


class CatalogLockedError(RuntimeError):
    """Raised when attempting a write-like operation on a locked catalog."""

    def __init__(self) -> None:
        super().__init__("Catalog is locked for writes. Unlock or use SUDO authorization.")


class CatalogStateCheckError(RuntimeError):
    """Raised when the guard state file cannot be read or is invalid."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"Cannot verify catalog lock state: {detail}")


class ExternalCatalogWriteBlockedError(RuntimeError):
    """Raised when write-like operations target an external project root."""

    def __init__(self, project_root: Path, cwd_root: Path) -> None:
        super().__init__(
            "External catalog write blocked: "
            f"BPFW_PROJECT_ROOT points to '{project_root}', "
            f"but current working directory is '{cwd_root}'. "
            "To allow this intentionally, set BPFW_ALLOW_EXTERNAL_CATALOG_WRITES=1."
        )


def _is_truthy_env(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def assert_catalog_write_scope() -> None:
    """Block external write targets unless explicitly authorized.

    Write-like operations are only allowed by default when the target project
    root is the current working directory. If BPFW_PROJECT_ROOT points to a
    different directory, the operation fails unless
    BPFW_ALLOW_EXTERNAL_CATALOG_WRITES is set to a truthy value.
    """
    explicit_root = os.environ.get("BPFW_PROJECT_ROOT")
    if not explicit_root:
        return
    if _is_truthy_env(os.environ.get("BPFW_ALLOW_EXTERNAL_CATALOG_WRITES")):
        return

    project_root = Path(explicit_root).expanduser().resolve()
    cwd_root = Path.cwd().resolve()
    if project_root != cwd_root:
        raise ExternalCatalogWriteBlockedError(project_root=project_root, cwd_root=cwd_root)


def is_catalog_locked() -> bool:
    """Return True when the catalog lock state is currently ``locked``.

    Missing state file is treated as unlocked for backward compatibility.
    """
    try:
        state = read_state_file()
    except CatalogGuardStateFileNotFoundError:
        return False
    except Exception as exc:
        raise CatalogStateCheckError(str(exc)) from exc
    state_locked = state.get("status") == "locked"
    try:
        catalog_yaml_files = list_catalog_yaml_files()
        write_block_active = verify_write_block(catalog_yaml_files)
    except (CatalogDirectoryNotFoundError, CatalogFilesNotFoundError):
        return state_locked
    except Exception as exc:
        raise CatalogStateCheckError(f"Cannot verify filesystem lock enforcement: {exc}") from exc

    if state_locked and not write_block_active:
        raise CatalogStateCheckError(
            "Inconsistent lock state: lockstate says 'locked' but catalog files are writable."
        )
    if (not state_locked) and write_block_active:
        raise CatalogStateCheckError(
            "Inconsistent lock state: lockstate says 'unlocked' but catalog files are write-blocked."
        )
    return state_locked


def assert_catalog_writable() -> None:
    """Verify that write-like catalog operations are currently allowed.

    Raises:
        CatalogLockedError: If the catalog is locked.
        CatalogStateCheckError: If the state file cannot be read or validated.
    """
    if is_catalog_locked():
        raise CatalogLockedError()
