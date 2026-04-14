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

    Checks the guard state file. If status is 'locked', raises CatalogLockedError.
    If the state file does not exist, treats it as 'unlocked' (backward compatibility
    for initial state).

    Raises:
        CatalogLockedError: If the catalog is locked.
        CatalogStateCheckError: If the state file cannot be read or validated.
    """
    try:
        state = read_state_file()
    except CatalogGuardStateFileNotFoundError:
        # State file doesn't exist yet — treat as unlocked (first run).
        return
    except Exception as exc:
        raise CatalogStateCheckError(str(exc)) from exc

    if state.get("status") == "locked":
        raise CatalogLockedError()
