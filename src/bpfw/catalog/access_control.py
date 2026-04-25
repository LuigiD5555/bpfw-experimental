"""Catalog access control: enforce guard state before any read/write operations.

This module ensures that the catalog state file is consulted before any
attempt to load or modify catalog YAML files. When the catalog is locked,
all operations fail fast with a clear error message.

On filesystems without Unix permission enforcement (e.g. NTFS via FUSE),
the guard state file is the only protection mechanism.
"""

from bpfw.catalog.state_file import (
    CatalogGuardStateFileNotFoundError,
    read_state_file,
)


class CatalogLockedError(RuntimeError):
    """Raised when attempting to access a locked catalog."""

    def __init__(self) -> None:
        super().__init__(
            "Catalog is locked. "
            "Run: python -m tools.catalog_protection.unlock_catalog"
        )


class CatalogStateCheckError(RuntimeError):
    """Raised when the guard state file cannot be read or is invalid."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"Cannot verify catalog lock state: {detail}")


def assert_catalog_unlocked() -> None:
    """Verify that the catalog is unlocked before allowing any access.

    Checks the real lock state via the active strategy (chmod/ACL/git).
    This is the authoritative check — not the state file alone.

    Raises:
        CatalogLockedError: If the catalog is locked.
        CatalogStateCheckError: If the lock state cannot be determined.
    """
    try:
        from bpfw.catalog.authority import is_locked_real
        if is_locked_real():
            raise CatalogLockedError()
    except CatalogLockedError:
        raise
    except Exception as exc:
        raise CatalogStateCheckError(str(exc)) from exc
