"""Explicit catalog edit session management."""

from bpfw.catalog.catalog_paths import list_catalog_yaml_files
from bpfw.catalog.file_permissions import (
    assert_catalog_state,
    lock_catalog_files,
    unlock_catalog_files,
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
    try:
        unlock_catalog_files(yaml_files)
    except PermissionError as permission_error:
        raise CatalogSessionUnlockFailedError(
            f"insufficient OS permissions: {permission_error}"
        ) from permission_error

    try:
        assert_catalog_state(yaml_files, expected_writable=True)
    except AssertionError as assertion_error:
        raise CatalogSessionUnlockFailedError(str(assertion_error)) from assertion_error

    write_state_file(
        {
            "status": "unlocked",
            "opened_at": None,
            "watcher_active": False,
            "last_event": None,
            "last_error": None,
        }
    )


def close_catalog_session() -> None:
    yaml_files = list_catalog_yaml_files()
    try:
        lock_catalog_files(yaml_files)
    except PermissionError as permission_error:
        raise CatalogSessionLockFailedError(
            f"insufficient OS permissions: {permission_error}"
        ) from permission_error

    try:
        assert_catalog_state(yaml_files, expected_writable=False)
    except AssertionError as assertion_error:
        raise CatalogSessionLockFailedError(str(assertion_error)) from assertion_error

    write_state_file(
        {
            "status": "locked",
            "opened_at": None,
            "watcher_active": False,
            "last_event": None,
            "last_error": None,
        }
    )
