"""Runtime integrity validation for locked catalogs.

This module enforces catalog immutability at runtime by:
1. Computing hashes of catalog files when locking
2. Verifying hashes match stored hashes at application startup
3. Raising an error if catalog was modified while locked
"""

from pathlib import Path
import sys

from bpfw.catalog.catalog_hashes import read_hashes_file, compute_catalog_hashes
from bpfw.catalog.catalog_paths import get_catalog_directory, get_repo_root
from bpfw.catalog.state_file import read_state_file
from bpfw.catalog.signature import verify_hashes_lock, verify_lockstate


class CatalogTamperDetectedError(RuntimeError):
    """Raised when catalog files were modified while locked."""

    def __init__(self, modified_files: list[str]) -> None:
        files_str = "\n  ".join(modified_files)
        super().__init__(
            f"CRITICAL: Catalog was locked but files were modified:\n  {files_str}\n"
            f"\nThis indicates a security breach. The catalog must be re-locked immediately:\n"
            f"  bpfw lock"
        )


def validate_catalog_integrity(password: str | None = None) -> None:
    """Validate catalog integrity at runtime.

    If catalog is locked (per lockstate.json) and hashes don't match,
    raise CatalogTamperDetectedError. This prevents the application from
    running with a tampered catalog.

    Also verifies digital signatures if password is provided.

    Args:
        password: User password for verifying HMAC signatures (optional)

    Raises:
        CatalogTamperDetectedError: If locked catalog has been modified
    """
    try:
        state = read_state_file()
    except RuntimeError:
        return

    if state.get("status") != "locked":
        return

    try:
        repo_root = get_repo_root()
        hashes_path = repo_root / "src" / ".catalog" / "hashes.lock"
        lockstate_path = repo_root / ".catalog" / "lockstate.json"

        # Verify digital signatures if available and password provided
        if password and sys.platform != "win32":
            if not verify_hashes_lock(hashes_path, password):
                raise CatalogTamperDetectedError([str(hashes_path)])
            if not verify_lockstate(lockstate_path, password):
                raise CatalogTamperDetectedError([str(lockstate_path)])

        catalog_dir = get_catalog_directory()
        yaml_files = sorted(catalog_dir.glob("*.yaml"))

        stored_hashes = read_hashes_file(hashes_path)
        current_hashes = compute_catalog_hashes(yaml_files)

        modified = []
        for path_str, current_hash in current_hashes.items():
            stored_hash = stored_hashes.get(path_str)
            if stored_hash != current_hash:
                modified.append(path_str)

        if modified:
            raise CatalogTamperDetectedError(modified)
    except CatalogTamperDetectedError:
        raise
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Cannot validate catalog integrity: {e}") from e
