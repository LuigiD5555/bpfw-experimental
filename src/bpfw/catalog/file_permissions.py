"""Permission helpers for catalog lock/unlock operations."""

import os
import tempfile
from pathlib import Path


def get_permissions_snapshot(path: Path) -> dict[str, bool]:
    return {
        "exists": path.exists(),
        "is_file": path.is_file(),
        "is_readable": os.access(path, os.R_OK),
        "is_writable": os.access(path, os.W_OK),
    }


def set_read_only(path: Path) -> None:
    current_mode = path.stat().st_mode
    read_only_mode = current_mode & ~0o222
    try:
        path.chmod(read_only_mode)
    except (OSError, NotImplementedError):
        pass


def set_writable(path: Path) -> None:
    current_mode = path.stat().st_mode
    writable_mode = current_mode | 0o200
    try:
        path.chmod(writable_mode)
    except (OSError, NotImplementedError):
        pass


def lock_catalog_files(paths: list[Path]) -> None:
    for path in paths:
        set_read_only(path)


def unlock_catalog_files(paths: list[Path]) -> None:
    for path in paths:
        set_writable(path)


def detect_permission_enforcement_support(paths: list[Path]) -> bool:
    if not paths:
        return False
    first_path = paths[0]
    if not first_path.exists():
        return False

    catalog_directory = first_path.parent
    temp_path: Path | None = None
    try:
        temp_file = tempfile.NamedTemporaryFile(
            dir=catalog_directory,
            prefix=".permission_test_",
            suffix=".tmp",
            delete=False,
        )
        temp_path = Path(temp_file.name)
        temp_file.close()

        initial_mode = temp_path.stat().st_mode
        initial_writable = os.access(temp_path, os.W_OK)

        read_only_mode = initial_mode & ~0o222
        temp_path.chmod(read_only_mode)
        after_lock_writable = os.access(temp_path, os.W_OK)

        if initial_writable and not after_lock_writable:
            return True
        if initial_writable and after_lock_writable:
            return False

        writable_mode = initial_mode | 0o200
        temp_path.chmod(writable_mode)
        after_unlock_writable = os.access(temp_path, os.W_OK)
        return (not initial_writable) and after_unlock_writable
    except (OSError, PermissionError):
        return False
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except (OSError, PermissionError):
                pass


def assert_catalog_state(paths: list[Path], expected_writable: bool) -> dict[str, list[str]]:
    if not detect_permission_enforcement_support(paths):
        return {"matching": [str(path) for path in paths], "mismatching": []}

    matching: list[str] = []
    mismatching: list[str] = []
    for path in paths:
        is_writable = get_permissions_snapshot(path)["is_writable"]
        if is_writable == expected_writable:
            matching.append(str(path))
        else:
            mismatching.append(str(path))

    if mismatching:
        expected_state = "writable" if expected_writable else "read-only"
        raise AssertionError(
            f"Expected state '{expected_state}' but found mismatches for: {', '.join(mismatching)}"
        )
    return {"matching": matching, "mismatching": mismatching}

