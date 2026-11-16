"""Crash-safe local persistence primitives for BPFW critical state.

The helpers in this module deliberately keep a very small surface area.  They
write into the destination directory, fsync the temporary file, atomically
replace the target, and best-effort fsync the containing directory.  This
prevents interrupted writes from leaving a partially-written authority or
state document visible to subsequent BPFW runs.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


def _fsync_directory(path: Path) -> None:
    """Best-effort fsync of a directory after rename/create operations."""
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Atomically replace *path* with *text*.

    If writing or replacing fails, the previous target remains untouched and
    the temporary file is removed.  Existing permission bits are preserved
    when the target already exists.
    """
    atomic_write_bytes(path, text.encode(encoding))


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomically replace *path* with *data*, with the same guarantees as atomic_write_text."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous_mode: int | None = None
    try:
        previous_mode = path.stat().st_mode & 0o7777
    except OSError:
        pass

    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if previous_mode is not None:
            temp_path.chmod(previous_mode)
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise



def atomic_copy_file(source: Path, target: Path) -> None:
    """Atomically restore *target* from *source* while preserving metadata.

    The backup remains untouched until the replacement succeeds.  This is used
    by authority rollback so an interrupted recovery cannot truncate the last
    known-good authority file.
    """
    source = Path(source)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{target.name}.restore.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    temp_path = Path(raw_temp)
    try:
        shutil.copy2(source, temp_path)
        with temp_path.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        _fsync_directory(target.parent)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise

def append_jsonl_durable(path: Path, payload: dict[str, Any]) -> None:
    """Append one JSON object durably while isolating a corrupt partial tail.

    JSONL is intentionally append-only for intent/evidence history.  If a
    previous process died after a partial write, a separating newline is added
    before the next valid record so readers can skip the damaged line rather
    than losing every later record.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n"
    needs_separator = False
    try:
        if path.exists() and path.stat().st_size:
            with path.open("rb") as reader:
                reader.seek(-1, os.SEEK_END)
                needs_separator = reader.read(1) != b"\n"
    except OSError:
        needs_separator = False

    with path.open("a", encoding="utf-8", newline="") as handle:
        if needs_separator:
            handle.write("\n")
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)
