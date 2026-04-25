"""Runtime integrity validation for locked catalogs.

This module enforces catalog immutability at runtime by:
1. Computing hashes of catalog files when locking
2. Verifying hashes match stored hashes at application startup
3. Raising an error if catalog was modified while locked
"""

import hashlib
from pathlib import Path

from bpfw.catalog.authority import is_locked_real
from bpfw.catalog.catalog_hashes import read_hashes_file, compute_catalog_hashes
from bpfw.catalog.catalog_paths import get_catalog_directory, get_repo_root


class CatalogTamperDetectedError(RuntimeError):
    """Raised when catalog files were modified while locked."""

    def __init__(self, modified_files: list[str]) -> None:
        files_str = "\n  ".join(modified_files)
        super().__init__(
            f"CRITICAL: Catalog was locked but files were modified:\n  {files_str}\n"
            f"\nThis indicates a security breach. The catalog must be re-locked immediately:\n"
            f"  bpfw lock"
        )


def validate_catalog_integrity() -> None:
    """Validate catalog integrity at runtime.

    If catalog is locked and hashes don't match, raise CatalogTamperDetectedError.
    This prevents the application from running with a tampered catalog.

    Raises:
        CatalogTamperDetectedError: If locked catalog has been modified
    """
    if not is_locked_real():
        return

    try:
        repo_root = get_repo_root()
        hashes_path = repo_root / "src" / ".catalog" / "hashes.lock"

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
    except Exception as e:
        raise RuntimeError(f"Cannot validate catalog integrity: {e}") from e
