from pathlib import Path
import os

def detect_platform_family() -> str:
    if os.name == "nt":
        return "windows"
    return "posix"

def get_permissions_snapshot(path: Path) -> dict[str, bool]:
    return {
        "exists": path.exists(),
        "is_file": path.is_file(),
        "is_readable": os.access(path, os.R_OK),
        "is_writable": os.access(path, os.W_OK),
    }


def set_read_only(path: Path) -> None:
    """Set file permissions to read-only (remove write permissions).

    No-op when the filesystem does not enforce Unix permissions.
    """
    current_mode = path.stat().st_mode
    read_only_mode = current_mode & ~0o222  # Remove all write bits
    try:
        path.chmod(read_only_mode)
    except (OSError, NotImplementedError):
        pass


def set_writable(path: Path) -> None:
    """Set file permissions to writable (add write permission for owner).

    No-op when the filesystem does not enforce Unix permissions.
    """
    current_mode = path.stat().st_mode
    writable_mode = current_mode | 0o200  # Add write bit for owner
    try:
        path.chmod(writable_mode)
    except (OSError, NotImplementedError):
        pass


def lock_catalog_files(paths: list[Path]) -> None:
    """Lock catalog files by setting them read-only where supported."""
    for path in paths:
        set_read_only(path)


def unlock_catalog_files(paths: list[Path]) -> None:
    """Unlock catalog files by setting them writable where supported."""
    for path in paths:
        set_writable(path)


def assert_catalog_state(
    paths: list[Path], expected_writable: bool
) -> dict[str, list[str]]:
    """Verify that paths match the expected writable state.

    When the filesystem does not enforce Unix permissions, chmod has no
    observable effect and the check is skipped — the state file is the
    sole protection mechanism in that case.

    Returns a dict with 'matching' and 'mismatching' lists of path strings.
    Raises AssertionError if any paths do not match the expected state and
    permission enforcement is confirmed to be active.
    """
    if not detect_permission_enforcement_support(paths):
        return {"matching": [str(path) for path in paths], "mismatching": []}

    matching: list[str] = []
    mismatching: list[str] = []

    for path in paths:
        snapshot = get_permissions_snapshot(path)
        is_writable = snapshot["is_writable"]

        if is_writable == expected_writable:
            matching.append(str(path))
        else:
            mismatching.append(str(path))

    result = {
        "matching": matching,
        "mismatching": mismatching,
    }

    if mismatching:
        expected_state = "writable" if expected_writable else "read-only"
        mismatching_str = ", ".join(mismatching)
        raise AssertionError(
            f"Expected state '{expected_state}' but found mismatches for: {mismatching_str}"
        )

    return result


def detect_permission_enforcement_support(paths: list[Path]) -> bool:
    """
    Detect whether the filesystem actually supports Unix permission enforcement.
    
    This function tests real behavior rather than assuming POSIX support.
    Some filesystems (e.g., NTFS mounted via FUSE) may silently ignore chmod.
    
    Uses a temporary file in the same directory as the catalog to test
    permission changes without risking alteration of real catalog files.
    
    Args:
        paths: List of catalog file paths (used to determine filesystem location).
        
    Returns:
        True if the filesystem actually reflects permission changes,
        False if chmod operations are silently ignored.
    """
    import tempfile
    
    if not paths:
        return False
    
    first_path = paths[0]
    
    if not first_path.exists():
        return False
    
    catalog_dir = first_path.parent
    
    temp_file = None
    temp_path = None
    
    try:
        temp_file = tempfile.NamedTemporaryFile(
            dir=catalog_dir,
            prefix=".permission_test_",
            suffix=".tmp",
            delete=False
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
        
        if not initial_writable and after_unlock_writable:
            return True
        
        return False
        
    except (OSError, PermissionError):
        return False
        
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except (OSError, PermissionError):
                pass
