"""Hashing helpers for integrity manifest operations."""

from __future__ import annotations

import hashlib
from pathlib import Path


_READ_CHUNK_BYTES = 1024 * 1024


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 digest for a file path."""

    sha256 = hashlib.sha256()
    with file_path.open("rb") as file_pointer:
        while True:
            chunk = file_pointer.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


def read_file_size(file_path: Path) -> int:
    """Read file size in bytes."""

    return file_path.stat().st_size
