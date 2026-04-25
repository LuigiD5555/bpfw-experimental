"""SHA-256 hash management for catalog integrity verification."""

import hashlib
import json
from pathlib import Path


def compute_file_hash(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def compute_catalog_hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path): compute_file_hash(path) for path in paths}


def read_hashes_file(hashes_path: Path) -> dict[str, str]:
    if not hashes_path.exists():
        return {}
    try:
        return json.loads(hashes_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_hashes_file(hashes_path: Path, hashes: dict[str, str]) -> None:
    hashes_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = hashes_path.parent / f".{hashes_path.name}.tmp"
    temp_path.write_text(json.dumps(hashes, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(hashes_path)


def verify_catalog_hashes(paths: list[Path], hashes_path: Path) -> tuple[bool, list[str]]:
    """Verify that current file hashes match stored hashes.

    Returns:
        (all_match, list_of_modified_files)
    """
    stored_hashes = read_hashes_file(hashes_path)
    current_hashes = compute_catalog_hashes(paths)

    modified = []
    for path_str, current_hash in current_hashes.items():
        stored_hash = stored_hashes.get(path_str)
        if stored_hash != current_hash:
            modified.append(path_str)

    return len(modified) == 0, modified
