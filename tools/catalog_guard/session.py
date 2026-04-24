"""Explicit catalog edit session management."""

from bpfw.catalog.catalog_paths import list_catalog_yaml_files
from bpfw.catalog.file_permissions import (
    CatalogLockEnforcementError,
    apply_strong_lock,
    release_strong_lock,
)
from bpfw.catalog.state_file import read_state_file, write_state_file


class CatalogSessionAlreadyOpenError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "A catalog edit session is already open (status='unlocked'). "
            "Call close_catalog_session() before opening a new one."
        )


class CatalogSessionUnlockFailedError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(f"Unlock did not leave the catalog in a writable state: {detail}")


class CatalogSessionLockFailedError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(f"Lock did not leave the catalog in a read-only state: {detail}")


def open_catalog_session() -> None:
    current_state = read_state_file()
    if current_state["status"] == "unlocked":
        raise CatalogSessionAlreadyOpenError()

    yaml_files = list_catalog_yaml_files()
    lock_backend = current_state.get("lock_backend")
    if lock_backend != "linux_immutable":
        raise CatalogSessionUnlockFailedError(
            f"invalid or missing lock_backend for unlock: {lock_backend!r}"
        )
    try:
        release_strong_lock(yaml_files, lock_backend=lock_backend)
    except CatalogLockEnforcementError as permission_error:
        raise CatalogSessionUnlockFailedError(
            str(permission_error)
        ) from permission_error

    write_state_file(
        {
            "status": "unlocked",
            "lock_backend": None,
            "opened_at": None,
            "watcher_active": False,
            "last_event": None,
            "last_error": None,
        }
    )


def close_catalog_session() -> None:
    yaml_files = list_catalog_yaml_files()
    try:
        lock_backend = apply_strong_lock(yaml_files)
    except CatalogLockEnforcementError as permission_error:
        raise CatalogSessionLockFailedError(
            str(permission_error)
        ) from permission_error

    write_state_file(
        {
            "status": "locked",
            "lock_backend": lock_backend,
            "opened_at": None,
            "watcher_active": False,
            "last_event": None,
            "last_error": None,
        }
    )
